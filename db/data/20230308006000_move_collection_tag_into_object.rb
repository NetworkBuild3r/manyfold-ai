# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class MoveCollectionTagIntoObject < ActiveRecord::Migration[7.0]
  include DataMigrationHelpers

  def up
    return unless connection.table_exists?(:models) && connection.table_exists?(:collections)

    safe_model_each(Model) do |model|
      next unless model.respond_to?(:collections) && !model.collection

      model.collections.each do |collection|
        newcol = Collection.find_or_create_by(name: collection.name)
        newcol.models << model
        newcol.save
      end
    end
  rescue => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
    raise ActiveRecord::IrreversibleMigration
  end
end
