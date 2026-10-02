# frozen_string_literal: true

# INIT-031/SPEC-002 — one row per (model pair, evidence fingerprint, source).
# Reversible via `change`. Do not run against a live database from the control node.
class CreateDuplicatePairVerdicts < ActiveRecord::Migration[8.0]
  def change
    create_table :duplicate_pair_verdicts do |t|
      t.references :model_a, null: false, foreign_key: {to_table: :models, on_delete: :cascade}
      t.references :model_b, null: false, foreign_key: {to_table: :models, on_delete: :cascade}
      t.string :fingerprint, null: false, limit: 64
      t.string :source, null: false
      t.string :decision, null: false
      t.string :keeper, null: false
      t.decimal :confidence, precision: 4, scale: 3
      t.string :reason, limit: 500
      t.jsonb :evidence, null: false, default: {}
      t.string :llm_model
      t.string :prompt_version
      t.string :error
      t.references :decided_by, foreign_key: {to_table: :users, on_delete: :nullify}
      t.string :status, null: false, default: "proposed"

      t.timestamps
    end

    add_index :duplicate_pair_verdicts,
      [:model_a_id, :model_b_id, :fingerprint, :source],
      unique: true,
      name: "index_dup_verdicts_on_pair_fingerprint_source"
    add_index :duplicate_pair_verdicts,
      [:status, :decision, :confidence],
      name: "index_dup_verdicts_on_status_decision_confidence"
    add_check_constraint :duplicate_pair_verdicts,
      "model_a_id < model_b_id",
      name: "duplicate_pair_verdicts_model_a_lt_b"
  end
end
