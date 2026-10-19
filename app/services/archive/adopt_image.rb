# frozen_string_literal: true

module Archive
  # Adopt an image found inside an archive onto the model. Every image entry is
  # adopted (INIT-001 owner decision), once: a file with the same SHA-512 digest
  # is reused instead of copied. ModelFile#calculate_digest is SHA-512, so this
  # matches files the scanner already hashed. The entry is linked to the file it
  # resolved to so deleting that file can also remove it from the archive.
  # If the model has no on-disk image preview, the file becomes preview_file.
  class AdoptImage
    MAX_NAME_ATTEMPTS = 5

    def self.call(...)
      new(...).call
    end

    # SHA-512 of a file, matching ModelFile#calculate_digest.
    def self.hexdigest(path)
      digest = Digest::SHA512.new
      File.open(path, "rb") do |io|
        while (chunk = io.read(1.megabyte))
          digest.update(chunk)
        end
      end
      digest.hexdigest
    end

    # Fallback when adoption could not place a loose copy: the archive entry
    # itself becomes the preview (INIT-026). See Archive::EntryPreview.
    def self.assign_preview!(model:, entry:)
      Archive::EntryPreview.new(model, entry).assign_preview!
    end

    def initialize(model:, source_path:, filename:, entry: nil)
      @model = model
      @source_path = source_path
      @filename = filename
      @entry = entry
    end

    def call
      return unless File.file?(@source_path)
      return if @entry&.status == "dismissed"
      # SVG can carry active content; the rasterized preview is enough for it.
      return if File.extname(@filename.to_s).casecmp?(".svg")

      digest = self.class.hexdigest(@source_path)
      return if digest.blank?

      file = adopt!(digest)
      @entry&.update!(adopted_model_file: file)
      assign_preview!(file)
      file
    end

    private

    # Match, name, write and create under a per-model lock so concurrent preview
    # jobs cannot pick the same name or both miss a digest match (INIT-001/SPEC-002).
    def adopt!(digest)
      @model.with_lock { matching_image(digest) || create_image!(digest) }
    end

    def matching_image(digest)
      known = @model.model_files.where(digest: digest).detect { |file| file.is_image? && file.exists_on_storage? }
      return known if known

      @model.model_files.where(digest: [nil, ""]).find do |file|
        next unless file.is_image? && file.exists_on_storage?

        hashed = file.calculate_digest
        next if hashed.blank?

        file.update_column(:digest, hashed) if file.digest != hashed # rubocop:disable Rails/SkipsModelValidations -- cache digest only
        hashed == digest
      end
    end

    def create_image!(digest)
      filename = write_unique!
      begin
        @model.model_files.create!(filename: filename, digest: digest)
      rescue
        remove_written(filename)
        raise
      end
    end

    # Never follows or overwrites an existing path (including a dangling
    # symlink): local files are opened O_EXCL|O_NOFOLLOW, then the name is
    # retried. Other storages upload through the library's own adapter.
    def write_unique!
      MAX_NAME_ATTEMPTS.times do
        filename = unique_filename
        (library.storage_service == "filesystem") ? write_local!(filename) : write_storage!(filename)
        return filename
      rescue Errno::EEXIST, Errno::ELOOP
        next
      end
      raise Errno::EEXIST, "no free filename for #{@filename}"
    end

    def write_local!(filename)
      dest = File.join(local_model_dir, filename)
      flags = File::WRONLY | File::CREAT | File::EXCL | File::NOFOLLOW
      File.open(dest, flags, 0o644) do |out|
        # Past this point the file is ours; a failed copy must not leave a partial.
        File.open(@source_path, "rb") { |src| IO.copy_stream(src, out) }
      rescue
        FileUtils.rm_f(dest)
        raise
      end
    end

    def write_storage!(filename)
      File.open(@source_path, "rb") { |io| library.storage.upload(io, storage_key(filename)) }
    end

    def remove_written(filename)
      library.storage.delete(storage_key(filename))
    rescue Shrine::FileNotFound, Errno::ENOENT
      nil
    end

    def unique_filename
      base = File.basename(@filename.to_s)
      base = "image.png" if base.blank? || base == "." || base == ".."
      ext = File.extname(base)
      stem = File.basename(base, ext)
      candidate = base
      n = 1
      while name_taken?(candidate)
        candidate = "#{stem}-#{n}#{ext}"
        n += 1
      end
      candidate
    end

    def name_taken?(filename)
      return true if @model.model_files.exists?(filename: filename)
      return true if library.has_file?(storage_key(filename))

      # File.exist? is false for a dangling symlink, which a write would follow.
      library.storage_service == "filesystem" && File.symlink?(File.join(local_model_dir, filename))
    end

    def library
      @model.library
    end

    def storage_key(filename)
      File.join(*[@model.path, filename].compact_blank)
    end

    # Real, existing model directory, verified to sit inside the real library
    # root so a symlinked folder cannot redirect the write.
    def local_model_dir
      LibraryPathJail.assert_within!(library.path, @model.path) if @model.path.present?
      root = File.realpath(library.path)
      dir = File.realpath(File.join(library.path, @model.path.to_s))
      raise LibraryPathJail::EscapeError, "model folder escapes library" unless LibraryPathJail.contained?(root, dir)

      dir
    end

    def assign_preview!(file)
      return unless file&.is_image?

      current = @model.preview_file
      return if current&.is_image? && current.exists_on_storage?

      @model.update!(preview_file: file) unless @model.preview_file_id == file.id
    end
  end
end
