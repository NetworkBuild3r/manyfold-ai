# frozen_string_literal: true

require "rails_helper"

RSpec.describe BrowseGrid do
  describe ".page_size" do
    it "is a fixed batch for the HTML first page" do
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

  describe ".page_size_for_request" do
    it "uses PAGE_SIZE for non-stream HTML" do
      expect(described_class.page_size_for_request({per_page: "54"}, stream: false)).to eq(48)
    end

    it "honors clamped per_page on infinite-scroll requests" do
      expect(described_class.page_size_for_request({per_page: "54"}, stream: true)).to eq(54)
      expect(described_class.page_size_for_request({per_page: "24"}, stream: true)).to eq(24)
    end

    it "honors per_page when offset is present" do
      expect(described_class.page_size_for_request({offset: "48", per_page: "30"}, stream: true)).to eq(30)
    end

    it "allows single-card refill (per_page=1)" do
      expect(described_class.page_size_for_request({per_page: "1", offset: "10"}, stream: true)).to eq(1)
    end

    it "clamps per_page to 1..96" do
      expect(described_class.page_size_for_request({per_page: "0"}, stream: true)).to eq(1)
      expect(described_class.page_size_for_request({per_page: "200"}, stream: true)).to eq(96)
    end

    it "falls back to PAGE_SIZE when stream has no per_page or offset" do
      expect(described_class.page_size_for_request({}, stream: true)).to eq(48)
    end
  end

  describe ".offset_for_request" do
    it "clamps offset to a safe range" do
      expect(described_class.offset_for_request({offset: "-5"})).to eq(0)
      expect(described_class.offset_for_request({offset: "48"})).to eq(48)
      expect(described_class.offset_for_request({offset: "99999999"})).to eq(1_000_000)
    end
  end

  describe ".clamp_page_size" do
    it "clamps to MIN..MAX" do
      expect(described_class.clamp_page_size(0)).to eq(1)
      expect(described_class.clamp_page_size(1)).to eq(1)
      expect(described_class.clamp_page_size(48)).to eq(48)
      expect(described_class.clamp_page_size(999)).to eq(96)
    end
  end
end
