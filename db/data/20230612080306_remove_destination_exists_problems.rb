# frozen_string_literal: true

class RemoveDestinationExistsProblems < ActiveRecord::Migration[7.0]
  # category enum index for :destination_exists in Problem::CATEGORIES
  DESTINATION_EXISTS_CATEGORY = 2

  def up
    # Clean up deprecated problems (raw SQL to avoid loading Problem model)
    connection.execute("DELETE FROM problems WHERE category = #{DESTINATION_EXISTS_CATEGORY}")
  end

  def down
    raise ActiveRecord::IrreversibleMigration
  end
end
