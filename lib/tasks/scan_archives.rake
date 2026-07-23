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

  desc "Re-render archive mesh entry previews (replace placeholders / listed-only). " \
       "LIMIT=0 (all), BATCH=100, STAGGER=0.5, CURSOR=0. For new archives use IMAGES_ONLY=0 rake manyfold:scan_archives"
  task rerender_archive_mesh_previews: :environment do
    limit = Integer(ENV.fetch("LIMIT", "0"))
    batch = Integer(ENV.fetch("BATCH", Scan::EnqueueArchiveMeshPreviewRerendersJob::DEFAULT_BATCH.to_s))
    stagger = Float(ENV.fetch("STAGGER", Scan::EnqueueArchiveMeshPreviewRerendersJob::DEFAULT_STAGGER.to_s))
    cursor = Integer(ENV.fetch("CURSOR", "0"))
    Scan::EnqueueArchiveMeshPreviewRerendersJob.perform_later(
      limit: limit,
      batch_size: batch,
      stagger: stagger,
      cursor: cursor
    )
    puts "enqueued EnqueueArchiveMeshPreviewRerendersJob limit=#{limit == 0 ? "all" : limit} " \
         "batch=#{batch} stagger=#{stagger} cursor=#{cursor}"
  end
end
