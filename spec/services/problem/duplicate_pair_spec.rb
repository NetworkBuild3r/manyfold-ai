# frozen_string_literal: true

require "rails_helper"

RSpec.describe Problem::DuplicatePair do
  let(:model_a) { create(:model, name: "Ichigo") }
  let(:model_b) { create(:model, name: "Ichigo Copy") }
  let(:file_a) { create(:model_file, model: model_a, filename: "hero.stl") }
  let(:file_b) { create(:model_file, model: model_b, filename: "hero_copy.stl") }
  let(:problem) { create(:problem, category: :duplicate, problematic: file_a) }

  before do
    file_a.update_column(:digest, "same-digest") # rubocop:disable Rails/SkipsModelValidations
    file_b.update_column(:digest, "same-digest") # rubocop:disable Rails/SkipsModelValidations
  end

  it "is mergeable when the same digest lives on another model" do
    pair = described_class.build(problem)
    expect(pair).to be_mergeable
    expect(pair.other_models).to contain_exactly(model_b)
    expect(pair.primary_other_file).to eq file_b
  end

  it "is not mergeable when both copies are on the same model" do
    extra = create(:model_file, model: model_a, filename: "hero_dup.stl")
    extra.update_column(:digest, "same-digest") # rubocop:disable Rails/SkipsModelValidations
    file_b.update_column(:digest, "other") # rubocop:disable Rails/SkipsModelValidations

    pair = described_class.build(problem)
    expect(pair).not_to be_mergeable
    expect(pair.same_model_copies).to contain_exactly(extra)
  end
end
