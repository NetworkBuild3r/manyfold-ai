# frozen_string_literal: true

module Archive
  module ExtractEntry
    extend ActiveSupport::Concern
    include EntrySupport

    def extract_entries_to!(pathname_to_destination)
      raise ArgumentError, "pathname map required" if pathname_to_destination.blank?

      wanted = pathname_to_destination.transform_keys { |p| normalize_pathname(p) }
      found = {}

      with_archive_path do |archive_path|
        Archive::Reader.open_filename(archive_path) do |reader|
          reader.each_entry do |entry|
            next unless entry.file?

            pathname = normalize_pathname(entry.pathname)
            destination = wanted[pathname]
            next unless destination
            next if found.key?(pathname)

            raise ArchiveEntryService::EntryTooLarge if entry.size.to_i > SiteSettings.max_file_extract_size
            raise ArchiveEntryService::UnsafePath if unsafe_pathname?(pathname)

            Dir.mktmpdir("archive-extract") do |staging|
              reader.extract(entry, Archive::EXTRACT_SECURE, destination: staging)
              source = locate_extracted_file(staging, entry.pathname)
              raise ArchiveEntryService::EntryNotFound if source.blank? || !File.file?(source)

              FileUtils.mkdir_p(File.dirname(destination))
              FileUtils.mv(source, destination)
            end
            found[pathname] = destination
            break if found.size >= wanted.size
          end
        end
      end

      missing = wanted.keys - found.keys
      raise ArchiveEntryService::EntryNotFound, missing.join(", ") if missing.any?

      found
    end

    def extract_to_cache!(entry)
      raise ArchiveEntryService::EntryTooLarge if entry.size.to_i > SiteSettings.max_file_extract_size

      relative = cache_relative_path(entry)
      absolute = File.join(@library.path, relative)
      return relative if File.file?(absolute)

      FileUtils.mkdir_p(File.dirname(absolute))
      extract_entries_to!(entry.pathname => absolute)
      entry.update!(extracted_path: relative)
      relative
    end

    def extract_to_tempfile(entry)
      raise ArchiveEntryService::EntryTooLarge if entry.size.to_i > SiteSettings.max_file_extract_size

      tmp = Tempfile.new(["archive-dl", ".#{entry.extension.presence || "bin"}"])
      tmp.binmode
      extract_entries_to!(entry.pathname => tmp.path)
      tmp.rewind
      tmp
    end
  end
end
