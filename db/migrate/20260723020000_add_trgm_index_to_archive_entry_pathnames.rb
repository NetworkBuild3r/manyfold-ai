# frozen_string_literal: true

class AddTrgmIndexToArchiveEntryPathnames < ActiveRecord::Migration[8.0]
  disable_ddl_transaction!

  def up
    enable_extension "pg_trgm" unless extension_enabled?("pg_trgm")

    add_index :archive_entries, :pathname,
      using: :gin,
      opclass: :gin_trgm_ops,
      name: "index_archive_entries_on_pathname_trgm",
      algorithm: :concurrently,
      if_not_exists: true
  end

  def down
    remove_index :archive_entries,
      name: "index_archive_entries_on_pathname_trgm",
      algorithm: :concurrently,
      if_exists: true
  end
end
