# frozen_string_literal: true

require "mini_magick"

# List and selectively extract entries from library archives (zip/7z/rar/…)
# without expanding the whole archive into the model folder.
class ArchiveEntryService
  # Soft safety only — personal library may have huge packs; list everything we can.
  MAX_LIST_ENTRIES = 100_000

  class EntryTooLarge < StandardError; end
  class EntryNotFound < StandardError; end
  class UnsafePath < StandardError; end

  def initialize(model_file)
    @model_file = model_file
    @model = model_file.model
    @library = @model.library
  end

  def list!
    raise ArgumentError, "not an archive" unless @model_file.is_archive?
    raise Errno::ENOENT, "archive missing" unless @model_file.exists_on_storage?

    listed = []
    truncated = false

    with_archive_path do |archive_path|
      Archive::Reader.open_filename(archive_path) do |reader|
        reader.each_entry do |entry|
          next unless entry.file?
          pathname = normalize_pathname(entry.pathname)
          next if pathname.blank?
          next if SiteSettings.ignored_file?(pathname)
          next if unsafe_pathname?(pathname)

          if listed.size >= MAX_LIST_ENTRIES
            truncated = true
            break
          end

          size = entry.size.to_i
          kind = ArchiveEntry.kind_for_pathname(pathname)
          status = if size > SiteSettings.max_file_extract_size
            "too_large"
          else
            "listed"
          end

          record = @model_file.archive_entries.find_or_initialize_by(pathname: pathname)
          record.size = size
          record.compressed_size = entry.respond_to?(:size_compressed) ? entry.size_compressed : nil
          record.kind = kind
          # Keep preview state if pathname unchanged and already processed
          if record.new_record? || record.status.in?(%w[listed preview_pending])
            record.status = status
            record.error_message = nil if status == "listed"
          elsif status == "too_large"
            record.status = "too_large"
          end
          record.save!
          listed << record
        end
      end
    end

    # Drop entries that vanished from the archive
    keep_paths = listed.map(&:pathname)
    @model_file.archive_entries.where.not(pathname: keep_paths).find_each(&:destroy)

    @model_file.update!(
      archive_entries_truncated: truncated,
      archive_entries_listed_count: listed.size
    )

    listed
  end

  def enqueue_previews!(entries = nil, images_only: false)
    entries ||= @model_file.archive_entries.previewable.where.not(status: %w[too_large skipped])
    images = entries.select(&:is_image?).sort_by { |e| e.size.to_i }
    meshes = if images_only
      []
    else
      entries.select(&:is_renderable?).sort_by { |e| e.size.to_i }
    end

    (images + meshes).each do |entry|
      next if entry.status == "too_large"
      next if entry.preview_ready? && entry.preview_exists?

      entry.update!(status: "preview_pending", error_message: nil)
      Scan::ModelFile::PreviewArchiveEntryJob.perform_later(entry.id)
    end
  end

  def extract_to_cache!(entry)
    raise EntryTooLarge if entry.size.to_i > SiteSettings.max_file_extract_size

    relative = cache_relative_path(entry)
    absolute = File.join(@library.path, relative)
    return relative if File.file?(absolute)

    FileUtils.mkdir_p(File.dirname(absolute))
    extract_entry_to!(entry.pathname, absolute)
    entry.update!(extracted_path: relative)
    relative
  end

  def extract_preview_image!(entry)
    raise EntryTooLarge if entry.size.to_i > SiteSettings.max_file_extract_size

    relative = preview_relative_path(entry)
    absolute = File.join(@library.path, relative)
    FileUtils.mkdir_p(File.dirname(absolute))

    Tempfile.create(["archive-entry", ".#{entry.extension.presence || "bin"}"]) do |tmp|
      tmp.binmode
      extract_entry_to!(entry.pathname, tmp.path)
      write_image_preview!(tmp.path, absolute)
    end

    entry.update!(preview_path: relative, status: "preview_ready", error_message: nil)
    relative
  end

  def extract_mesh_and_preview!(entry)
    cache_rel = extract_to_cache!(entry)
    cache_abs = File.join(@library.path, cache_rel)
    preview_rel = preview_relative_path(entry)
    preview_abs = File.join(@library.path, preview_rel)
    FileUtils.mkdir_p(File.dirname(preview_abs))

    stl_path = mesh_path_for_thumbnail(cache_abs, entry)
    begin
      if run_mesh_thumbnail_script(stl_path, preview_abs) || write_mesh_placeholder_preview!(entry, preview_abs)
        entry.update!(preview_path: preview_rel, status: "preview_ready", error_message: nil)
      else
        entry.update!(status: "preview_failed", error_message: "thumbnail generation failed")
      end
    ensure
      if stl_path != cache_abs && stl_path.present? && File.exist?(stl_path)
        FileUtils.rm_f(stl_path)
      end
    end
  end

  def extract_to_tempfile(entry)
    raise EntryTooLarge if entry.size.to_i > SiteSettings.max_file_extract_size

    tmp = Tempfile.new(["archive-dl", ".#{entry.extension.presence || "bin"}"])
    tmp.binmode
    extract_entry_to!(entry.pathname, tmp.path)
    tmp.rewind
    tmp
  end

  private

  def with_archive_path
    if @model_file.attachment.present?
      Shrine.with_file(@model_file.attachment.open) { |io| yield io.path }
    else
      path = File.join(@library.path, @model_file.path_within_library)
      yield path
    end
  end

  def extract_entry_to!(pathname, destination)
    found = false
    with_archive_path do |archive_path|
      Archive::Reader.open_filename(archive_path) do |reader|
        reader.each_entry do |entry|
          next unless entry.file?
          next unless normalize_pathname(entry.pathname) == pathname

          raise EntryTooLarge if entry.size.to_i > SiteSettings.max_file_extract_size
          raise UnsafePath if unsafe_pathname?(pathname)

          # libarchive extracts using entry.pathname under destination; use a staging dir
          # then move the target file into place.
          Dir.mktmpdir("archive-extract") do |staging|
            reader.extract(entry, Archive::EXTRACT_SECURE, destination: staging)
            source = locate_extracted_file(staging, entry.pathname)
            raise EntryNotFound if source.blank? || !File.file?(source)

            FileUtils.mkdir_p(File.dirname(destination))
            FileUtils.mv(source, destination)
          end
          found = true
          break
        end
      end
    end
    raise EntryNotFound, pathname unless found
  end

  def locate_extracted_file(staging, pathname)
    candidates = [
      File.join(staging, pathname),
      File.join(staging, pathname.delete_prefix("/")),
      File.join(staging, File.basename(pathname))
    ]
    candidates.find { |p| File.file?(p) } ||
      Dir.glob(File.join(staging, "**", File.basename(pathname))).find { |p| File.file?(p) }
  end

  def normalize_pathname(pathname)
    pathname.to_s.delete_prefix("./").tr("\\", "/")
  end

  def unsafe_pathname?(pathname)
    parts = pathname.split("/")
    parts.any? { |p| p == ".." || p == "." } || pathname.start_with?("/")
  end

  def cache_relative_path(entry)
    File.join(
      @model.path,
      ".manyfold",
      "archive_cache",
      @model_file.public_id,
      entry.public_id,
      safe_basename(entry.pathname)
    )
  end

  def preview_relative_path(entry)
    File.join(
      @model.path,
      ".manyfold",
      "derivatives",
      "archives",
      @model_file.public_id,
      entry.public_id,
      "preview.png"
    )
  end

  def safe_basename(pathname)
    name = File.basename(pathname.to_s)
    name = "file" if name.blank? || name == "." || name == ".."
    name.gsub(/[^\w.\-]+/, "_")
  end

  def write_image_preview!(source_path, dest_path)
    ImageProcessing::MiniMagick
      .source(source_path)
      .resize_to_limit(640, 480)
      .convert("png")
      .call(destination: dest_path)
  end

  def write_mesh_placeholder_preview!(entry, dest_path)
    # Prefer ImageMagick; fall back to a tiny generated PNG (runtime may lack `convert`).
    label = entry.extension.upcase.presence || "MESH"
    size_label = entry.size.to_i.positive? ? ActiveSupport::NumberHelper.number_to_human_size(entry.size) : "?"
    name = entry.basename.to_s[0, 40]
    if write_mesh_placeholder_via_imagemagick!(label, name, size_label, dest_path)
      return true
    end
    write_minimal_png!(dest_path, 640, 480, [28, 24, 20], [232, 168, 90])
  end

  def write_mesh_placeholder_via_imagemagick!(label, name, size_label, dest_path)
    MiniMagick::Tool::Convert.new do |convert|
      convert.size "640x480"
      convert << "xc:#1c1814"
      convert.fill "#E8A85A"
      convert.gravity "center"
      convert.pointsize 48
      convert.draw "text 0,-40 '#{escape_draw(label)}'"
      convert.fill "#c4b8a8"
      convert.pointsize 22
      convert.draw "text 0,20 '#{escape_draw(name)}'"
      convert.pointsize 18
      convert.draw "text 0,60 '#{escape_draw(size_label)}'"
      convert << dest_path
    end
    File.file?(dest_path)
  rescue
    false
  end

  def write_minimal_png!(path, width, height, bg_rgb, fg_rgb)
    require "zlib"
    raw = "".b
    height.times do |y|
      raw << "\x00".b
      width.times do
        color = (y > height / 2 - 20 && y < height / 2 + 20) ? fg_rgb : bg_rgb
        raw << color.pack("C*") << "\xFF".b
      end
    end
    chunk = ->(tag, data) {
      tag_b = tag.b
      data_b = data.b
      [data_b.bytesize].pack("N") + tag_b + data_b + [Zlib.crc32(tag_b + data_b)].pack("N")
    }
    ihdr = [width, height, 8, 6, 0, 0, 0].pack("NNCCCCC")
    png = "\x89PNG\r\n\x1a\n".b
    png << chunk.call("IHDR", ihdr)
    png << chunk.call("IDAT", Zlib::Deflate.deflate(raw))
    png << chunk.call("IEND", "".b)
    FileUtils.mkdir_p(File.dirname(path))
    File.binwrite(path, png)
    File.file?(path) && File.size(path).positive?
  rescue
    false
  end

  def escape_draw(text)
    text.to_s.gsub("\\", "\\\\").gsub("'", "\\'")
  end

  def run_mesh_thumbnail_script(mesh_path, preview_path)
    script = Rails.root.join("scripts/mesh_thumbnail.mjs")
    return false unless script.file?
    return false unless system("command", "-v", "node", out: File::NULL, err: File::NULL)

    require "open3"
    stdout, stderr, status = Open3.capture3("node", script.to_s, mesh_path, preview_path)
    ok = status.success? && File.file?(preview_path) && File.size(preview_path).positive?
    unless ok
      Rails.logger.warn(
        "[ArchiveEntryService] mesh_thumbnail failed status=#{status.exitstatus} " \
        "mesh=#{mesh_path} out=#{stdout.to_s.truncate(200)} err=#{stderr.to_s.truncate(400)}"
      )
    end
    ok
  rescue => e
    Rails.logger.warn("[ArchiveEntryService] mesh_thumbnail error: #{e.class}: #{e.message}")
    false
  end

  # STL passes through; other mesh formats are converted via Assimp → binary STL tempfile.
  def mesh_path_for_thumbnail(cache_abs, entry)
    return cache_abs if entry.extension == "stl"
    return cache_abs unless defined?(Assimp)

    convert_mesh_to_stl_tempfile!(cache_abs) || cache_abs
  end

  def convert_mesh_to_stl_tempfile!(source_path)
    scene = Assimp.import_file(source_path)
    scene.apply_post_processing(Assimp::PostProcessSteps[
      :JoinIdenticalVertices,
      :Triangulate
    ])

    path = File.join(Dir.tmpdir, "archive-mesh-#{SecureRandom.hex(8)}.stl")
    File.open(path, "wb") { |io| write_binary_stl!(scene, io) }
    path
  rescue => e
    Rails.logger.warn("[ArchiveEntryService] Assimp→STL failed: #{e.class}: #{e.message}")
    nil
  end

  def write_binary_stl!(scene, io)
    triangles = []
    scene.meshes.each do |mesh|
      verts = mesh.vertices
      next if verts.blank?

      mesh.faces.each do |face|
        idxs = face.indices
        next if idxs.nil? || idxs.length < 3

        # Fan-triangulate any leftover polygons
        (1...(idxs.length - 1)).each do |i|
          a = verts[idxs[0]]
          b = verts[idxs[i]]
          c = verts[idxs[i + 1]]
          next if a.nil? || b.nil? || c.nil?

          nx = ((b.y - a.y) * (c.z - a.z)) - ((b.z - a.z) * (c.y - a.y))
          ny = ((b.z - a.z) * (c.x - a.x)) - ((b.x - a.x) * (c.z - a.z))
          nz = ((b.x - a.x) * (c.y - a.y)) - ((b.y - a.y) * (c.x - a.x))
          len = Math.sqrt(nx * nx + ny * ny + nz * nz)
          if len > 1e-12
            nx /= len
            ny /= len
            nz /= len
          else
            nx = 0.0
            ny = 0.0
            nz = 0.0
          end
          triangles << [nx, ny, nz, a.x, a.y, a.z, b.x, b.y, b.z, c.x, c.y, c.z]
        end
      end
    end

    raise "no triangles from Assimp scene" if triangles.empty?

    header = "manyfold archive mesh preview".ljust(80, "\0").b
    io.write(header)
    io.write([triangles.length].pack("V"))
    triangles.each do |t|
      io.write(t.pack("e12"))
      io.write([0].pack("v")) # attribute byte count
    end
  end
end
