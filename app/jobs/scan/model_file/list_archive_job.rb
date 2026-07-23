# frozen_string_literal: true

class Scan::ModelFile::ListArchiveJob < ApplicationJob
  queue_as :scan
  unique :until_executed, lock_ttl: 1.hour

  def perform(file_id, preview_images_only: false)
    file = ModelFile.find(file_id)
    return unless file.is_archive?
    unless file.exists_on_storage?
      Problems::MissingFile.detect(file)
      raise Errno::ENOENT, "archive missing for ModelFile##{file_id}"
    end

    file.attach_existing_file! if file.attachment.blank?

    service = ArchiveEntryService.new(file)
    service.list!
    service.enqueue_previews!(images_only: preview_images_only)
  rescue Errno::ENOENT, Shrine::FileNotFound => e
    Rails.logger.error("[ListArchiveJob] archive missing for ModelFile##{file_id}: #{e.message}")
    file = ModelFile.find_by(id: file_id)
    Problems::MissingFile.detect(file) if file
    raise
  end
end
