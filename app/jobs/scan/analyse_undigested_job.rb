# frozen_string_literal: true

# Phase B: enqueue digest/dup analysis for files that skipped it during discovery
# (SCAN_DEFER_ANALYSIS=1). Limit + stagger keep :low from flooding NFS.
#
# Files that already carry an open :missing Problem are skipped: AnalyseModelFileJob
# returns immediately for a file that is not on storage and never writes a digest, so
# those rows stay `digest IS NULL` forever. Because this scan is ordered by id, a block
# of stale rows at the low end would otherwise be re-picked on every run and starve all
# the real files behind it (dedup then only sees the files that were digested at discovery).
class Scan::AnalyseUndigestedJob < ApplicationJob
  queue_as :low
  unique :until_executed, lock_ttl: 2.hours

  DEFAULT_LIMIT = 500

  def perform(limit: DEFAULT_LIMIT, library_id: nil)
    scope = ModelFile.without_special.where(digest: nil).where.not(id: missing_file_ids)
    scope = scope.joins(:model).where(models: {library_id: library_id}) if library_id.present?

    count = 0
    scope.limit(limit).find_each do |file|
      Analysis::AnalyseModelFileJob.set(wait: (count * 0.05).seconds).perform_later(file.id)
      count += 1
    end

    Rails.logger.info("[scan] AnalyseUndigestedJob enqueued=#{count} limit=#{limit} library=#{library_id}")
    count
  end

  private

  def missing_file_ids
    Problem.where(problematic_type: "ModelFile", category: :missing).select(:problematic_id) # rubocop:disable Pundit/UsePolicyScope -- system scan
  end
end
