# frozen_string_literal: true

# Application-layer undo of a Model::Merge within UNMERGE_WINDOW.
class Model::Unmerge
  def self.call(target, merge_history, skip_problem_checks: true)
    new(target).call(merge_history, skip_problem_checks: skip_problem_checks)
  end

  def initialize(target)
    @target = target
  end

  def call(merge_history, skip_problem_checks: true)
    history = merge_history.is_a?(MergeHistory) ? merge_history : @target.merge_histories.find(merge_history)
    raise ArgumentError, "merge history does not belong to this model" if history.target_model_id != @target.id
    raise ArgumentError, "merge already undone" if history.undone_at.present?
    raise ArgumentError, "merge is too old to undo" if history.created_at < Model::UNMERGE_WINDOW.ago
    if history.source_library_id.nil?
      raise ActiveRecord::RecordNotFound,
        "Cannot unmerge: source library no longer exists (was deleted after merge)"
    end

    ActiveRecord::Base.transaction do
      @target.skip_problem_check = true if skip_problem_checks
      library = Library.find(history.source_library_id) # rubocop:disable Pundit/UsePolicyScope -- internal unmerge
      source_meta = history.source_metadata || {}

      new_path = history.source_path
      if library.models.exists?(path: new_path.trim_path_separators)
        new_path = "#{new_path.trim_path_separators}--unmerged-#{history.id}"
      end

      creator = Creator.find_by(id: source_meta["creator_id"])
      collection = Collection.find_by(id: source_meta["collection_id"])

      new_model = library.models.new(
        name: history.source_name,
        path: new_path.trim_path_separators,
        creator_id: creator&.id,
        collection_id: collection&.id,
        license: source_meta["license"],
        caption: source_meta["caption"],
        notes: source_meta["notes"],
        sensitive: source_meta["sensitive"]
      )
      new_model.suppress_announce = true if new_model.respond_to?(:suppress_announce=)
      new_model.skip_problem_check = true if skip_problem_checks
      new_model.save!

      new_model.tag_list = Array(source_meta["tag_list"])
      new_model.links_attributes = Array(source_meta["links"]).map { |url| {url: url} }
      new_model.skip_problem_check = true if skip_problem_checks
      new_model.save!

      Array(history.moved_files).each do |entry|
        file_id = entry["id"] || entry[:id]
        source_filename = entry["source_filename"] || entry[:source_filename]
        was_deduplicated = entry["deduplicated"] || entry[:deduplicated]

        if was_deduplicated
          existing_id = entry["existing_file_id"] || entry[:existing_file_id]
          existing_file = ModelFile.find_by(id: existing_id)
          next unless existing_file && source_filename.present?

          new_file = new_model.model_files.create!(
            filename: source_filename,
            digest: existing_file.digest,
            size: existing_file.size,
            presupported: existing_file.presupported,
            y_up: existing_file.y_up,
            previewable: existing_file.previewable
          )
          @target.copy_file_to_model_file_for_unmerge(existing_file, new_file)
        else
          file = ModelFile.find_by(id: file_id)
          next unless file && source_filename.present?

          file.filename = source_filename
          new_model.adopt_file(file)
        end
      end

      if (preview_filename = history.source_preview_filename)
        preview = new_model.model_files.find_by(filename: preview_filename)
        new_model.update!(preview_file: preview) if preview
      end

      history.update!(undone_at: Time.current)
      new_model
    end
  end
end
