# frozen_string_literal: true

module Archive
  # INIT-026/SPEC-004 — rewrite an archive without one member (copy-then-replace).
  module DeleteEntry
    extend ActiveSupport::Concern
    include EntrySupport

    REWRITEABLE_EXTENSIONS = %w[zip].freeze
    COPY_CHUNK = 1.megabyte

    def delete_member!(entry)
      raise ArchiveEntryService::EntryNotFound unless entry.model_file_id == @model_file.id

      pathname = normalize_pathname(entry.pathname)
      raise ArchiveEntryService::UnsafePath if unsafe_pathname?(pathname)
      raise ArchiveEntryService::UnsupportedFormat, @model_file.extension unless rewriteable_archive?

      archive_path = jailed_archive_absolute_path!
      rewrite_archive_without!(archive_path, pathname)
      remove_entry_artifacts!(entry)
      entry.destroy!
      recount_listed_entries!
      Rails.logger.info { "INIT-026/SPEC-004 deleted archive entry=#{entry.public_id}" }
      entry
    end

    private

    def rewriteable_archive?
      REWRITEABLE_EXTENSIONS.include?(@model_file.extension.to_s.downcase)
    end

    def jailed_archive_absolute_path!
      relative = @model_file.path_within_library
      absolute = File.expand_path(File.join(@library.path, relative))
      raise ArchiveEntryService::UnsafePath unless LibraryPathJail.contained?(@library.path, absolute)
      raise Errno::ENOENT, "archive missing" unless File.file?(absolute)

      absolute
    rescue LibraryPathJail::EscapeError
      raise ArchiveEntryService::UnsafePath
    end

    def rewrite_archive_without!(archive_path, skip_pathname)
      dir = File.dirname(archive_path)
      raise ArchiveEntryService::UnsafePath unless LibraryPathJail.contained?(@library.path, dir)

      tmp_path = File.join(dir, ".#{File.basename(archive_path)}.#{Process.pid}.#{SecureRandom.hex(8)}.rewrite.tmp")
      raise ArchiveEntryService::UnsafePath unless LibraryPathJail.contained?(@library.path, tmp_path)

      begin
        copy_archive_omitting(archive_path, tmp_path, skip_pathname)
        File.open(tmp_path, "rb") { |f| f.fsync }
        File.rename(tmp_path, archive_path)
      rescue
        FileUtils.rm_f(tmp_path)
        raise
      end
    end

    def copy_archive_omitting(source, dest, skip_pathname)
      Archive::Reader.open_filename(source) do |reader|
        Archive.write_open_filename(dest, Archive::COMPRESSION_NONE, Archive::FORMAT_ZIP) do |writer|
          reader.each_entry do |in_entry|
            next unless in_entry.file?

            member = normalize_pathname(in_entry.pathname)
            next if member == skip_pathname
            next if member.blank? || unsafe_pathname?(member)

            writer.new_entry do |out_entry|
              out_entry.pathname = member
              out_entry.size = in_entry.size.to_i
              out_entry.filetype = Archive::Entry::FILE
              out_entry.mode = Archive::Entry::S_IFREG | 0o640
              out_entry.mtime = in_entry.mtime if in_entry.respond_to?(:mtime)
              writer.write_header out_entry
              reader.read_data(COPY_CHUNK) do |chunk|
                writer.write_data(chunk)
              end
            end
          end
        end
      end
    end

    def remove_entry_artifacts!(entry)
      [entry.absolute_preview_path, entry.absolute_extracted_path].compact.each do |path|
        next unless LibraryPathJail.contained?(@library.path, path)

        FileUtils.rm_f(path) if File.file?(path)
      end
    end

    def recount_listed_entries!
      @model_file.update!(archive_entries_listed_count: @model_file.archive_entries.count)
    end
  end
end
