# frozen_string_literal: true

module Archive
  # Shared helpers for archive entry services.
  module EntrySupport
    private

    def with_archive_path
      if @model_file.attachment.present?
        Shrine.with_file(@model_file.attachment.open) { |io| yield io.path }
      else
        path = File.join(@library.path, @model_file.path_within_library)
        yield path
      end
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
  end
end
