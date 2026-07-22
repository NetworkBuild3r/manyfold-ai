# frozen_string_literal: true

class Scan::ModelFile::PreviewArchiveEntryJob < ApplicationJob
  queue_as :performance
  unique :until_executed, lock_ttl: 1.hour
  sidekiq_options retry: 2

  def perform(entry_id)
    entry = ArchiveEntry.find(entry_id)
    file = entry.model_file
    return unless file.is_archive?
    return unless file.exists_on_storage?
    return if entry.status == "too_large"

    service = ArchiveEntryService.new(file)

    case entry.kind
    when "image"
      service.extract_preview_image!(entry)
    when "mesh"
      service.extract_mesh_and_preview!(entry)
    else
      entry.update!(status: "skipped")
    end
  rescue ArchiveEntryService::EntryTooLarge
    entry&.update!(status: "too_large", error_message: "entry exceeds max extract size")
  rescue ArchiveEntryService::EntryNotFound => e
    entry&.update!(status: "preview_failed", error_message: e.message)
  rescue => e
    entry&.update!(status: "preview_failed", error_message: e.message.to_s.truncate(500))
    raise
  end
end
