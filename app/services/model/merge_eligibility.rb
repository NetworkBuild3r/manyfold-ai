# frozen_string_literal: true

# Application-layer merge targets. Filesystem ancestry is nesting, not eligibility.
# INIT-025/SPEC-005 · ADR D-4 / D-5 (v1 same-pack signals empty).
class Model::MergeEligibility
  # Closed list of signals that may authorize a show-Merge target (ADR D-5).
  # Empty in v1 — spark same_pack, operator pin, and datapackage land later.
  SAME_PACK_SIGNALS = [].freeze

  def self.merge_targets(model)
    new(model).merge_targets
  end

  def self.eligible?(source:, target:)
    new(source).eligible?(target)
  end

  def initialize(model)
    @model = model
  end

  def merge_targets
    same_pack_models & path_parents
  end

  def eligible?(target)
    return false if target.nil?
    return true unless path_parent?(target)

    merge_targets.include?(target)
  end

  private

  def path_parents
    @model.parents
  end

  def path_parent?(target)
    path_parents.include?(target)
  end

  def same_pack_models
    SAME_PACK_SIGNALS
  end
end
