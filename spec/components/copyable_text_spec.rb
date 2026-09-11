# frozen_string_literal: true

require "rails_helper"

# INIT-027/SPEC-004 — CopyButton removed; copy UX lives on CopyableText + copy-text.
RSpec.describe Components::CopyableText, type: :component do
  it "renders a button with copy-text controller" do
    html = render described_class.new(text: "secret-token")
    expect(html).to include("data-controller=\"copy-text\"")
    expect(html).to include("data-copy-text-text-value=\"secret-token\"")
    expect(html).to include("data-action=\"click->copy-text#copy:prevent\"")
  end

  it "still copies when obfuscated by keeping copy-text on the clipboard button" do
    html = render described_class.new(text: "secret-token", obfuscated: true)
    expect(html).to include("data-controller=\"copy-text\"")
    expect(html).to include("data-copy-text-text-value=\"secret-token\"")
    expect(html).to include("data-controller=\"obfuscated-text\"")
  end
end
