# frozen_string_literal: true

namespace :manyfold do
  desc "Set preview_file to an on-disk folder image when preview is missing or " \
       "non-image. Prefers preview/cover/thumb filenames. DRY_RUN=1 to report only. " \
       "Delegates to HealMissingPreviewsJob (LIMIT=0) unless DRY_RUN."
  task backfill_image_previews: :environment do
    dry_run = ENV["DRY_RUN"].present?

    if dry_run
      would = 0
      Model.includes(:preview_file, :model_files, :library).find_each do |model|
        current = model.preview_file
        next if current&.is_image? && current.exists_on_storage?

        pick = PreviewFilePicker.new(model).call(require_on_disk: true)
        next if pick.nil?
        next if current&.id == pick.id

        puts "would update model=#{model.id} #{model.name.inspect} " \
             "preview=#{current&.filename.inspect} -> #{pick.filename.inspect}"
        would += 1
      end
      puts "Would update #{would} model(s)"
    else
      count = Scan::Model::HealMissingPreviewsJob.perform_now(limit: 0)
      puts "Updated #{count} model(s) via HealMissingPreviewsJob"
    end
  end
end
