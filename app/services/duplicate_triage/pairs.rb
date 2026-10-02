# frozen_string_literal: true

module DuplicateTriage
  # Cross-model pairs from shared non-empty digests. Groups of 3+ models are
  # starred against one D-7 keeper so approvals cannot chain (INIT-031/SPEC-003).
  class Pairs
    include Enumerable

    Pair = Data.define(:model_a, :model_b, :keeper) do
      def keeper_side
        (keeper.id == model_a.id) ? :a : :b
      end
    end

    def self.each(limit: nil, &block)
      new(limit: limit).each(&block)
    end

    def initialize(limit: nil)
      @limit = limit
    end

    def each
      return enum_for(:each) unless block_given?

      built = build_pairs
      built = built.first(@limit) if @limit
      built.each { |pair| yield pair }
    end

    private

    def build_pairs
      groups = model_ids_by_digest.values.map(&:uniq).select { |ids| ids.size >= 2 }
      return [] if groups.empty?

      model_ids = groups.flatten.uniq
      models = load_models(model_ids)
      counts = FileIndex.counts(model_ids)
      pair_keepers = {}

      groups.sort_by { |ids| -ids.size }.each do |ids|
        members = ids.filter_map { |id| models[id] }
        next if members.size < 2

        keeper = Keeper.pick(members, counts)
        (members - [keeper]).each do |other|
          key = [keeper.id, other.id].minmax
          pair_keepers[key] ||= keeper
        end
      end

      pair_keepers.filter_map do |(low_id, high_id), keeper|
        low = models[low_id]
        high = models[high_id]
        next unless low && high

        Pair.new(model_a: low, model_b: high, keeper: keeper)
      end.sort_by { |pair| [pair.model_a.id, pair.model_b.id] }
    end

    def model_ids_by_digest
      rows = eligible_files.where(digest: multi_model_digests).distinct.pluck(:digest, :model_id)
      rows.each_with_object(Hash.new { |hash, key| hash[key] = [] }) do |(digest, model_id), memo|
        memo[digest] << model_id
      end
    end

    def multi_model_digests
      eligible_files.group(:digest).having("COUNT(DISTINCT model_id) >= 2").select(:digest)
    end

    def eligible_files
      FileIndex.eligible
    end

    def load_models(model_ids)
      Model.where(id: model_ids).includes(:creator).index_by(&:id) # rubocop:disable Pundit/UsePolicyScope -- system pair enumeration
    end
  end
end
