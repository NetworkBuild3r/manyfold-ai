# frozen_string_literal: true

require "rails_helper"

RSpec.describe BrowseGrid do
  describe ".columns" do
    it "clamps to 2..4" do
      expect(described_class.columns("grid_columns" => 1)).to eq(2)
      expect(described_class.columns("grid_columns" => 3)).to eq(3)
      expect(described_class.columns("grid_columns" => 9)).to eq(4)
    end
  end

  describe ".aligned_page_size" do
    it "rounds up to a multiple of columns" do
      expect(described_class.aligned_page_size(24, 3)).to eq(24)
      expect(described_class.aligned_page_size(25, 3)).to eq(27)
      expect(described_class.aligned_page_size(10, 4)).to eq(12)
    end
  end

  describe ".page_size_for_settings" do
    it "aligns default pagination settings" do
      expect(described_class.page_size_for_settings("per_page" => 24, "grid_columns" => 3)).to eq(24)
      expect(described_class.page_size_for_settings("per_page" => 24, "grid_columns" => 4)).to eq(24)
    end
  end
end
