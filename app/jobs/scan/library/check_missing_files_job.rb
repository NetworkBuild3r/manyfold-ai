# frozen_string_literal: true

require "set"

# Follow-up from DetectFilesystemChangesJob: check DB-known files for disappearance
# without blocking discovery fan-out on large libraries.
class Scan::Library::CheckMissingFilesJob < ApplicationJob
  queue_as :scan
  unique :until_executed, lock_ttl: 30.minutes

  BATCH_SIZE = 500

  def perform(library_id, scan_batch_id: nil, offset: 0)
    library = Library.find(library_id)
    return if Problems::MissingLibrary.detect(library)

    root = library.path
    return unless root.present?

    rows = ModelFile.without_special
      .joins(:model)
      .where(models: {library_id: library.id})
      .order("model_files.id")
      .offset(offset)
      .limit(BATCH_SIZE)
      .pluck("model_files.id", "models.path", "model_files.filename", "models.id")

    return if rows.empty?

    missing_model_ids = Set.new
    rows.each do |_file_id, model_path, filename, model_id|
      abs = File.join(root, model_path, filename)
      missing_model_ids << model_id unless File.file?(abs)
    end

    Model.where(id: missing_model_ids.to_a).find_each do |model|
      Scan::Model::CheckForProblemsJob.perform_later(model.id, light: true)
    end

    if rows.size == BATCH_SIZE
      self.class.set(wait: 2.seconds).perform_later(
        library_id,
        scan_batch_id: scan_batch_id,
        offset: offset + BATCH_SIZE
      )
    end
  end
end
