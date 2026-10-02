# frozen_string_literal: true

module DuplicateTriage
  # D-7: more eligible files wins; tie → older created_at, then lower id.
  module Keeper
    def self.pick(models, file_counts)
      models.min_by { |model| [-file_counts.fetch(model.id, 0), model.created_at, model.id] }
    end
  end
end
