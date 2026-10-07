# frozen_string_literal: true

# Remove dismissed image entries from their archive after the adopted image was
# deleted from the model (INIT-001/SPEC-004). Processes every dismissed entry
# of the archive, so a burst of deletions collapses into one rewrite; the row
# lock serializes rewrites of the same archive.
class Scan::ModelFile::RemoveArchiveEntriesJob < ApplicationJob
  queue_as :performance
  unique :until_executing, lock_ttl: 1.hour

  UNWRITABLE_MESSAGE = "archive format not writable; image hidden but kept in archive"

  def perform(archive_file_id)
    file = ModelFile.find_by(id: archive_file_id)
    return unless file&.is_archive?

    file.with_lock do
      entries = file.archive_entries.where(status: "dismissed").to_a
      next if entries.empty?

      result = Archive::RemoveEntries.call(model_file: file, pathnames: entries.map(&:pathname))
      case result.status
      when :removed
        cleanup!(file, entries.select { |e| result.removed.include?(e.pathname) })
      when :unwritable
        entries.each { |e| e.update!(error_message: UNWRITABLE_MESSAGE) }
      end
    end
  end

  private

  def cleanup!(file, entries)
    entries.each do |entry|
      derivative_dirs(file, entry).each { |dir| FileUtils.rm_rf(dir) }
      entry.destroy!
    end
    file.attachment_attacher.refresh_metadata!
    file.digest = file.calculate_digest
    file.archive_entries_listed_count = file.archive_entries.count
    file.save!
  end

  def derivative_dirs(file, entry)
    base = File.join(file.model.library.path, file.model.path, ".manyfold")
    [
      File.join(base, "derivatives", "archives", file.public_id, entry.public_id),
      File.join(base, "archive_cache", file.public_id, entry.public_id)
    ]
  end
end
