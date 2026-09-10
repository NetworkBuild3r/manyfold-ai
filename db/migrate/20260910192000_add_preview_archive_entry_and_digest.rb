# frozen_string_literal: true

# INIT-026/SPEC-002 — ADR D-4 preview source + D-6 optional member digest.
class AddPreviewArchiveEntryAndDigest < ActiveRecord::Migration[8.0]
  def change
    add_reference :models, :preview_archive_entry,
      foreign_key: {to_table: :archive_entries, on_delete: :nullify},
      null: true,
      index: true

    add_column :archive_entries, :digest, :string
  end
end
