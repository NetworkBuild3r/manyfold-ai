# frozen_string_literal: true

namespace :manyfold do
  desc "Enqueue AnalyseModelFileJob for files with digest IS NULL (Phase B). " \
       "LIMIT=500 LIBRARY_ID= optional."
  task analyse_undigested: :environment do
    limit = Integer(ENV.fetch("LIMIT", Scan::AnalyseUndigestedJob::DEFAULT_LIMIT))
    library_id = ENV["LIBRARY_ID"].presence&.to_i
    count = Scan::AnalyseUndigestedJob.perform_now(limit: limit, library_id: library_id)
    puts "Enqueued analysis for #{count} undigested file(s) (limit=#{limit})"
  end
end
