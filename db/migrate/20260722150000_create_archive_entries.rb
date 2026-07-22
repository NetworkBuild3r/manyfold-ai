class CreateArchiveEntries < ActiveRecord::Migration[8.0]
  def change
    create_table :archive_entries do |t|
      t.references :model_file, null: false, foreign_key: {on_delete: :cascade}
      t.string :public_id, null: false
      t.string :pathname, null: false
      t.bigint :size
      t.bigint :compressed_size
      t.string :kind, null: false, default: "other"
      t.string :preview_path
      t.string :extracted_path
      t.string :status, null: false, default: "listed"
      t.text :error_message
      t.timestamps
    end

    add_index :archive_entries, :public_id, unique: true
    add_index :archive_entries, [:model_file_id, :pathname], unique: true
    add_index :archive_entries, [:model_file_id, :kind]
    add_index :archive_entries, [:model_file_id, :status]

    add_column :model_files, :archive_entries_truncated, :boolean, null: false, default: false
    add_column :model_files, :archive_entries_listed_count, :integer, null: false, default: 0
  end
end
