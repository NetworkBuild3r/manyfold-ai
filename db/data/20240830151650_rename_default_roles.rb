# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class RenameDefaultRoles < ActiveRecord::Migration[7.1]
  include DataMigrationHelpers

  def up
    return unless connection.table_exists?(:roles)

    Role.reset_column_information
    Role.find_by(name: :editor)&.update!(name: :moderator) unless Role.find_by(name: :moderator)
    Role.find_by(name: :viewer)&.update!(name: :member) unless Role.find_by(name: :member)
  rescue StandardError => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
    Role.find_by(name: :moderator)&.update!(name: :editor)
    Role.find_by(name: :member)&.update!(name: :viewer)
  end
end
