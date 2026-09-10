# frozen_string_literal: true

require "rails_helper"
require "support/mock_directory"

RSpec.describe Problems::SweepSameModelExtras do
  around do |ex|
    MockDirectory.create([
      "keep/keep.stl",
      "keep/extra.stl",
      "other/copy.stl"
    ]) do |path|
      @library_path = path
      ex.run
    end
  end

  let(:library) { create(:library, path: @library_path) } # rubocop:todo RSpec/InstanceVariable

  it "drops leftover extras on one model and clears their Problems" do # rubocop:todo RSpec/ExampleLength, RSpec/MultipleExpectations
    model = create(:model, library: library, path: "keep")
    keeper = create(:model_file, model: model, filename: "keep.stl")
    extra = create(:model_file, model: model, filename: "extra.stl")
    keeper.update_columns(digest: "same", size: 2048) # rubocop:disable Rails/SkipsModelValidations
    extra.update_columns(digest: "same", size: 2048) # rubocop:disable Rails/SkipsModelValidations
    create(:problem, category: :duplicate, problematic: keeper)
    create(:problem, category: :duplicate, problematic: extra)

    result = described_class.call

    expect(result.collapsed).to eq 1
    expect(ModelFile.where(id: extra.id)).not_to exist
    expect(Problem.where(category: :duplicate, problematic: [keeper, extra])).not_to exist
  end

  it "leaves a real two-model pair on the Problems list" do # rubocop:todo RSpec/ExampleLength, RSpec/MultipleExpectations
    model_a = create(:model, library: library, path: "keep")
    model_b = create(:model, library: library, path: "other")
    file_a = create(:model_file, model: model_a, filename: "keep.stl")
    file_b = create(:model_file, model: model_b, filename: "copy.stl")
    file_a.update_columns(digest: "cross", size: 2048) # rubocop:disable Rails/SkipsModelValidations
    file_b.update_columns(digest: "cross", size: 2048) # rubocop:disable Rails/SkipsModelValidations
    create(:problem, category: :duplicate, problematic: file_a)
    create(:problem, category: :duplicate, problematic: file_b)

    result = described_class.call

    expect(result.collapsed).to eq 0
    expect(ModelFile.where(id: [file_a.id, file_b.id]).count).to eq 2
    expect(Problem.where(category: :duplicate, problematic: [file_a, file_b]).count).to eq 2
  end
end
