# frozen_string_literal: true

require "rails_helper"

RSpec.describe DuplicateTriage::Deterministic, type: :duplicate_triage do
  let(:library) { create(:library) }

  describe "a nested pair (AC4)" do
    let!(:parent) do
      create(:model, library: library, path: "AnySTL/Girl Sitting on Dinosaur", name: "Girl")
    end
    let!(:child) do
      create(:model, library: library, path: "AnySTL/Girl Sitting on Dinosaur/Stormtrooper", name: "Trooper")
    end

    before do
      digested_file(parent, filename: "shared.stl", digest: "nested", size: 80)
      digested_file(parent, filename: "extra.stl", digest: "parent-only", size: 20)
      digested_file(child, filename: "shared.stl", digest: "nested", size: 80)
    end

    it "writes a deterministic keep_separate row" do
      rows = described_class.call
      expect(rows.size).to eq(1)
      row = rows.first
      expect(row).to be_deterministic
      expect(row).to be_decision_keep_separate
      expect(row.confidence).to eq(1)
      expect(row.reason).to eq(described_class::REASON)
    end

    it "stores the evidence snapshot and fingerprint" do
      row = described_class.call.first
      evidence = DuplicateTriage::Evidence.build(parent, child)
      expect(row.fingerprint).to eq(evidence.fingerprint)
      expect(row.evidence["nested"]).to be(true)
      expect(row.evidence["fingerprint"]).to eq(evidence.fingerprint)
    end

    it "is idempotent for the same fingerprint" do
      described_class.call
      expect { described_class.call }.not_to change(DuplicatePairVerdict, :count)
    end
  end

  describe "a non-nested pair (AC4)" do
    let!(:left) { create(:model, library: library, path: "Pack/Left", name: "Left") }
    let!(:right) { create(:model, library: library, path: "Pack/Right", name: "Right") }

    before do
      digested_file(left, filename: "shared.stl", digest: "siblings", size: 40)
      digested_file(right, filename: "shared.stl", digest: "siblings", size: 40)
    end

    it "writes no deterministic row" do
      expect(described_class.call).to be_empty
      expect(DuplicatePairVerdict.where(source: :deterministic)).to be_empty
    end
  end
end
