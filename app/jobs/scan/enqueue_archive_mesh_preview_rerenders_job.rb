# frozen_string_literal: true

# Re-queue archive mesh preview jobs so placeholders can be replaced with
# real software-rendered PNGs (Assimp → STL → mesh_thumbnail.mjs).
class Scan::EnqueueArchiveMeshPreviewRerendersJob < ApplicationJob
  queue_as :low
  unique :until_executed, lock_ttl: 6.hours

  DEFAULT_BATCH = 100
  DEFAULT_STAGGER = 0.5

  def perform(limit: 0, batch_size: DEFAULT_BATCH, stagger: DEFAULT_STAGGER, cursor: 0)
    max = (limit.to_i <= 0) ? Float::INFINITY : limit.to_i
    batch = [batch_size.to_i, 1].max
    stagger_s = stagger.to_f

    scope = ArchiveEntry.meshes
      .where(status: %w[preview_ready preview_failed preview_pending])
      .where("archive_entries.id > ?", cursor.to_i)
      .order(:id)
      .limit([batch, max].min)

    entries = scope.to_a
    return 0 if entries.empty?

    queued = 0
    entries.each_with_index do |entry, index|
      break if queued >= max

      wait = (index * stagger_s).seconds
      entry.update_columns(status: "preview_pending", error_message: nil) # rubocop:disable Rails/SkipsModelValidations
      Scan::ModelFile::PreviewArchiveEntryJob.set(wait: wait).perform_later(entry.id)
      queued += 1
    end

    last_id = entries.last.id
    remaining_cap = max - queued

    Rails.logger.info(
      "[scan] EnqueueArchiveMeshPreviewRerendersJob queued=#{queued} last_id=#{last_id}"
    )

    if remaining_cap > 0 && entries.size >= batch
      self.class.perform_later(
        limit: (limit.to_i <= 0) ? 0 : remaining_cap,
        batch_size: batch,
        stagger: stagger_s,
        cursor: last_id
      )
    end

    queued
  end
end
