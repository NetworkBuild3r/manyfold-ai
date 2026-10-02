# frozen_string_literal: true

require "rails_helper"

RSpec.describe DuplicateTriage::CalibrationSample, type: :duplicate_triage do
  def verdict(containment:, confidence:)
    create(
      :duplicate_pair_verdict,
      confidence: confidence,
      evidence: {"byte_containment" => containment}
    )
  end

  it "takes one row from each containment/band stratum up to the limit" do
    high = verdict(containment: 0.95, confidence: 0.96)
    mid = verdict(containment: 0.6, confidence: 0.75)
    low = verdict(containment: 0.001, confidence: 0.4)
    picked = described_class.call(3)
    expect(picked.map { |row| row[:fingerprint] }).to contain_exactly(
      high.fingerprint, mid.fingerprint, low.fingerprint
    )
    expect(picked.map { |row| row[:byte_containment_bin] }).to include("gte_0_90", "gte_0_50", "lt_0_01")
    expect(picked.map { |row| row[:llm_band] }).to include("high", "medium", "low")
  end

  it "prints JSON from the sample rake without writing rows" do
    verdict(containment: 0.95, confidence: 0.96)
    task = Rake::Task["manyfold:duplicate_triage:sample"]
    task.reenable
    expect {
      expect { task.invoke("1") }.to output(/"llm_band"/).to_stdout
    }.not_to change(DuplicatePairVerdict, :count)
  end
end
