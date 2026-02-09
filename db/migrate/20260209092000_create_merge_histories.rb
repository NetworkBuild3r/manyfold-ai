class CreateMergeHistories < ActiveRecord::Migration[8.0]
  def change
    create_table :merge_histories do |t|
      t.references :target_model, null: false, foreign_key: {to_table: :models}

      t.bigint :source_library_id, null: false
      t.string :source_path, null: false
      t.string :source_name, null: false

      t.json :source_metadata, null: false, default: {}
      t.json :moved_files, null: false, default: []

      t.datetime :undone_at

      t.timestamps
    end

    add_index :merge_histories, [:target_model_id, :created_at]
  end
end

