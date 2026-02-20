# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class ConvertAdminFlagToRole < ActiveRecord::Migration[7.0]
  include DataMigrationHelpers

  def up
    return unless connection.column_exists?(:users, :admin)

    User.reset_column_information
    User.where(admin: true).find_each { |u| u.add_role :administrator }
  rescue => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
    User.with_role(:administrator).find_each { |u| u.update!(admin: true) }
  end
end
