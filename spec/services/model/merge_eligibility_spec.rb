# frozen_string_literal: true

require "rails_helper"

# INIT-025/SPEC-005 — path parent is nesting, not merge eligibility (ADR D-4 / D-5).
RSpec.describe Model::MergeEligibility do
  let(:library) { create(:library) }
  # Live pair shape (ASMT-013): Stormtrooper under Girl — path prefix only.
  # Create the parent first so Model#parents can resolve it (memoized).
  let!(:girl) do
    create(:model, library: library, path: "AnySTL/Girl Sitting on Dinosaur", name: "Girl Sitting on Dinosaur")
  end
  let!(:stormtrooper) do
    create(
      :model,
      library: library,
      path: "AnySTL/Girl Sitting on Dinosaur/Alliance-Stormtrooper_Samurai_NSFW",
      name: "Alliance Stormtrooper"
    )
  end
  let(:unrelated) { create(:model, library: library, path: "AnySTL/Other Pack", name: "Other Pack") }

  describe "#merge_targets" do
    it "is empty when the only relation is parents (v1 same-pack signals empty)" do
      expect(described_class.merge_targets(stormtrooper)).to eq([])
    end
  end

  describe "#eligible?" do
    it "rejects a path parent with no same-pack signal" do
      expect(described_class.eligible?(source: stormtrooper, target: girl)).to be false
    end

    it "allows a non-ancestor target (digest / HITL merge unchanged)" do
      expect(described_class.eligible?(source: stormtrooper, target: unrelated)).to be true
    end
  end

  it "does not change Model#parents nesting" do
    expect(stormtrooper.parents).to eq([girl])
  end
end
