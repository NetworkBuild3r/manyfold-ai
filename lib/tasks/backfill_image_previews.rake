# frozen_string_literal: true

namespace :manyfold do
  desc "Set preview_file to an image for models that have image files but a " \
       "missing or non-image preview. DRY_RUN=1 to report only."
  task backfill_image_previews: :environment do
    dry_run = ENV["DRY_RUN"].present?
    exts = SupportedMimeTypes.image_extensions.map(&:downcase).uniq
    abort "No image extensions configured" if exts.empty?

    image_filename_sql = exts.map { |ext|
      "LOWER(model_files.filename) LIKE #{ActiveRecord::Base.connection.quote("%.#{ext}")}"
    }.join(" OR ")

    image_files = ModelFile.without_special.where(image_filename_sql)
    model_ids = image_files.distinct.pluck(:model_id)
    updated = 0
    skipped = 0

    Model.where(id: model_ids).find_each do |model|
      current = model.preview_file
      if current&.is_image?
        skipped += 1
        next
      end

      best = model.model_files.min_by { |f|
        if f.is_image?
          0
        elsif f.is_renderable?
          1
        else
          100
        end
      }
      next unless best&.is_image?

      if dry_run
        puts "would update model=#{model.id} #{model.name.inspect} " \
             "preview=#{current&.filename.inspect} -> #{best.filename.inspect}"
      else
        model.update!(preview_file: best)
      end
      updated += 1
    end

    verb = dry_run ? "Would update" : "Updated"
    puts "#{verb} #{updated} model(s); skipped #{skipped} already image-previewed " \
         "(candidates=#{model_ids.size})"
  end
end
