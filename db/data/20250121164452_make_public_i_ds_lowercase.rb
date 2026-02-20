# frozen_string_literal: true

require File.expand_path("../../lib/data_migration_helpers", __dir__)

class MakePublicIDsLowercase < ActiveRecord::Migration[7.2]
  include DataMigrationHelpers

  MODELS = [Collection, Comment, Creator, Library, ModelFile, Model, User].freeze

  def up
    MODELS.each do |klass|
      next unless table_ready?(klass.table_name.to_sym, :public_id)

      klass.update_all("public_id = lower(public_id)") # rubocop:disable Rails/SkipsModelValidations
    end
    return unless connection.table_exists?(:problems) && connection.column_exists?(:problems, :public_id)

    connection.execute("UPDATE problems SET public_id = lower(public_id)")
  rescue => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
  end
end
