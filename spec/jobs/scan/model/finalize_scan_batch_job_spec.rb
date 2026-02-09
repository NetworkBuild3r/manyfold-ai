# frozen_string_literal: true

require "rails_helper"

RSpec.describe Scan::Model::FinalizeScanBatchJob do
  let(:model) { create(:model) }
  let(:scan_batch_id) { SecureRandom.uuid }

  it "enqueues exactly one CheckForProblemsJob for the model" do
    expect {
      described_class.perform_now(model.id, scan_batch_id: scan_batch_id)
    }.to have_enqueued_job(Scan::Model::CheckForProblemsJob).with(model.id).exactly(:once)
  end

  it "does not enqueue a second CheckForProblemsJob when run again with same batch id" do
    described_class.perform_now(model.id, scan_batch_id: scan_batch_id)
    expect {
      described_class.perform_now(model.id, scan_batch_id: scan_batch_id)
    }.not_to have_enqueued_job(Scan::Model::CheckForProblemsJob)
  end
end
