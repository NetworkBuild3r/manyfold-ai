# frozen_string_literal: true

require "rails_helper"

RSpec.describe Scan::AnalyseUndigestedJob do
  let(:library) { create(:library) }
  let(:model) { create(:model, library: library) }

  before do
    create(:model_file, model: model, filename: "a.stl", digest: nil)
    create(:model_file, model: model, filename: "b.stl", digest: "abc")
  end

  it "enqueues analysis only for undigested files up to the limit" do
    expect {
      described_class.perform_now(limit: 10)
    }.to have_enqueued_job(Analysis::AnalyseModelFileJob).exactly(1).times
  end

  context "when stale rows sit ahead of real files" do
    let!(:stale) { create(:model_file, model: model, filename: "gone.stl", digest: nil) }
    let!(:real) { create(:model_file, model: model, filename: "real.stl", digest: nil) }

    before do
      Problem.create!(problematic: stale, category: :missing)
    end

    it "skips files with an open missing problem so they cannot starve the drain" do
      # limit 2 would be filled by [a.stl, gone.stl] if stale rows were not excluded
      described_class.perform_now(limit: 2)
      enqueued = ActiveJob::Base.queue_adapter.enqueued_jobs.map { |j| j["arguments"] || j[:args] }.flatten
      expect(enqueued).to include(real.id)
      expect(enqueued).not_to include(stale.id)
    end
  end
end
