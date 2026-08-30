# frozen_string_literal: true

# INIT-013/SPEC-002 — KPI / chart read path without Redis KEYS (ADR D-3 / D-4).
# Percentiles and throughput come from HTTP request samples only — never Sidekiq keys.
module Performance
  class Telemetry
    REQUEST_MATCH = "performance|*"
    CACHE_TTL = 15.seconds

    Result = Data.define(
      :p50, :p95, :p99,
      :throughput,
      :sample_count,
      :budget_exceeded
    )

    def initialize(redis: nil, scan_count: Performance::RedisScan::DEFAULT_COUNT,
      max_iterations: Performance::RedisScan::DEFAULT_MAX_ITERATIONS,
      cache: true)
      @redis = redis
      @scan_count = scan_count
      @max_iterations = max_iterations
      @cache = cache
    end

    def call
      if @cache && defined?(Rails) && Rails.respond_to?(:cache)
        Rails.cache.fetch(cache_key, expires_in: CACHE_TTL) { compute }
      else
        compute
      end
    end

    private

    def compute
      client = redis_client
      return empty_result(budget_exceeded: false) if client.nil?

      scan = Performance::RedisScan.each_matching(
        client,
        match: REQUEST_MATCH,
        count: @scan_count,
        max_iterations: @max_iterations
      )

      samples = load_request_samples(client, scan.keys)
      durations = samples.filter_map { |s| s[:duration] }.select { |d| d.is_a?(Numeric) }

      Result.new(
        p50: percentile(durations, 50),
        p95: percentile(durations, 95),
        p99: percentile(durations, 99),
        throughput: throughput_series(samples),
        sample_count: samples.size,
        budget_exceeded: scan.budget_exceeded
      )
    end

    def redis_client
      @redis || (defined?(RailsPerformance) && RailsPerformance.redis)
    end

    def load_request_samples(client, keys)
      return [] if keys.empty?

      values = client.mget(*keys)
      keys.zip(values).filter_map do |key, raw|
        next if raw.blank?

        parsed = parse_json(raw)
        duration = parsed["duration"]
        datetime = datetime_from_key(key)
        {
          duration: duration,
          datetime: datetime,
          datetimei: datetimei_from_key(key)
        }
      end
    end

    def parse_json(raw)
      JSON.parse(raw)
    rescue JSON::ParserError
      {}
    end

    # performance|…|datetime|20200124T0523|datetimei|1579861423|…
    def datetime_from_key(key)
      parts = key.to_s.split("|")
      idx = parts.index("datetime")
      idx ? parts[idx + 1] : nil
    end

    def datetimei_from_key(key)
      parts = key.to_s.split("|")
      idx = parts.index("datetimei")
      idx ? parts[idx + 1].to_i : nil
    end

    def percentile(values, pct)
      return nil if values.empty?

      if defined?(RailsPerformance::Utils) && RailsPerformance::Utils.respond_to?(:percentile)
        return RailsPerformance::Utils.percentile(values, pct)
      end

      sorted = values.sort
      rank = (pct.to_f / 100) * (sorted.size - 1)
      lower = sorted[rank.floor]
      upper = sorted[rank.ceil]
      lower + (upper - lower) * (rank - rank.floor)
    end

    # Bucket by minute (RP datetime key YYYYMMDDTHHMM) → rpm points sorted by bucket.
    def throughput_series(samples)
      buckets = Hash.new(0)
      samples.each do |sample|
        bucket = sample[:datetime]
        next if bucket.blank?

        buckets[bucket] += 1
      end
      buckets.keys.sort.map { |k| {datetime: k, rpm: buckets[k]} }
    end

    def empty_result(budget_exceeded:)
      Result.new(
        p50: nil, p95: nil, p99: nil,
        throughput: [],
        sample_count: 0,
        budget_exceeded: budget_exceeded
      )
    end

    def cache_key
      "performance/telemetry/v1"
    end
  end
end
