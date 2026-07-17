class Scan::Model::FinalizeScanBatchJob < ApplicationJob
  queue_as :scan
  unique :until_executed

  def perform(model_id, scan_batch_id:)
    return if scan_batch_id.blank?

    # Ensure we only finalize once per model per batch.
    begin
      key = "manyfold:scan_batch:finalized:#{scan_batch_id}:model:#{model_id}"
      wrote = Rails.cache.write(key, true, expires_in: 1.hour, unless_exist: true)
      return unless wrote
    rescue ArgumentError, NoMethodError
      # Cache store doesn't support `unless_exist`; fall back to job uniqueness.
    end

    # Problem checks need the file list; model metadata is done. File-level
    # parse/analysis can still be in flight — that is fine: MissingFile and
    # EmptyModel only need DB rows + storage existence, not digests.
    Scan::Model::CheckForProblemsJob.perform_later(model_id)

    Model.where(id: model_id).update_all(scan_started_at: nil) # rubocop:disable Rails/SkipsModelValidations
  end
end
