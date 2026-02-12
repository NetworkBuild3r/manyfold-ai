class AddStateToProblems < ActiveRecord::Migration[8.0]
  def change
    add_column :problems, :state, :integer, null: false, default: 0
    add_index :problems, :state
  end
end
