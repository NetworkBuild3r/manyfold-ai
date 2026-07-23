# frozen_string_literal: true

class EnablePgTrgmSearchIndexes < ActiveRecord::Migration[8.0]
  disable_ddl_transaction!

  def up
    enable_extension "pg_trgm" unless extension_enabled?("pg_trgm")
    enable_extension "fuzzystrmatch" unless extension_enabled?("fuzzystrmatch")

    add_index :models, :name,
      using: :gin,
      opclass: :gin_trgm_ops,
      name: "index_models_on_name_trgm",
      algorithm: :concurrently,
      if_not_exists: true

    add_index :models, :path,
      using: :gin,
      opclass: :gin_trgm_ops,
      name: "index_models_on_path_trgm",
      algorithm: :concurrently,
      if_not_exists: true
  end

  def down
    remove_index :models, name: "index_models_on_name_trgm", algorithm: :concurrently, if_exists: true
    remove_index :models, name: "index_models_on_path_trgm", algorithm: :concurrently, if_exists: true
    # Leave extensions installed — other objects may depend on them.
  end
end
