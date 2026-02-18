# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class MoveScaleFactorIntoNote < ActiveRecord::Migration[7.0]
  include DataMigrationHelpers

  def up
    safe_model_each(Model) do |model|
      if model.respond_to?(:scale_factor) && (model.scale_factor != 100)
        model.update!(notes: [
          model.notes,
          "Scale factor: #{model.scale_factor}%"
        ].compact_blank.join("\n"))
      end
    end
  rescue => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
    raise ActiveRecord::IrreversibleMigration
  end
end
