# frozen_string_literal: true

require "rails_helper"

# INIT-027/SPEC-011
RSpec.describe Components::PageTitle, type: :component do
  it "uses NAV_CLASS and HEADING_CLASS constants" do
    html = render described_class.new(title: "Library")
    expect(html).to include(%(class="#{described_class::NAV_CLASS}"))
    expect(html).to include(%(class="#{described_class::HEADING_CLASS}"))
    expect(html).to include("Library")
  end

  it "omits the heading when heading: false" do
    html = render described_class.new(title: "Library", heading: false)
    expect(html).not_to include("<h1")
    expect(html).to include("Library")
  end
end
