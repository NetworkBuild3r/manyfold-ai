# frozen_string_literal: true

module DuplicateTriage
  # D-2: ancestry is the only deterministic decision. Nested pairs become
  # keep_separate; everything else is left for the LLM (INIT-031/SPEC-003).
  class Deterministic
    REASON = "nested folder, not a duplicate product"

    def self.call(pairs: nil)
      new(pairs: pairs).call
    end

    def initialize(pairs: nil)
      @pairs = pairs
    end

    def call
      nested = candidates.select { |pair| Ancestry.nested?(pair.model_a, pair.model_b) }
      return [] if nested.empty?

      index = FileIndex.load(nested.flat_map { |pair| [pair.model_a.id, pair.model_b.id] }.uniq)
      nested.map { |pair| persist(pair, Evidence.build(pair.model_a, pair.model_b, files: index)) }
    end

    private

    def candidates
      @pairs || Pairs.new.to_a
    end

    def persist(pair, evidence)
      row = DuplicatePairVerdict.find_or_initialize_by( # rubocop:disable Pundit/UsePolicyScope -- system deterministic verdict write
        model_a_id: pair.model_a.id,
        model_b_id: pair.model_b.id,
        fingerprint: evidence.fingerprint,
        source: :deterministic
      )
      row.assign_attributes(
        decision: :keep_separate,
        keeper: pair.keeper_side,
        confidence: 1.0,
        reason: REASON,
        evidence: evidence.to_prompt_h,
        status: :proposed
      )
      row.save!
      row
    end
  end
end
