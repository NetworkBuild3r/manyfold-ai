# frozen_string_literal: true

class AddDatabaseIntegrityConstraints < ActiveRecord::Migration[8.0]
  def change
    # --- Allow NULL for merge_histories.source_library_id ---
    # Required for FK with on_delete: :nullify (when library is deleted, we nullify rather than cascade)
    change_column_null :merge_histories, :source_library_id, true

    # --- Foreign keys ---

    # merge_histories.source_library_id → libraries
    # Prevents: unmerge crash when library was deleted.
    # on_delete: :nullify — prefer unmergeable history over cascade-deleting histories when library removed
    add_foreign_key :merge_histories, :libraries,
      column: :source_library_id,
      on_delete: :nullify,
      if_not_exists: true

    # models.preview_file_id → model_files
    # Prevents: model referencing a deleted file as its preview.
    # on_delete: :nullify — deleting a file clears the preview, not the model
    add_foreign_key :models, :model_files,
      column: :preview_file_id,
      on_delete: :nullify,
      if_not_exists: true

    # memberships.group_id → groups
    add_foreign_key :memberships, :groups,
      on_delete: :cascade,
      if_not_exists: true

    # memberships.user_id → users
    add_foreign_key :memberships, :users,
      on_delete: :cascade,
      if_not_exists: true

    # users_roles.user_id → users
    add_foreign_key :users_roles, :users,
      on_delete: :cascade,
      if_not_exists: true

    # users_roles.role_id → roles
    add_foreign_key :users_roles, :roles,
      on_delete: :cascade,
      if_not_exists: true

    # --- Indexes ---

    # libraries.path — uniqueness at DB level; validation does full table scan without it.
    # Migration 20240703160732 removed this index; re-adding for integrity. If case-sensitivity
    # or path normalization causes issues, consider a non-unique index instead.
    add_index :libraries, :path, unique: true, if_not_exists: true

    # merge_histories.source_library_id — unmerge looks up by this
    add_index :merge_histories, :source_library_id, if_not_exists: true
  end
end
