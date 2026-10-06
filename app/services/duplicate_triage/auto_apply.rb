# frozen_string_literal: true

module DuplicateTriage
  # Applies LLM merge verdicts with no human in the loop (owner decision 2026-10-06, replacing
  # the human gate of INIT-031 REQ-003). Safety comes from code, not from the model:
  #
  #   * only `lossless` pairs: every file of the smaller entry already exists byte-identical in
  #     the larger one, so the merge cannot drop a file;
  #   * only a consensus verdict (both a/b presentation orders said merge, confidence >= 0.9)
  #     for the current prompt version;
  #   * evidence is rebuilt right before the merge; a changed fingerprint rejects the verdict;
  #   * nested (ancestor/descendant) pairs, pairs with a human verdict and pairs whose current
  #     verdict is not this one are never touched;
  #   * the keeper comes from the evidence (larger entry; tie -> D-7), never from the model;
  #   * merges go through Model::MergeWithChoices, so each is a MergeHistory row, undoable for
  #     30 days at /merges;
  #   * paced, capped per run, and the run stops after repeated storage failures.
  class AutoApply
    MIN_CONFIDENCE = 0.9
    DEFAULT_LIMIT = 50
    DEFAULT_PACE_SECONDS = 1.0
    MAX_CONSECUTIVE_FAILURES = 3
    FILL_FIELDS = %w[name caption notes creator_id collection_id license].freeze

    Summary = Data.define(:applied, :failed, :rejected, :skipped, :would_apply, :stopped, :dry_run)

    def self.call(**options)
      new(**options).call
    end

    def initialize(limit: DEFAULT_LIMIT, dry_run: true, pace: DEFAULT_PACE_SECONDS, logger: Rails.logger)
      @limit = limit
      @dry_run = dry_run
      @pace = pace
      @logger = logger
      @counts = Hash.new(0)
      @failures_in_a_row = 0
    end

    def call
      stopped = false
      candidates.each do |verdict|
        break if @counts[:applied] + @counts[:would_apply] >= @limit

        outcome = process(verdict)
        @counts[outcome] += 1
        track_failures(outcome)
        if @failures_in_a_row >= MAX_CONSECUTIVE_FAILURES
          stopped = true
          break
        end
        sleep @pace if outcome == :applied && @pace.positive?
      end
      Summary.new(
        applied: @counts[:applied], failed: @counts[:failed], rejected: @counts[:rejected], skipped: @counts[:skipped],
        would_apply: @counts[:would_apply], stopped: stopped, dry_run: @dry_run
      )
    end

    private

    def candidates
      DuplicatePairVerdict.where( # rubocop:disable Pundit/UsePolicyScope -- system apply
        source: "llm", decision: "merge", status: "proposed",
        prompt_version: LlmJudge::PROMPT_VERSION
      ).where("confidence >= ?", MIN_CONFIDENCE)
        .where("evidence ->> 'lossless' = 'true'")
        .order(confidence: :desc, id: :asc)
    end

    def process(verdict)
      left = Model.find_by(id: verdict.model_a_id) # rubocop:disable Pundit/UsePolicyScope -- system apply
      right = Model.find_by(id: verdict.model_b_id) # rubocop:disable Pundit/UsePolicyScope -- system apply
      return reject(verdict, "model_gone") unless left && right
      return reject(verdict, "nested") if Ancestry.nested?(left, right)

      evidence = Evidence.build(left, right)
      return reject(verdict, "evidence_changed") unless evidence.fingerprint == verdict.fingerprint
      return reject(verdict, "not_lossless") unless evidence.lossless?
      return :skipped unless DuplicatePairVerdict.current_for(left, right, evidence.fingerprint)&.id == verdict.id

      target, source = keeper_and_source(left, right, evidence)
      return would_apply(verdict, target, source) if @dry_run

      apply(verdict, target, source)
    end

    def keeper_and_source(left, right, evidence)
      by_side = {"a" => left, "b" => right}
      if evidence.total_bytes_a == evidence.total_bytes_b
        counts = FileIndex.counts([left.id, right.id])
        keeper = Keeper.pick([left, right], counts)
        [keeper, (keeper == left) ? right : left]
      else
        container = by_side.fetch(evidence.container_side)
        [container, by_side.fetch(evidence.contained_side)]
      end
    end

    def would_apply(verdict, target, source)
      @logger.info("[duplicate_triage] would merge #{describe(source)} into #{describe(target)} #{verdict.reason}")
      :would_apply
    end

    def apply(verdict, target, source)
      choices, overrides = merge_choices(target, source)
      reason = verdict.reason
      confidence = verdict.confidence
      fingerprint = verdict.fingerprint
      Model::MergeWithChoices.call(
        target: target, source: source, choices: choices, overrides: overrides, tag_strategy: "combine"
      )
      # The source model (and with it this verdict row, FK cascade) is gone; MergeHistory is the record.
      @logger.info(
        "[duplicate_triage] merged #{describe(source)} into #{describe(target)} " \
        "confidence=#{confidence} fingerprint=#{fingerprint} reason=#{reason.inspect}"
      )
      :applied
    rescue => error
      @logger.warn("[duplicate_triage] merge failed #{describe(source)} -> #{describe(target)}: #{error.class}: #{error.message}")
      verdict.update(status: :rejected, error: "apply_failed: #{error.class}".truncate(255)) if DuplicatePairVerdict.exists?(verdict.id) # rubocop:disable Pundit/UsePolicyScope -- system apply
      :failed
    end

    # Target wins every field it has; blanks are filled from the source so nothing is lost.
    def merge_choices(target, source)
      choices = FILL_FIELDS.to_h do |key|
        [key, (target.public_send(key).blank? && source.public_send(key).present?) ? "b" : "a"]
      end
      choices["preview"] = (target.preview_file_id.nil? && source.preview_file_id.present?) ? "b" : "a"
      choices["indexable"] = "a"
      choices["sensitive"] = "override"
      [choices, {"sensitive" => (target.sensitive || source.sensitive) ? true : false}]
    end

    def reject(verdict, reason)
      verdict.update!(status: :rejected, error: reason) unless @dry_run
      @logger.info("[duplicate_triage] rejected pair=#{verdict.model_a_id}:#{verdict.model_b_id} #{reason}")
      :rejected
    end

    def track_failures(outcome)
      @failures_in_a_row = (outcome == :failed) ? @failures_in_a_row + 1 : 0
    end

    def describe(model)
      "##{model.id} #{model.path}"
    end
  end
end
