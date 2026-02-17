# frozen_string_literal: true

class RemoveDestinationExistsProblems < ActiveRecord::Migration[7.0]
  # category enum index for :destination_exists in Problem::CATEGORIES
  DESTINATION_EXISTS_CATEGORY = 2

  def up
    return unless connection.table_exists?(:problems) && connection.column_exists?(:problems, :category)

    connection.execute("DELETE FROM problems WHERE category = #{DESTINATION_EXISTS_CATEGORY}")
  rescue StandardError => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
    raise ActiveRecord::IrreversibleMigration
  end
end
