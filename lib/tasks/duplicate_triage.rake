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
  end
end
