# frozen_string_literal: true

FactoryBot.define do
  factory :duplicate_pair_verdict do
    model_a factory: :model
    model_b factory: :model
    fingerprint { SecureRandom.hex(32) }
    source { :llm }
    decision { :merge }
    keeper { :a }
    confidence { 0.9 }
    reason { "shared files" }
    evidence { {} }
    status { :proposed }

    trait :human do
      source { :human }
      confidence { nil }
      decided_by factory: :user
    end

    trait :deterministic do
      source { :deterministic }
      decision { :keep_separate }
      confidence { 1.0 }
      reason { "nested folder, not a duplicate product" }
    end

    after(:build) do |row|
      next if row.model_a_id.blank? || row.model_b_id.blank?
      next if row.model_a_id < row.model_b_id

      low, high = row.model_b, row.model_a
      row.model_a = low
      row.model_b = high
    end
  end
end
