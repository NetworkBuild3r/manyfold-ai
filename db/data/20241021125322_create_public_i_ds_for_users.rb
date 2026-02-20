# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class CreatePublicIDsForUsers < ActiveRecord::Migration[7.1]
  include DataMigrationHelpers

  def up
    return unless table_ready?(:users, :public_id)

    User.reset_column_information
    User.find_each do |u|
      u.save if u.valid?
    end
  rescue => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
    raise ActiveRecord::IrreversibleMigration
  end
end
