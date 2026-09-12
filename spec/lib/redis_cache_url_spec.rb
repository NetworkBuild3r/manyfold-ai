require "rails_helper"
require Rails.root.join("lib/redis_cache_url")

RSpec.describe RedisCacheUrl do
  it "rewrites a /1 Sidekiq URL onto cache database /2" do
    expect(described_class.call("redis://redis:6379/1")).to eq("redis://redis:6379/2")
  end

  it "adds /2 when REDIS_URL has no database path" do
    expect(described_class.call("redis://localhost:6379")).to eq("redis://localhost:6379/2")
  end

  it "does not keep Sidekiq /1" do
    expect(described_class.call("redis://redis:6379/1")).not_to include("/1")
  end

  it "raises when REDIS_URL is blank" do
    expect { described_class.call("") }.to raise_error(ArgumentError, /REDIS_URL is not configured/)
    expect { described_class.call("   ") }.to raise_error(ArgumentError, /REDIS_URL is not configured/)
  end
end
