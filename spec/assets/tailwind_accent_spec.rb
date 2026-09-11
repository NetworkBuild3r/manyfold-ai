# frozen_string_literal: true

require "rails_helper"

# INIT-027/SPEC-005 — documented CSS alias; not a third palette.
RSpec.describe "tailwind appearance accent alias" do
  let(:css) { Rails.root.join("app/assets/stylesheets/tailwind.css").read }

  it "defines an OKLCH scale for every AVAILABLE_ACCENTS value including indigo" do
    SiteSettings::AVAILABLE_ACCENTS.each do |accent|
      expect(css).to include(%(:root[data-accent="#{accent}"]))
    end
    expect(css).to match(/:root\[data-accent="indigo"\]\s*\{[^}]*--accent-600:\s*oklch\(/m)
  end

  it "remaps --color-primary-* from --accent-* so primary utilities follow the picker" do
    expect(css).to include("--color-primary-600: var(--accent-600)")
    expect(css).to include("--color-primary-400: var(--accent-400)")
    expect(css).to include("--color-primary-700: var(--accent-700)")
  end

  it "does not use raw hex in accent palette blocks" do
    accent_section = css[/:root\[data-accent="indigo"\].*:root\[data-accent\]\s*\{/m]
    expect(accent_section).to be_present
    expect(accent_section).not_to match(/#[0-9a-fA-F]{3,8}\b/)
  end
end
