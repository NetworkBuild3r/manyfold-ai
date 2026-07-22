# frozen_string_literal: true

namespace :manyfold do
  desc "Assign or repair preview_file from on-disk folder images. " \
       "Fixes broken previews and unset previews when an image exists. " \
       "LIMIT=500 (0 = all), LIBRARY_ID= optional."
  task heal_missing_previews: :environment do
    raw = ENV.fetch("LIMIT", Scan::Model::HealMissingPreviewsJob::DEFAULT_LIMIT.to_s)
    limit = Integer(raw)
    library_id = ENV["LIBRARY_ID"].presence&.to_i
    count = Scan::Model::HealMissingPreviewsJob.perform_now(limit: limit, library_id: library_id)
    puts "Healed #{count} preview(s) (limit=#{limit == 0 ? "all" : limit})"
  end
end
