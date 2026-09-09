# frozen_string_literal: true

require "rails_helper"

RSpec.describe Problem::DuplicateGroup do
  describe ".representative_ids" do
    it "keeps one problem per identical digest" do
      model_a = create(:model)
      model_b = create(:model)
      file_a = create(:model_file, model: model_a, filename: "a.stl")
      file_b = create(:model_file, model: model_b, filename: "b.stl")
      file_a.update_column(:digest, "same") # rubocop:disable Rails/SkipsModelValidations
      file_b.update_column(:digest, "same") # rubocop:disable Rails/SkipsModelValidations
      first = create(:problem, category: :duplicate, problematic: file_a)
      create(:problem, category: :duplicate, problematic: file_b)
      other = create(:model_file, model: model_a, filename: "solo.stl")
      other.update_column(:digest, "solo") # rubocop:disable Rails/SkipsModelValidations
      solo = create(:problem, category: :duplicate, problematic: other)

      ids = described_class.representative_ids(Problem.where(category: :duplicate))

      expect(ids).to contain_exactly(first.id, solo.id)
    end
  end

  describe ".recoverable_bytes" do
    it "counts extra copies only" do
      model = create(:model)
      keep = create(:model_file, model: model, filename: "keep.stl")
      extra = create(:model_file, model: model, filename: "extra.stl")
      keep.update_columns(digest: "same", size: 100) # rubocop:disable Rails/SkipsModelValidations
      extra.update_columns(digest: "same", size: 40) # rubocop:disable Rails/SkipsModelValidations
      create(:problem, category: :duplicate, problematic: extra)

      expect(described_class.recoverable_bytes(Problem.all, ModelFile.all)).to eq 40
    end
  end
end
