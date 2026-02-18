# frozen_string_literal: true

class ClearStuckProblems < ActiveRecord::Migration[7.2]
  def up
    return unless connection.table_exists?(:problems) && connection.column_exists?(:problems, :in_progress)

    connection.execute("UPDATE problems SET in_progress = false")
  rescue => e
    Rails.logger.warn "[DataMigration] #{self.class.name} skipped: #{e.message}"
  end

  def down
    raise ActiveRecord::IrreversibleMigration
  end
end
