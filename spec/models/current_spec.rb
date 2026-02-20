# frozen_string_literal: true

require "rails_helper"

RSpec.describe Current do
  it "does not leak attributes outside Current.set block" do
    expect(described_class.skip_problem_checks).to be_nil
    expect(described_class.scan_batch_id).to be_nil

    described_class.set(skip_problem_checks: true, scan_batch_id: "batch-1") do
      expect(described_class.skip_problem_checks).to be(true)
      expect(described_class.scan_batch_id).to eq("batch-1")
    end

    expect(described_class.skip_problem_checks).to be_nil
    expect(described_class.scan_batch_id).to be_nil
  end
end
