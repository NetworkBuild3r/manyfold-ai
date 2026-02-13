# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class AddDefaultAccessControls < ActiveRecord::Migration[7.1]
  include DataMigrationHelpers

  def up
    [Creator, Collection, Model].each do |klass|
      safe_model_each(klass, &:set_owner)
      safe_model_each(klass, &:set_permissions_from_preset)
    end
  rescue StandardError => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
  end
end
