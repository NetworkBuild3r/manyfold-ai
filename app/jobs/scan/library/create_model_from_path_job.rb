class Scan::Library::CreateModelFromPathJob < ApplicationJob
  queue_as :scan
  unique :until_executed

  def perform(library_id, path, include_all_subfolders: false, scan_batch_id: nil)
    library = Library.find(library_id)
    return if library.nil?
    new_model_properties = {
      # Initial best guess at name, this might be overwritten later by path parser
      name: File.basename(path).humanize.tr("+", " ").careful_titleize,
      tag_list: Array(SiteSettings.model_tags_auto_tag_new)
    }
    # Current.scan_batch_id suppresses Activity/Federails publish callbacks
    # and problem-check storms during bulk discovery.
    model = Current.set(scan_batch_id: scan_batch_id) do
      library.models.create_with(new_model_properties).find_or_create_by(path: path.trim_path_separators)
    end
    if model.valid?
      model.add_new_files_later(include_all_subfolders: include_all_subfolders, scan_batch_id: scan_batch_id)
    else
      Rails.logger.error(model.inspect)
      Rails.logger.error(model.errors.full_messages.inspect)
    end
  end
end
