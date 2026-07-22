# frozen_string_literal: true

require "rails_helper"

RSpec.describe BrowseGrid do
  describe ".page_size" do
    it "is a fixed batch for card-sized auto-fill grids" do
      expect(described_class.page_size).to eq(48)
      expect(described_class.page_size("per_page" => 12, "grid_columns" => 2)).to eq(48)
    end
  end

  describe ".page_size_for_settings" do
    it "ignores legacy settings and returns PAGE_SIZE" do
      expect(described_class.page_size_for_settings("per_page" => 24, "grid_columns" => 3)).to eq(48)
      expect(described_class.page_size_for_settings("per_page" => 100, "grid_columns" => 4)).to eq(48)
    end
  end
end
