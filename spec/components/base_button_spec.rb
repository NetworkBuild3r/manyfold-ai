# frozen_string_literal: true

require "rails_helper"

RSpec.describe Components::DoButton, type: :component do
  it "renders a form with primary variant classes" do
    html = render described_class.new(
      label: "Save",
      href: "/save",
      variant: "primary"
    )
    expect(html).to include("Save")
    expect(html).to include("bg-primary-600")
    expect(html).to include("action=")
  end

  it "renders secondary variant when specified" do
    html = render described_class.new(
      label: "Cancel",
      href: "/cancel",
      variant: "secondary"
    )
    expect(html).to include("border")
    expect(html).to include("rounded-lg")
  end
end
