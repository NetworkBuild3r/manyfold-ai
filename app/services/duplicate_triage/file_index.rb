# frozen_string_literal: true

module DuplicateTriage
  # Batched digest/filename/size rows plus SUM(size) totals for a pair set.
  # Grouped SQL only — never `ModelFile.all` (INIT-031/SPEC-003, AC6).
  class FileIndex
    Row = Data.define(:model_id, :digest, :filename, :size)

    def self.load(model_ids)
      ids = Array(model_ids).compact.uniq
      return new({}, {}) if ids.empty?

      rows = eligible.where(model_id: ids).pluck(:model_id, :digest, :filename, :size).map do |model_id, digest, filename, size|
        Row.new(model_id:, digest:, filename:, size: size.to_i)
      end
      new(rows.group_by(&:model_id), totals(ids))
    end

    def self.totals(model_ids)
      ids = Array(model_ids).compact.uniq
      return {} if ids.empty?

      ModelFile.where(model_id: ids).group(:model_id).sum(:size) # rubocop:disable Pundit/UsePolicyScope -- system pair evidence
    end

    def self.counts(model_ids)
      ids = Array(model_ids).compact.uniq
      return {} if ids.empty?

      eligible.where(model_id: ids).group(:model_id).count
    end

    def self.eligible
      ModelFile.where.not(digest: [nil, ""]).where(ModelFile.arel_table[:size].gt(0)) # rubocop:disable Pundit/UsePolicyScope -- system pair evidence
    end

    def initialize(rows_by_model_id, totals_by_model_id = {})
      @rows_by_model_id = rows_by_model_id
      @totals_by_model_id = totals_by_model_id
    end

    def rows_for(model_id)
      @rows_by_model_id.fetch(model_id, [])
    end

    def total_bytes_for(model_id)
      @totals_by_model_id.fetch(model_id, 0).to_i
    end
  end
end
