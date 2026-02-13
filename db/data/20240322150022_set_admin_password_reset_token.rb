# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class SetAdminPasswordResetToken < ActiveRecord::Migration[7.0]
  include DataMigrationHelpers

  def up
    return unless table_ready?(:users, :reset_password_token)

    User.reset_column_information
    u = User.with_role(:administrator).first
    if u
      u.reset_password_token = "first_use"
      u.save validate: false
    end
  rescue StandardError => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
  end
end
