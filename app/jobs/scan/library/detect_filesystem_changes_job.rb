# frozen_string_literal: true

class Scan::Library::DetectFilesystemChangesJob < ApplicationJob
  queue_as :scan
  unique :until_executed, lock_ttl: 2.hours

  def folders_with_changes(library) = detector.folders_with_changes(library)
  def filenames_on_disk(library) = detector.filenames_on_disk(library)
  def known_filenames(library) = detector.known_filenames(library)
  def models_with_new_files(library) = detector.models_with_new_files(library)
  def missing_file_model_paths(library) = detector.missing_file_model_paths(library)

  def perform(library_id)
    library = Library.find(library_id)
    return if Problems::MissingLibrary.detect(library)

    if Model.column_names.include?("scan_started_at")
      Model.where(library_id: library.id)
        .where(scan_started_at: ...1.hour.ago)
        .update_all(scan_started_at: nil) # rubocop:disable Rails/SkipsModelValidations
    end

    new_model_paths = folders_with_changes(library)
    refresh_model_ids = models_with_new_files(library)

    scan_batch_id = SecureRandom.uuid
    status[:step] = "jobs.scan.detect_filesystem_changes.creating_models" # i18n-tasks-use t('jobs.scan.detect_filesystem_changes.creating_models')

    Rails.logger.info(
      "[scan] library=#{library.id} new_models=#{new_model_paths.size} " \
      "refresh_models=#{refresh_model_ids.size} batch=#{scan_batch_id}"
    )

    new_model_paths.each_with_index do |path, index|
      delay = [index * 0.05, 30.0].min.seconds
      library.create_model_from_path_later(path, delay: delay, scan_batch_id: scan_batch_id)
    end

    refresh_model_ids.each_with_index do |model_id, index|
      delay = [index * 0.05, 30.0].min.seconds
      model = Model.find_by(id: model_id)
      next unless model

      model.add_new_files_later(delay: delay, scan_batch_id: scan_batch_id)
    end

    Scan::Library::CheckMissingFilesJob.set(wait: 5.seconds)
      .perform_later(library.id, scan_batch_id: scan_batch_id)
  end

  private

  def detector
    @detector ||= Library::FilesystemChangeDetector.new(status: status)
  end
end
