# frozen_string_literal: true

namespace :manyfold do
  desc "Enqueue background archive listing for the library. " \
       "LIMIT=0 (all), BATCH=100, IMAGES_ONLY=1 (default), FORCE=0, MODEL_ID=public_id"
  task scan_archives: :environment do
    images_only = ActiveModel::Type::Boolean.new.cast(ENV.fetch("IMAGES_ONLY", "1"))

    if ENV["MODEL_ID"].present?
      model = Model.find_by!(public_id: ENV["MODEL_ID"])
      count = 0
      model.model_files.find_each do |file|
        next unless file.is_archive?
        file.scan_archive_later(preview_images_only: images_only)
        count += 1
        puts "queued ListArchiveJob for model=#{model.public_id} file=#{file.filename}"
      end
      puts "queued #{count} archive scan(s) for model=#{model.public_id}"
    else
      limit = Integer(ENV.fetch("LIMIT", "0"))
      batch = Integer(ENV.fetch("BATCH", Scan::EnqueueArchiveScansJob::DEFAULT_BATCH.to_s))
      force = ActiveModel::Type::Boolean.new.cast(ENV.fetch("FORCE", "0"))
      Scan::EnqueueArchiveScansJob.perform_later(
        limit: limit,
        batch_size: batch,
        preview_images_only: images_only,
        force: force
      )
      puts "enqueued EnqueueArchiveScansJob limit=#{limit == 0 ? "all" : limit} " \
           "batch=#{batch} images_only=#{images_only} force=#{force}"
    end
  end
end
