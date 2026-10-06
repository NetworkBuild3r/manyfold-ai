# frozen_string_literal: true

module DuplicateTriage
  # Stratified owner-review sample by byte_containment bin and LLM band
  # (INIT-031/SPEC-004, D-4).
  class CalibrationSample
    CONTAINMENT_BINS = [
      ["gte_0_90", 0.9..],
      ["gte_0_50", 0.5...0.9],
      ["gte_0_01", 0.01...0.5],
      ["lt_0_01", ...0.01]
    ].freeze

    LLM_BANDS = [
      ["high", 0.9..],
      ["medium", 0.7...0.9],
      ["low", ...0.7]
    ].freeze

    def self.call(limit)
      new(limit).call
    end

    def initialize(limit)
      @limit = Integer(limit)
    end

    def call
      rows = llm_rows
      return pair_only_sample if rows.empty?

      buckets = Hash.new { |hash, key| hash[key] = [] }
      rows.each do |row|
        buckets[[containment_bin(row), llm_band(row)]] << row
      end
      take_round_robin(buckets).map { |row| present_verdict(row) }
    end

    private

    def llm_rows
      DuplicatePairVerdict.where(source: :llm).to_a # rubocop:disable Pundit/UsePolicyScope -- system calibration sample
    end

    def pair_only_sample
      pairs = Pairs.new.to_a
      index = FileIndex.load(pairs.flat_map { |pair| [pair.model_a.id, pair.model_b.id] }.uniq)
      buckets = Hash.new { |hash, key| hash[key] = [] }
      pairs.each do |pair|
        evidence = Evidence.build(pair.model_a, pair.model_b, files: index)
        buckets[[bin_for(evidence.byte_containment), "unjudged"]] << [pair, evidence]
      end
      take_round_robin(buckets).map { |pair, evidence| present_pair(pair, evidence) }
    end

    def take_round_robin(buckets)
      lists = buckets.values.reject(&:empty?).map(&:shuffle)
      picked = []
      while picked.size < @limit && lists.any?(&:any?)
        lists.each do |list|
          next if list.empty?
          break if picked.size >= @limit

          picked << list.shift
        end
      end
      picked
    end

    def containment_bin(row)
      bin_for(row.evidence.to_h.stringify_keys["byte_containment"].to_f)
    end

    def llm_band(row)
      band_for(row.confidence)
    end

    def bin_for(value)
      CONTAINMENT_BINS.find { |_name, range| range.cover?(value) }&.first || "lt_0_01"
    end

    def band_for(value)
      return "unjudged" if value.nil?

      LLM_BANDS.find { |_name, range| range.cover?(value.to_f) }&.first || "low"
    end

    def present_verdict(row)
      {
        model_a_id: row.model_a_id,
        model_b_id: row.model_b_id,
        fingerprint: row.fingerprint,
        decision: row.decision,
        confidence: row.confidence,
        byte_containment_bin: containment_bin(row),
        llm_band: llm_band(row)
      }
    end

    def present_pair(pair, evidence)
      {
        model_a_id: pair.model_a.id,
        model_b_id: pair.model_b.id,
        fingerprint: evidence.fingerprint,
        decision: nil,
        confidence: nil,
        byte_containment_bin: bin_for(evidence.byte_containment),
        llm_band: "unjudged"
      }
    end
  end
end
