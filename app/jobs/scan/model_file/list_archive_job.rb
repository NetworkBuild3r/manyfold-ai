# frozen_string_literal: true

class Scan::ModelFile::ListArchiveJob < ApplicationJob
  queue_as :scan
  unique :until_executed, lock_ttl: 1.hour

  # INIT-026/SPEC-003: skip an already-listed archive unless force: true (D-1).
  def perform(file_id, preview_images_only: false, force: false)
    file = ModelFile.find(file_id)
    return unless file.is_archive?
    unless file.exists_on_storage?
      Problems::MissingFile.detect(file)
      raise Errno::ENOENT, "archive missing for ModelFile##{file_id}"
    end

    listed_count = file.archive_entries_listed_count.to_i
    if listed_count.positive? && !force
      Rails.logger.info("[ListArchiveJob] skip listed file=#{file_id} count=#{listed_count}")
      return
    end

    file.attach_existing_file! if file.attachment.blank?

    service = ArchiveEntryService.new(file)
    service.list!
    queued = service.enqueue_previews!(images_only: preview_images_only, force: force)
    Rails.logger.info(
      "[ListArchiveJob] listed file=#{file_id} queued_images=#{queued} " \
      "images_only=#{preview_images_only} force=#{force}"
    )
  rescue Errno::ENOENT, Shrine::FileNotFound => e
    Rails.logger.error("[ListArchiveJob] archive missing for ModelFile##{file_id}: #{e.message}")
    file = ModelFile.find_by(id: file_id)
    Problems::MissingFile.detect(file) if file
    raise
  end
end
