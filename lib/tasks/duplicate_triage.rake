# frozen_string_literal: true

namespace :manyfold do
  namespace :duplicate_triage do
    desc "Print evidence JSON for N cross-model duplicate pairs (read-only; INIT-031/SPEC-003)"
    task :evidence, [:limit] => :environment do |_task, args|
      limit = Integer(args[:limit].presence || 10)
      pairs = DuplicateTriage::Pairs.new(limit: limit).to_a
      index = DuplicateTriage::FileIndex.load(pairs.flat_map { |pair| [pair.model_a.id, pair.model_b.id] }.uniq)
      payload = pairs.map { |pair|
        evidence = DuplicateTriage::Evidence.build(pair.model_a, pair.model_b, files: index)
        {
          model_a_id: pair.model_a.id,
          model_b_id: pair.model_b.id,
          keeper: pair.keeper_side.to_s
        }.merge(evidence.to_prompt_h)
      }
      puts JSON.pretty_generate(payload) # rubocop:disable Rails/Output -- operator dry-run
    end

    desc "Enqueue the LLM judge job (optional limit). INIT-031/SPEC-004"
    task :judge, [:limit] => :environment do |_task, args|
      limit = args[:limit].presence
      if limit
        DuplicateTriage::JudgeJob.perform_later(Integer(limit))
      else
        DuplicateTriage::JudgeJob.perform_later
      end
      puts "enqueued DuplicateTriage::JudgeJob limit=#{limit.inspect}" # rubocop:disable Rails/Output -- operator enqueue
    end

    desc "Print a stratified calibration sample. INIT-031/SPEC-004"
    task :sample, [:n] => :environment do |_task, args|
      limit = Integer(args[:n].presence || 20)
      payload = DuplicateTriage::CalibrationSample.call(limit)
      puts JSON.pretty_generate(payload) # rubocop:disable Rails/Output -- operator sample
    end

    desc "Probe vLLM throughput from an evidence JSON file (no database). INIT-031/SPEC-004"
    task :probe, [:path, :n] do |_task, args|
      require_relative "duplicate_triage_probe"
      path = args[:path]
      path = ENV["DUPLICATE_TRIAGE_EVIDENCE_FILE"] if path.nil? || path.to_s.empty?
      raise "pass path or DUPLICATE_TRIAGE_EVIDENCE_FILE" if path.nil? || path.to_s.empty?

      count = args[:n]
      count = DuplicateTriage::ThroughputProbe::DEFAULT_COUNT if count.nil? || count.to_s.empty?
      DuplicateTriage::ThroughputProbe.run(evidence_path: path, count: Integer(count))
    end
  end
end
