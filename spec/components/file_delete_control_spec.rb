# frozen_string_literal: true

# INIT-027/SPEC-010
require "rails_helper"

RSpec.describe Components::FileDeleteControl, type: :component do
  it "renders a DoButton DELETE with turbo_confirm naming the noun" do # rubocop:todo RSpec/ExampleLength, RSpec/MultipleExpectations
    html = render described_class.new(
      href: "/models/1/model_files/2",
      confirm: "Remove this file from your filesystem?",
      label: "Delete file"
    )
    expect(html).to include("<form")
    expect(html).to include('name="_method"')
    expect(html).to include('value="delete"')
    expect(html).to include('data-turbo-confirm="Remove this file from your filesystem?"')
    expect(html).to include("Delete file")
    expect(html).not_to include("data-method")
  end

  it "keeps icon-only trash labeled with the noun in aria-label" do
    html = render described_class.new(
      href: "/models/1/model_files/2",
      confirm: "Remove this image from the model folder?",
      label: "Delete image",
      icon_only: true
    )
    expect(html).to include('aria-label="Delete image"')
    expect(html).to include('data-turbo-confirm="Remove this image from the model folder?"')
  end
end
