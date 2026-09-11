# frozen_string_literal: true

# INIT-027/SPEC-009 — creators/collections indexes are thin wrappers around shared chrome.
require "rails_helper"

RSpec.describe "browse index DRY" do # rubocop:todo RSpec/DescribeClass
  it "keeps creators and collections index templates at or under 25 lines" do
    creators = Rails.root.join("app/views/creators/index.html.erb").readlines
    collections = Rails.root.join("app/views/collections/index.html.erb").readlines
    expect(creators.size).to be <= 25
    expect(collections.size).to be <= 25
  end

  it "puts shared browse chrome in one partial" do
    chrome = Rails.root.join("app/views/application/_browse_index.html.erb").read
    expect(chrome).to include("content_for :browse_chrome")
    expect(chrome).to include("filter-drawer#open")
  end
end
