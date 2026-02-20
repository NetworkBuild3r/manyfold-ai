# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class AddNewDefaultsToRendererSettings < ActiveRecord::Migration[7.0]
  include DataMigrationHelpers

  def up
    return unless table_ready?(:users, :renderer_settings)

    User.reset_column_information
    User.find_each do |user|
      user.update(
        renderer_settings: SiteSettings::UserDefaults::RENDERER.merge(user.renderer_settings)
      )
    end
  rescue => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
    raise ActiveRecord::IrreversibleMigration
  end
end
