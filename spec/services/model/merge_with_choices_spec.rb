# frozen_string_literal: true

require "rails_helper"
require "support/mock_directory"

RSpec.describe Model::MergeWithChoices do
  around do |ex|
    MockDirectory.create([
      "alpha/part.stl",
      "beta/copy.stl"
    ]) do |path|
      @library_path = path
      ex.run
    end
  end

  let(:library) { create(:library, path: @library_path) } # rubocop:todo RSpec/InstanceVariable
  let!(:model_a) { create(:model, library: library, path: "alpha", name: "Alpha", notes: "Keep me") }
  let!(:model_b) { create(:model, library: library, path: "beta", name: "Beta", notes: "From B") }

  before do
    create(:model_file, model: model_a, filename: "part.stl")
    create(:model_file, model: model_b, filename: "copy.stl")
  end

  it "merges source into target and applies chosen field values" do # rubocop:todo RSpec/ExampleLength
    described_class.call(
      target: model_a,
      source: model_b,
      choices: {"name" => "b", "notes" => "a"},
      tag_strategy: "combine"
    )

    model_a.reload
    expect(model_a.name).to eq "Beta"
    expect(model_a.notes).to eq "Keep me"
    expect(Model.where(id: model_b.id)).not_to exist
    expect(model_a.model_files.count).to eq 2
  end

  it "applies override text when chosen" do
    described_class.call(
      target: model_a,
      source: model_b,
      choices: {"name" => "override"},
      overrides: {"name" => "Merged Ichigo"}
    )

    expect(model_a.reload.name).to eq "Merged Ichigo"
  end
end
