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

  desc "Drop leftover same-model extra copies and retract their duplicate Problems"
  task sweep_same_model_duplicate_extras: :environment do
    result = Problems::SweepSameModelExtras.call
    puts "collapsed=#{result.collapsed} retracted=#{result.retracted}"
  end
end
