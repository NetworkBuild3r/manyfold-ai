class Scan::Library::DetectFilesystemChangesJob < ApplicationJob
  queue_as :scan
  unique :until_executed

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
      return new_model_folders_streaming(library)
    end

    on_disk = filter_indexable_changes(filenames_on_disk(library)).to_set
    known = known_filenames(library).to_set
    new_files = (on_disk - known).to_a
    status[:step] = "jobs.scan.detect_filesystem_changes.building_folder_list" # i18n-tasks-use t('jobs.scan.detect_filesystem_changes.building_folder_list')
    model_paths_from_file_paths(new_files)
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
    return if library.nil?
    return if Problems::MissingLibrary.detect(library)

    # Only *new* files create/rescan models. Treating missing files as "changes"
    # caused endless re-scan loops of every model with a MissingFile problem.
    new_model_paths = folders_with_changes(library)
    missing_model_paths = missing_file_model_paths(library)

    scan_batch_id = SecureRandom.uuid
    status[:step] = "jobs.scan.detect_filesystem_changes.creating_models" # i18n-tasks-use t('jobs.scan.detect_filesystem_changes.creating_models')

    Rails.logger.info(
      "[scan] library=#{library.id} new_models=#{new_model_paths.size} " \
      "missing_models=#{missing_model_paths.size} batch=#{scan_batch_id}"
    )

    new_model_paths.each do |path|
      library.create_model_from_path_later(path, scan_batch_id: scan_batch_id)
    end

    # Models that lost files (but still exist): cheap problem check only — no re-parse/re-analyse.
    if missing_model_paths.any?
      Model.where(library_id: library.id, path: missing_model_paths).find_each do |model|
        model.check_for_problems_later(delay: 2.seconds)
      end
    end
  end

  private

  def indexable_ext_set
    @indexable_ext_set ||= SupportedMimeTypes.indexable_extensions.map(&:downcase).to_set
  end

  def model_ext_set
    @model_ext_set ||= SupportedMimeTypes.model_extensions.map(&:downcase).to_set
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
    require "find"

    Find.find(root) do |abs|
      # Skip hidden / metadata dirs that often appear on NAS shares
      base = File.basename(abs)
      if File.directory?(abs) && (base.start_with?(".") || base == "#recycle" || base == "@eaDir")
        Find.prune
        next
      end
      next unless File.file?(abs)

      ext = File.extname(abs).delete(".").downcase
      next unless indexable_ext_set.include?(ext)

      rel = abs.delete_prefix(root).delete_prefix(File::SEPARATOR).tr("\\", "/")
      next if rel.blank?
      next if SiteSettings.ignored_file?(rel)

      # thingiverse false-positive: model files under images/
      if model_ext_set.include?(ext) && rel.match?(%r{images/[^/]+\.#{Regexp.escape(ext)}$}i)
        next
      end

      yield rel
    end
  end

  # Discover new model folders WITHOUT a full recursive file walk.
  # Organized libraries are Category/ModelName — shallow dir listings are cheap on NAS/SMB.
  # Full Find.find of multi-TB trees over Docker Desktop + SMB repeatedly crashes the engine.
  def new_model_folders_streaming(library)
    status[:step] = "jobs.scan.detect_filesystem_changes.building_folder_list"
    root = library.path
    return [] unless root.present? && File.directory?(root)

    known_paths = Model.where(library_id: library.id).pluck(:path).to_set
    # Also treat known file-bearing folders as known (path may include nested layouts)
    known_from_files = known_filenames(library).map { |f| File.dirname(f).sub(common_subfolder_matcher, "") }.to_set
    known = known_paths | known_from_files

    new_folders = []
    categories_scanned = 0

    safe_children(root).each do |category|
      cat_abs = File.join(root, category)
      next unless File.directory?(cat_abs)
      categories_scanned += 1

      # Case 1: category itself is a model (files directly under top-level dir)
      if model_dir_has_indexable?(cat_abs) && !known.include?(category)
        new_folders << category
      end

      # Case 2: organized layout Category/ModelName
      safe_children(cat_abs).each do |model_name|
        model_abs = File.join(cat_abs, model_name)
        next unless File.directory?(model_abs)
        rel = File.join(category, model_name).tr("\\", "/")
        next if known.include?(rel)
        next unless model_dir_has_indexable?(model_abs)

        new_folders << rel
      end

      if (categories_scanned % 2).zero?
        Rails.logger.info(
          "[scan] library=#{library.id} categories_scanned=#{categories_scanned} " \
          "new_folders=#{new_folders.size}"
        )
      end
    end

    Rails.logger.info(
      "[scan] library=#{library.id} folder_scan_complete categories=#{categories_scanned} " \
      "new_folders=#{new_folders.size}"
    )
    new_folders
  end

  def safe_children(dir)
    Dir.children(dir).reject { |n| n.start_with?(".") || n == "#recycle" || n == "@eaDir" }
  rescue Errno::EACCES, Errno::ENOENT, Errno::EIO
    []
  end

  # Shallow check: indexable file in model dir OR one common subfolder level (files/, stl/, etc.)
  def model_dir_has_indexable?(abs_dir)
    return false unless File.directory?(abs_dir)

    entries = safe_children(abs_dir)
    entries.each do |name|
      path = File.join(abs_dir, name)
      if File.file?(path)
        ext = File.extname(name).delete(".").downcase
        return true if indexable_ext_set.include?(ext)
      end
    end

    # one level of common subfolders only
    common = ApplicationJob.common_subfolders.keys.map(&:downcase).to_set
    entries.each do |name|
      next unless common.include?(name.downcase)
      sub = File.join(abs_dir, name)
      next unless File.directory?(sub)
      safe_children(sub).each do |fname|
        fpath = File.join(sub, fname)
        next unless File.file?(fpath)
        ext = File.extname(fname).delete(".").downcase
        return true if indexable_ext_set.include?(ext)
      end
    end

    false
  rescue Errno::EACCES, Errno::ENOENT, Errno::EIO
    false
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
