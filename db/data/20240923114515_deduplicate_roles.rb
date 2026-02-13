# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class DeduplicateRoles < ActiveRecord::Migration[7.1]
  include DataMigrationHelpers

  def up
    return unless connection.table_exists?(:roles)
    return unless Role.respond_to?(:merge_duplicates!)

    Role.reset_column_information
    Role.merge_duplicates!
  rescue StandardError => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
  end
end
