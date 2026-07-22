# frozen_string_literal: true

class Scan::ModelFile::ListArchiveJob < ApplicationJob
  queue_as :scan
  unique :until_executed, lock_ttl: 1.hour

  def perform(file_id)
    file = ModelFile.find(file_id)
    return unless file.is_archive?
    return unless file.exists_on_storage?

    file.attach_existing_file! if file.attachment.blank?

    service = ArchiveEntryService.new(file)
    service.list!
    service.enqueue_previews!
  rescue Errno::ENOENT, Shrine::FileNotFound => e
    Rails.logger.warn("[ListArchiveJob] archive missing for ModelFile##{file_id}: #{e.message}")
  end
end
