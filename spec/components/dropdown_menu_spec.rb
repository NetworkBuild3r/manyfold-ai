# frozen_string_literal: true

require "rails_helper"

# INIT-027/SPEC-011
RSpec.describe Components::DropdownMenu do
  describe ".panel_class" do
    it "starts from PANEL_CLASS_BASE, not a call-site literal" do
      expect(described_class.panel_class).to include(described_class::PANEL_CLASS_BASE)
    end

    it "adds right alignment and down offset by default" do
      cls = described_class.panel_class
      expect(cls).to include("right-0")
      expect(cls).to include("mt-1")
      expect(cls).not_to include("left-0")
    end

    it "adds left alignment and up offset when requested" do
      cls = described_class.panel_class(align: :left, direction: :up)
      expect(cls).to include(described_class::PANEL_CLASS_BASE)
      expect(cls).to include("left-0")
      expect(cls).to include("bottom-full mb-1")
    end
  end
end
