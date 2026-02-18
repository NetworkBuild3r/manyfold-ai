# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class MoveFileDataIntoShrine < ActiveRecord::Migration[7.0]
  include DataMigrationHelpers

  def up
    safe_model_each(ModelFile) { |it| it.attach_existing_file!(refresh: false, skip_validations: true) }
  rescue => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
  end
end
