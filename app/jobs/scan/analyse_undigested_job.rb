# frozen_string_literal: true

# Phase B: enqueue digest/dup analysis for files that skipped it during discovery
# (SCAN_DEFER_ANALYSIS=1). Limit + stagger keep :low from flooding NFS.
class Scan::AnalyseUndigestedJob < ApplicationJob
  queue_as :low
  unique :until_executed, lock_ttl: 2.hours

  DEFAULT_LIMIT = 500

  def perform(limit: DEFAULT_LIMIT, library_id: nil)
    scope = ModelFile.without_special.where(digest: nil)
    scope = scope.joins(:model).where(models: {library_id: library_id}) if library_id.present?

    count = 0
    scope.limit(limit).find_each do |file|
      Analysis::AnalyseModelFileJob.set(wait: (count * 0.05).seconds).perform_later(file.id)
      count += 1
    end

    Rails.logger.info("[scan] AnalyseUndigestedJob enqueued=#{count} limit=#{limit} library=#{library_id}")
    count
  end
end
