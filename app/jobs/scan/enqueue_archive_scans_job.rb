# frozen_string_literal: true

# Walk unlisted archive ModelFiles and enqueue ListArchiveJob in paced batches
# so a full-library pass does not stampede NFS / Sidekiq.
class Scan::EnqueueArchiveScansJob < ApplicationJob
  queue_as :low
  unique :until_executed, lock_ttl: 6.hours

  DEFAULT_BATCH = 100
  DEFAULT_STAGGER = 0.5 # seconds between each ListArchiveJob in a batch

  def perform(limit: 0, batch_size: DEFAULT_BATCH, stagger: DEFAULT_STAGGER,
    preview_images_only: true, force: false, cursor: 0)
    max = (limit.to_i <= 0) ? Float::INFINITY : limit.to_i
    batch = [batch_size.to_i, 1].max
    stagger_s = stagger.to_f

    scope = archive_file_scope(force: force).where("model_files.id > ?", cursor.to_i)
      .order(:id)
      .limit([batch, max].min)

    files = scope.to_a
    return 0 if files.empty?

    queued = 0
    files.each_with_index do |file, index|
      break if queued >= max

      unless file.exists_on_storage?
        Rails.logger.info("[scan] EnqueueArchiveScansJob skip missing file=#{file.id}")
        next
      end

      wait = (index * stagger_s).seconds
      Scan::ModelFile::ListArchiveJob.set(wait: wait)
        .perform_later(file.id, preview_images_only: preview_images_only)
      queued += 1
    end

    last_id = files.last.id
    remaining_cap = max - queued

    Rails.logger.info(
      "[scan] EnqueueArchiveScansJob queued=#{queued} last_id=#{last_id} " \
      "images_only=#{preview_images_only} force=#{force}"
    )

    if remaining_cap > 0 && files.size >= batch
      self.class.perform_later(
        limit: (limit.to_i <= 0) ? 0 : remaining_cap,
        batch_size: batch,
        stagger: stagger_s,
        preview_images_only: preview_images_only,
        force: force,
        cursor: last_id
      )
    end

    queued
  end

  private

  def archive_file_scope(force:)
    exts = SupportedMimeTypes.archive_extensions.map(&:downcase).uniq
    like = exts.map { |e|
      "LOWER(model_files.filename) LIKE #{ActiveRecord::Base.connection.quote("%.#{e}")}"
    }.join(" OR ")

    scope = ModelFile.without_special.where(like)
    scope = scope.where(archive_entries_listed_count: 0) unless force
    scope
  end
end
