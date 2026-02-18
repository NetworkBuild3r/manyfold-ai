# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class BackfillActivitiesAfterUuids < ActiveRecord::Migration[7.1]
  include DataMigrationHelpers

  def up
    return unless connection.table_exists?(:models)

    Model.reset_column_information
    Model.unscoped.limit(20).order(created_at: :desc).each do |model|
      model.send :post_creation_activity if model.federails_actor&.try(:activities)&.empty?
    end
  rescue => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
  end
end
