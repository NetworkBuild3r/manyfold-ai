# frozen_string_literal: true

require "rails_helper"

RSpec.describe Components::ModelCard, type: :component do
  let(:model) { create(:model, name: "Test Model") }

  before do
    # edit?/destroy? for ModelCard; show?: false so StatusBadges skips problems_including_files (avoids policy_scope/Warden)
    policy_double = double(edit?: true, destroy?: true, show?: false)
    allow(controller).to receive(:policy).and_return(policy_double)
  end

  it "renders the model name" do
    html = render described_class.new(model: model)
    expect(html).to include("Test Model")
  end

  it "renders with model-card class" do
    html = render described_class.new(model: model)
    expect(html).to include("model-card")
  end

  it "renders ModelCardPreview and ModelCardActions" do
    html = render described_class.new(model: model)
    expect(html).to include("model-card-selection-bubble")
  end
end
