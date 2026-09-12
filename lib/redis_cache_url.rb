# frozen_string_literal: true

require "uri"

# INIT-030/SPEC-003 — production Rails.cache URL.
# Cluster REDIS_URL is Sidekiq + ActiveJob::Status (typically /1). Cache uses database /2.
# GR-004: never point Rails.cache at Sidekiq /1 or at ActiveJob::Status's URL unchanged.
class RedisCacheUrl
  CACHE_DB = 2

  def self.call(redis_url)
    url = redis_url.to_s.strip
    raise ArgumentError, "REDIS_URL is not configured" if url.empty?

    uri = URI.parse(url)
    uri.path = "/#{CACHE_DB}"
    uri.to_s
  end
end
