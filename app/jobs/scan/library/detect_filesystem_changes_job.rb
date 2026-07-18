# frozen_string_literal: true

require "set"

class Scan::Library::DetectFilesystemChangesJob < ApplicationJob
  queue_as :scan
  unique :until_executed, lock_ttl: 2.hours

  DEFAULT_MAX_DEPTH = 6

  # Find all indexable files currently on disk under the library root.
  # Prefer streaming Find for local/NAS filesystem libraries — Dir.glob("**/*")
  # on multi-thousand-model network mounts can exhaust memory and crash Docker.
  def filenames_on_disk(library)
    if library.storage_service == "filesystem"
      stream_indexable_relative_paths(library).to_a
    else
      library.list_files(File.join("**", ApplicationJob.file_pattern))
    end
  end

  # Known library-relative paths from the DB (no full AR + attachment JSON load).
  def known_filenames(library)
    ModelFile.without_special
      .joins(:model)
      .where(models: {library_id: library.id})
      .pluck("models.path", "model_files.filename")
      .map { |model_path, filename| File.join(model_path, filename) }
  end

  def filter_out_common_subfolders(folders)
    matcher = /\/(#{ApplicationJob.common_subfolders.keys.join("|")})$/i
    folders.map { |f| f.gsub(matcher, "") }.uniq
  end

  def model_paths_from_file_paths(file_paths)
    folders = file_paths.map { |f| File.dirname(f) }.uniq
    folders = filter_out_common_subfolders(folders)
    folders.delete("/")
    folders.delete(".")
    folders.delete("./")
    folders.compact_blank
  end

  # Discard thingiverse false-positives (model-ext files dumped under images/).
  def filter_indexable_changes(paths)
    paths = paths.select { |f|
      SupportedMimeTypes.indexable_extensions.include?(File.extname(f).tr(".", "").downcase)
    }
    patterns = SupportedMimeTypes.model_extensions.map { |it| %r{images/[^/]*\.#{it}}i }
    paths.reject { |f| patterns.any? { |pat| f.match?(pat) } }
  end

  # Model folder paths that have *new* files on disk (not yet in the DB).
  # Specs and callers use this; missing files are handled separately in #perform.
  def folders_with_changes(library)
    status[:step] = "jobs.scan.detect_filesystem_changes.building_filename_list" # i18n-tasks-use t('jobs.scan.detect_filesystem_changes.building_filename_list')

    if library.storage_service == "filesystem"
      return discover_new_model_dirs(library)
    end

    on_disk = filter_indexable_changes(filenames_on_disk(library)).to_set
    known = known_filenames(library).to_set
    new_files = (on_disk - known).to_a
    status[:step] = "jobs.scan.detect_filesystem_changes.building_folder_list" # i18n-tasks-use t('jobs.scan.detect_filesystem_changes.building_folder_list')
    model_paths_from_file_paths(new_files)
  end

  # Known model IDs that gained new indexable files on disk (shallow check).
  def models_with_new_files(library)
    return [] unless library.storage_service == "filesystem"

    root = library.path
    return [] unless root.present? && File.directory?(root)

    status[:step] = "jobs.scan.detect_filesystem_changes.checking_known_models"
    changed_ids = []
    Model.where(library_id: library.id).find_each do |model|
      abs = File.join(root, model.path)
      next unless File.directory?(abs)
      next if File.symlink?(abs)

      on_disk = shallow_indexable_relative_names(abs)
      existing = model.model_files.without_special.pluck(:filename).to_set
      changed_ids << model.id if (on_disk - existing).any?
    end
    changed_ids
  end

  # Only probe files already registered in the DB — do not re-walk the entire tree.
  def missing_file_model_paths(library)
    if library.storage_service == "filesystem"
      return missing_model_paths_from_known_files(library)
    end

    on_disk = filter_indexable_changes(filenames_on_disk(library)).to_set
    known = known_filenames(library).to_set
    missing_files = (known - on_disk).to_a
    model_paths_from_file_paths(missing_files)
  end

  def perform(library_id)
    library = Library.find(library_id)
    return if Problems::MissingLibrary.detect(library)

    # Clear stuck scan banners from prior crashed jobs.
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

    # Stagger fan-out so Redis + NFS are not hit by thousands of CreateModel jobs
    # in the same second. Cap at 30s so the tail is not delayed forever.
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

    # Missing-file checks run in a follow-up job so Detect stays responsive on large libs.
    Scan::Library::CheckMissingFilesJob.set(wait: 5.seconds)
      .perform_later(library.id, scan_batch_id: scan_batch_id)
  end

  private

  def max_depth
    Integer(ENV.fetch("SCAN_MAX_DEPTH", DEFAULT_MAX_DEPTH))
  rescue ArgumentError, TypeError
    DEFAULT_MAX_DEPTH
  end

  def indexable_ext_set
    @indexable_ext_set ||= SupportedMimeTypes.indexable_extensions.map(&:downcase).to_set
  end

  def model_ext_set
    @model_ext_set ||= SupportedMimeTypes.model_extensions.map(&:downcase).to_set
  end

  def common_dir_names
    @common_dir_names ||= ApplicationJob.common_subfolders.keys.map(&:downcase).to_set
  end

  def common_subfolder_matcher
    @common_subfolder_matcher ||= /\/(#{ApplicationJob.common_subfolders.keys.join("|")})$/i
  end

  # Stream absolute paths under the library and yield library-relative indexable file paths.
  def stream_indexable_relative_paths(library)
    return enum_for(:stream_indexable_relative_paths, library) unless block_given?

    root = library.path
    return unless root.present? && File.directory?(root)

    root = File.expand_path(root)
    root_real = safe_realpath(root) || root
    require "find"

    Find.find(root) do |abs|
      base = File.basename(abs)
      if File.directory?(abs)
        if base.start_with?(".") || base == "#recycle" || base == "@eaDir" || File.symlink?(abs)
          Find.prune
          next
        end
        next
      end
      next unless File.file?(abs)
      next if File.symlink?(abs) && !path_inside_root?(abs, root_real)

      unless path_inside_root?(abs, root_real)
        next
      end

      ext = File.extname(abs).delete(".").downcase
      next unless indexable_ext_set.include?(ext)

      rel = abs.delete_prefix(root).delete_prefix(File::SEPARATOR).tr("\\", "/")
      next if rel.blank?
      next if SiteSettings.ignored_file?(rel)

      if model_ext_set.include?(ext) && rel.match?(%r{images/[^/]+\.#{Regexp.escape(ext)}$}i)
        next
      end

      yield rel
    end
  end

  # Discover new model folders with bounded DFS — no full-tree file list in memory.
  # Prunes known model paths; still recurses into dirs that themselves look like models
  # so nested models (model/nested/) are found.
  def discover_new_model_dirs(library)
    status[:step] = "jobs.scan.detect_filesystem_changes.building_folder_list"
    root = library.path
    return [] unless root.present? && File.directory?(root)

    root = File.expand_path(root)
    root_real = safe_realpath(root) || root

    known_paths = Model.where(library_id: library.id).pluck(:path).to_set
    known_from_files = known_filenames(library).map { |f| File.dirname(f).sub(common_subfolder_matcher, "") }.to_set
    known = known_paths | known_from_files

    new_folders = []
    visit_for_new_models(
      abs: root,
      rel: "",
      depth: 0,
      root_real: root_real,
      known: known,
      new_folders: new_folders,
      library_id: library.id
    )

    Rails.logger.info(
      "[scan] library=#{library.id} folder_scan_complete " \
      "new_folders=#{new_folders.size} max_depth=#{max_depth}"
    )
    new_folders
  end

  def visit_for_new_models(abs:, rel:, depth:, root_real:, known:, new_folders:, library_id:)
    return if depth > max_depth
    return unless File.directory?(abs)
    return if File.symlink?(abs)

    # Already indexed as a model — file deltas handled separately; do not walk children for new folders.
    if rel.present? && known.include?(rel)
      return
    end

    if rel.present? && model_dir_has_indexable?(abs) && !known.include?(rel)
      new_folders << rel
    end

    return if depth == max_depth

    safe_children(abs).each do |name|
      next if common_dir_names.include?(name.downcase)

      child_abs = File.join(abs, name)
      next unless File.directory?(child_abs)
      next if File.symlink?(child_abs)
      next unless path_inside_root?(child_abs, root_real)

      child_rel = rel.present? ? File.join(rel, name).tr("\\", "/") : name
      visit_for_new_models(
        abs: child_abs,
        rel: child_rel,
        depth: depth + 1,
        root_real: root_real,
        known: known,
        new_folders: new_folders,
        library_id: library_id
      )
    end

    if (new_folders.size % 50).zero? && new_folders.any?
      Rails.logger.info(
        "[scan] library=#{library_id} discovering depth=#{depth} new_folders=#{new_folders.size}"
      )
    end
  end

  def safe_children(dir)
    Dir.children(dir).reject { |n| n.start_with?(".") || n == "#recycle" || n == "@eaDir" }
  rescue Errno::EACCES, Errno::ENOENT, Errno::EIO
    []
  end

  def safe_realpath(path)
    File.realpath(path)
  rescue Errno::ENOENT, Errno::EACCES, Errno::EIO, Errno::ELOOP
    nil
  end

  def path_inside_root?(abs, root_real)
    real = safe_realpath(abs)
    return false if real.nil?

    real == root_real || real.start_with?(root_real + File::SEPARATOR)
  end

  # Shallow indexable filenames relative to a model directory (incl. one common-subfolder level).
  def shallow_indexable_relative_names(abs_dir)
    names = []
    safe_children(abs_dir).each do |name|
      path = File.join(abs_dir, name)
      if File.file?(path) && !File.symlink?(path)
        ext = File.extname(name).delete(".").downcase
        names << name if indexable_ext_set.include?(ext)
      elsif File.directory?(path) && !File.symlink?(path) && common_dir_names.include?(name.downcase)
        safe_children(path).each do |fname|
          fpath = File.join(path, fname)
          next unless File.file?(fpath) && !File.symlink?(fpath)

          ext = File.extname(fname).delete(".").downcase
          names << File.join(name, fname) if indexable_ext_set.include?(ext)
        end
      end
    end
    names.to_set
  rescue Errno::EACCES, Errno::ENOENT, Errno::EIO
    Set.new
  end

  # Shallow check: indexable file in model dir OR one common subfolder level (files/, stl/, etc.)
  def model_dir_has_indexable?(abs_dir)
    return false unless File.directory?(abs_dir)
    return false if File.symlink?(abs_dir)

    shallow_indexable_relative_names(abs_dir).any?
  end

  # Check only DB-known files for disappearance (O(known files), not O(disk)).
  def missing_model_paths_from_known_files(library)
    root = library.path
    return [] unless root.present?

    missing = []
    known_filenames(library).each do |rel|
      abs = File.join(root, rel)
      missing << rel unless File.file?(abs)
    end
    model_paths_from_file_paths(missing)
  end
end
