# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class RemoveLeadingSeparatorsFromModelFilenames < ActiveRecord::Migration[7.0]
  include DataMigrationHelpers

  def up
    safe_model_each(Model) do |model|
      newpath = model.path&.trim_path_separators
      model.update!(path: newpath) if newpath != model.path
    rescue ActiveRecord::RecordInvalid
      model.destroy!
    end
  rescue => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
    raise ActiveRecord::IrreversibleMigration
  end
end
