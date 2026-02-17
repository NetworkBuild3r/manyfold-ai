# frozen_string_literal: true

require "rails_helper"

RSpec.describe Components::CopyButton, type: :component do
  it "renders a button with copy-text controller" do
    html = render described_class.new(text: "secret-token")
    expect(html).to include("data-controller=\"copy-text\"")
    expect(html).to include("data-copy-text-text-value=\"secret-token\"")
    expect(html).to include("data-action=\"click->copy-text#copy:prevent\"")
  end

  it "uses secondary button styling from BaseButton" do
    html = render described_class.new(text: "x")
    expect(html).to include("border")
    expect(html).to include("rounded-lg")
  end
end
