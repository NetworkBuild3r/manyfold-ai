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
end
