class Scan::CheckModelJob < ApplicationJob
  queue_as :scan
  unique :until_executed

  def perform(model_id, scan_batch_id: nil)
    model = Model.find(model_id)
    # Scan for new files (runs integrity check automatically)
    model.add_new_files_later(
      include_all_subfolders: !model.contains_other_models?,
      scan_batch_id: scan_batch_id
    )
    # Rerun analysis job on individual files
    model.model_files.without_special.each do |file|
      file.analyse_later
    end
  end
end
