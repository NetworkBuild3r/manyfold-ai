# frozen_string_literal: true

module Archive
  module ListEntries
    extend ActiveSupport::Concern
    include EntrySupport

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

            if listed.size >= ArchiveEntryService::MAX_LIST_ENTRIES
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

      keep_paths = listed.map(&:pathname)
      @model_file.archive_entries.where.not(pathname: keep_paths).find_each(&:destroy)

      @model_file.update!(
        archive_entries_truncated: truncated,
        archive_entries_listed_count: listed.size
      )

      listed
    end
  end
end
