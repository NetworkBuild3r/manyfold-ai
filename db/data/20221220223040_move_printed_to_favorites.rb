# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class MovePrintedToFavorites < ActiveRecord::Migration[7.0]
  include DataMigrationHelpers

  def up
    return unless table_ready?(:model_files, :printed) && connection.table_exists?(:users)

    ModelFile.reset_column_information
    user = User.first
    return unless user

    safe_model_each(ModelFile) do |file|
      user.favorite(file, scope: :printed) if file.respond_to?(:printed) && file.printed
    end
  rescue => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
    raise ActiveRecord::IrreversibleMigration
  end
end
