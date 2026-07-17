class Scan::CheckModelJob < ApplicationJob
  queue_as :scan
  unique :until_executed

  # deep: when true, re-run analysis on every file (expensive). Default false —
  # only sync filesystem and re-check problems; analysis runs for *new* files only
  # via Scan::ModelFile::ParseMetadataJob → AnalyseModelFileJob.
  def perform(model_id, scan_batch_id: nil, deep: false)
    model = Model.find(model_id)

    model.add_new_files_later(
      include_all_subfolders: !model.contains_other_models?,
      scan_batch_id: scan_batch_id
    )

    return unless deep

    model.model_files.without_special.find_each do |file|
      file.analyse_later
    end
  end
end
