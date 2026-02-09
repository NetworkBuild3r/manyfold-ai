# frozen_string_literal: true

class ClearStuckProblems < ActiveRecord::Migration[7.2]
  def up
    return unless connection.column_exists?(:problems, :in_progress)
    connection.execute("UPDATE problems SET in_progress = 0")
  end

  def down
    raise ActiveRecord::IrreversibleMigration
  end
end
