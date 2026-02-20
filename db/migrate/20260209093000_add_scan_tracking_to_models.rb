class AddScanTrackingToModels < ActiveRecord::Migration[8.0]
  def change
    add_column :models, :scan_started_at, :datetime
  end
end
