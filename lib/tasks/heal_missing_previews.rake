# frozen_string_literal: true

namespace :manyfold do
  desc "Re-pick or clear preview_file when the image is missing on disk. " \
       "LIMIT=500 LIBRARY_ID= optional."
  task heal_missing_previews: :environment do
    limit = Integer(ENV.fetch("LIMIT", Scan::Model::HealMissingPreviewsJob::DEFAULT_LIMIT))
    library_id = ENV["LIBRARY_ID"].presence&.to_i
    count = Scan::Model::HealMissingPreviewsJob.perform_now(limit: limit, library_id: library_id)
    puts "Healed #{count} missing preview(s) (limit=#{limit})"
  end
end
