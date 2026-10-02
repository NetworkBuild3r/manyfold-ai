# frozen_string_literal: true

module DuplicateTriage
  # Paced LLM judge over cross-model pairs (INIT-031/SPEC-004).
  # One Sidekiq slot on `analysis` (after `low`); HTTP fan-out is in-process.
  class JudgeJob < ApplicationJob
    queue_as :analysis
    unique :until_executed, lock_ttl: 14.hours
    sidekiq_options retry: 1

    # INIT-031/SPEC-004 live probe (20 real evidence prompts, k82 throwaway pod):
    #   conc 1:  69.0 pairs/h  p50 54s  p95 63s
    #   conc 2: 120.5 pairs/h  p50 59s  p95 75s
    #   conc 4: 211.6 pairs/h  p50 71s  p95 78s
    #   conc 8: 367.3 pairs/h  p50 66s  p95 84s  (0 errors)
    # Chosen 8: best throughput, p95 still under the 180s read timeout, one
    # Sidekiq slot so the `low` digest drain is not starved (GR-004).
    # 10k pairs @ 367/h ≈ 27h — REQ-007 12h is not met; the per-call floor
    # is ~1 minute. Override with DUPLICATE_TRIAGE_LLM_CONCURRENCY to retune.
    DEFAULT_CONCURRENCY = 8
    BATCH_PAUSE_SECONDS = 2

    Item = Data.define(:pair, :evidence)

    def perform(limit = nil)
      LlmJudge.configure!
      cap = limit.present? ? Integer(limit) : nil
      items = llm_items
      items = items.first(cap) if cap
      batches = batches_for(items)
      batches.each_with_index do |batch, index|
        persist_batch(batch)
        sleep BATCH_PAUSE_SECONDS if index < (batches.size - 1)
      end
    end

    def self.concurrency
      raw = ENV["DUPLICATE_TRIAGE_LLM_CONCURRENCY"]
      return DEFAULT_CONCURRENCY if raw.nil? || raw.strip.empty?

      Integer(raw)
    end

    private

    def concurrency
      self.class.concurrency
    end

    def llm_items
      pairs = Pairs.new.to_a
      index = FileIndex.load(pairs.flat_map { |pair| [pair.model_a.id, pair.model_b.id] }.uniq)
      pairs.filter_map { |pair| item_for(pair, index) }
        .sort_by { |item| -item.evidence.byte_containment }
    end

    # Highest overlap first; the below-0.01 band is its own trailing
    # slice so a low pair is never judged in the same wave as a high one
    # (AC5 / ADR Addendum A-1).
    def batches_for(items)
      head, tail = items.partition { |item| item.evidence.byte_containment >= 0.01 }
      head.each_slice(concurrency).to_a + tail.each_slice(concurrency).to_a
    end

    def item_for(pair, index)
      return if Ancestry.nested?(pair.model_a, pair.model_b)

      evidence = Evidence.build(pair.model_a, pair.model_b, files: index)
      current = DuplicatePairVerdict.current_for(pair.model_a, pair.model_b, evidence.fingerprint)
      return if skip?(current)

      Item.new(pair: pair, evidence: evidence)
    end

    def skip?(current)
      return false unless current
      return true if current.human?

      current.llm? && current.prompt_version == LlmJudge::PROMPT_VERSION
    end

    def persist_batch(batch)
      failures = []
      judged = Array.new(batch.size)
      lock = Mutex.new
      threads = batch.each_with_index.map do |item, offset|
        Thread.new do
          judged[offset] = [item, LlmJudge.call(item.evidence.to_prompt_h)]
        rescue => error
          lock.synchronize { failures << error }
        end
      end
      threads.each(&:join)
      judged.compact.each { |item, result| persist(item, result) }
      raise failures.first if failures.any?
    end

    def persist(item, result)
      pair = item.pair
      evidence = item.evidence
      decision = result.decision
      keeper = (decision == "unsure") ? pair.keeper_side.to_s : result.keeper
      row = DuplicatePairVerdict.find_or_initialize_by( # rubocop:disable Pundit/UsePolicyScope -- system llm verdict write
        model_a_id: pair.model_a.id,
        model_b_id: pair.model_b.id,
        fingerprint: evidence.fingerprint,
        source: :llm
      )
      row.assign_attributes(
        decision: decision,
        keeper: keeper,
        confidence: result.confidence,
        reason: result.reason.to_s.truncate(500),
        error: result.error,
        evidence: evidence.to_prompt_h,
        llm_model: LlmJudge.model_id,
        prompt_version: LlmJudge::PROMPT_VERSION,
        status: :proposed
      )
      row.save!
      Rails.logger.info(
        "[duplicate_triage] judged pair=#{pair.model_a.id}:#{pair.model_b.id} " \
        "decision=#{decision} error=#{result.error}"
      )
    end
  end
end
