# frozen_string_literal: true

namespace :manyfold do
  desc "Apply spark-curate merges-pending.jsonl via Model#merge!. " \
       "DRY_RUN=1 to preview. LIMIT=500 LIBRARY_ID= optional."
  task apply_spark_merges: :environment do
    dry_run = ENV.fetch("DRY_RUN", "0").match?(/\A(1|true|yes)\z/i)
    limit = Integer(ENV.fetch("LIMIT", "500"))
    library_id = ENV["LIBRARY_ID"].presence&.to_i
    result = Scan::ApplySparkMergePlanJob.perform_now(
      library_id: library_id,
      dry_run: dry_run,
      limit: limit
    )
    puts "ApplySparkMergePlanJob #{result.inspect}"
  end
end
