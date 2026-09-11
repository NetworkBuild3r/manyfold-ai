# frozen_string_literal: true

require "rails_helper"

# INIT-027/SPEC-011
RSpec.describe Components::Tag, type: :component do
  it "applies CLASSES from the constant, not a view literal" do
    tag = build_stubbed(:tag, name: "resin")
    html = render described_class.new(tag: tag)
    expect(html).to include(%(class="#{described_class::CLASSES}"))
    expect(html).to include("resin")
  end
end
