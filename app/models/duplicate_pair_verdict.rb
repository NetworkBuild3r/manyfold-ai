# frozen_string_literal: true

# System table: current verdict for a pair is the matching-fingerprint row with
# source precedence human > llm > deterministic (INIT-031/SPEC-002, D-5, D-6).
class DuplicatePairVerdict < ApplicationRecord
  SOURCES = {
    deterministic: "deterministic",
    llm: "llm",
    human: "human"
  }.freeze

  DECISIONS = {
    merge: "merge",
    keep_separate: "keep_separate",
    unsure: "unsure"
  }.freeze

  KEEPERS = {
    a: "a",
    b: "b"
  }.freeze

  STATUSES = {
    proposed: "proposed",
    approved: "approved",
    applied: "applied",
    rejected: "rejected"
  }.freeze

  SOURCE_PRECEDENCE = {"human" => 0, "llm" => 1, "deterministic" => 2}.freeze

  belongs_to :model_a, class_name: "Model"
  belongs_to :model_b, class_name: "Model"
  belongs_to :decided_by, class_name: "User", optional: true

  enum :source, SOURCES, validate: true
  enum :decision, DECISIONS, validate: true
  enum :keeper, KEEPERS, prefix: :keeper, validate: true
  enum :status, STATUSES, default: :proposed, validate: true

  validates :fingerprint, presence: true, length: {maximum: 64}
  validates :reason, length: {maximum: 500}, allow_nil: true
  validates :confidence, numericality: {greater_than_or_equal_to: 0, less_than_or_equal_to: 1}, allow_nil: true
  validates :model_a_id, numericality: {less_than: :model_b_id}, if: -> { model_a_id.present? && model_b_id.present? }

  scope :pending_review, -> { where(status: :proposed) }
  scope :in_band, ->(range) { where(confidence: range) }

  def self.current_for(model_a, model_b, fingerprint)
    a_id, b_id = [id_of(model_a), id_of(model_b)].minmax
    matches = where(model_a_id: a_id, model_b_id: b_id, fingerprint: fingerprint).to_a # rubocop:disable Pundit/UsePolicyScope -- system current-verdict lookup
    matches.min_by { |row| [SOURCE_PRECEDENCE.fetch(row.source, 99), -row.created_at.to_f] }
  end

  def self.id_of(model_or_id)
    model_or_id.respond_to?(:id) ? model_or_id.id : model_or_id
  end
  private_class_method :id_of
end
