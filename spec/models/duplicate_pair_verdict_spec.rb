# frozen_string_literal: true

require "rails_helper"

RSpec.describe DuplicatePairVerdict do
  def new_verdict(**attrs)
    described_class.new({
      fingerprint: SecureRandom.hex(32),
      source: :llm,
      decision: :merge,
      keeper: :a,
      status: :proposed,
      evidence: {}
    }.merge(attrs))
  end

  it "declares the pair-order check constraint and both indexes (AC1)" do
    checks = described_class.connection.check_constraints("duplicate_pair_verdicts")
    expect(checks.map(&:expression)).to include(a_string_matching(/model_a_id < model_b_id/))
    names = described_class.connection.indexes("duplicate_pair_verdicts").map(&:name)
    expect(names).to include(
      "index_dup_verdicts_on_pair_fingerprint_source",
      "index_dup_verdicts_on_status_decision_confidence"
    )
  end

  it "rejects reversed model ids at the database (AC2)" do
    lower, higher = [create(:model), create(:model)].sort_by(&:id)
    row = new_verdict(model_a: higher, model_b: lower)
    expect { row.save!(validate: false) }.to raise_error(ActiveRecord::StatementInvalid)
  end

  it "returns the human row when human and llm share a fingerprint (AC3)" do
    pair = create(:duplicate_pair_verdict)
    human = create(:duplicate_pair_verdict, :human,
      model_a: pair.model_a, model_b: pair.model_b, fingerprint: pair.fingerprint)
    expect(described_class.current_for(pair.model_a, pair.model_b, pair.fingerprint)).to eq(human)
  end

  it "returns nothing when the fingerprint differs (AC3)" do
    pair = create(:duplicate_pair_verdict)
    expect(described_class.current_for(pair.model_a, pair.model_b, "0" * 64)).to be_nil
  end

  it "returns the llm row over the deterministic row for the same fingerprint" do
    det = create(:duplicate_pair_verdict, :deterministic)
    llm = create(:duplicate_pair_verdict,
      model_a: det.model_a, model_b: det.model_b, fingerprint: det.fingerprint)
    expect(described_class.current_for(det.model_a, det.model_b, det.fingerprint)).to eq(llm)
  end

  it "normalizes pair order when looking up current_for" do
    pair = create(:duplicate_pair_verdict)
    expect(described_class.current_for(pair.model_b, pair.model_a, pair.fingerprint)).to eq(pair)
  end

  it "deletes verdict rows when either model is destroyed (AC4)" do
    left = create(:duplicate_pair_verdict)
    right = create(:duplicate_pair_verdict)
    Model.where(id: left.model_a_id).delete_all
    Model.where(id: right.model_b_id).delete_all
    expect(described_class.where(id: [left.id, right.id])).to be_empty
  end

  describe ".pending_review" do
    it "includes proposed rows and excludes applied rows" do
      proposed = create(:duplicate_pair_verdict, status: :proposed)
      create(:duplicate_pair_verdict, status: :applied)
      expect(described_class.pending_review).to contain_exactly(proposed)
    end
  end

  describe ".in_band" do
    it "filters by the given confidence range" do
      high = create(:duplicate_pair_verdict, confidence: 0.95)
      create(:duplicate_pair_verdict, confidence: 0.5)
      expect(described_class.in_band(0.9..1.0)).to contain_exactly(high)
    end
  end
end
