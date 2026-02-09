require "shellwords"

class Scan::Model::AddNewFilesJob < ApplicationJob
  queue_as :scan
  unique :until_executed

  def file_list(model_path, library, include_all_subfolders: false)
    glob = include_all_subfolders ?
      [File.join(Shellwords.escape(model_path), "**", ApplicationJob.file_pattern)] :
      [File.join(Shellwords.escape(model_path), ApplicationJob.file_pattern)] +
        ApplicationJob.common_subfolders.map do |name, pattern|
          File.join(
            Shellwords.escape(model_path),
            ApplicationJob.case_insensitive_glob_string(name),
            pattern
          )
        end
    # datapackage.json is treated as import/export metadata only; it is not a ModelFile.
    library.list_files(glob)
  end

  def perform(model_id, include_all_subfolders: false, scan_batch_id: nil)
    Current.set(scan_batch_id: scan_batch_id) do
      model = Model.find(model_id)
      return if model.remote?
      return if Problems::MissingModel.detect(model)
      # For each file in the model, create a file object
      file_list(model.path, model.library, include_all_subfolders: include_all_subfolders).each do |filename|
        # Create the file
        file = model.model_files.find_or_create_by(filename: filename.gsub(model.path + "/", ""))
        file.parse_metadata_later if file.valid?
      end
      model.parse_metadata_later(scan_batch_id: scan_batch_id)
      Scan::Model::FinalizeScanBatchJob.set(wait: 15.seconds).perform_later(model.id, scan_batch_id: scan_batch_id) if scan_batch_id.present?
    end
  end
end
