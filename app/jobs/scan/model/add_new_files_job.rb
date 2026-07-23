require "shellwords"
require "find"
require "set"

class Scan::Model::AddNewFilesJob < ApplicationJob
  queue_as :scan
  unique :until_executed, lock_ttl: 30.minutes

  def file_list(model_path, library, include_all_subfolders: false)
    if library.storage_service == "filesystem"
      return filesystem_file_list(model_path, library, include_all_subfolders: include_all_subfolders)
    end

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

      prefix = model.path + "/"
      on_disk = file_list(model.path, model.library, include_all_subfolders: include_all_subfolders)
        .map { |filename| filename.delete_prefix(prefix).delete_prefix(model.path) }
        .map { |filename| filename.sub(%r{\A/}, "") }
      on_disk_set = on_disk.to_set

      # Existing filenames from DB (one query)
      existing_names = model.model_files.without_special.pluck(:filename).to_set

      created = 0
      # Only create + parse *new* files. Re-parsing every file on every scan is what
      # made rescan unusable on large libraries.
      on_disk.each do |filename|
        next if existing_names.include?(filename)

        file = model.model_files.create(filename: filename)
        if file.persisted?
          created += 1
          # Thread scan_batch_id so ParseMetadata can skip AnalyseModelFileJob
          # during library discovery (see SCAN_DEFER_ANALYSIS).
          file.parse_metadata_later(scan_batch_id: scan_batch_id)
        end
      end

      # Files in DB but gone from disk — leave records; CheckForProblems raises MissingFile.
      gone = (existing_names - on_disk_set).size

      Rails.logger.info(
        "[scan] model=#{model.id} on_disk=#{on_disk.size} existing=#{existing_names.size} " \
        "created=#{created} missing=#{gone} batch=#{scan_batch_id}"
      )

      # Model-level metadata (preview, path tags, README) then finalize → problems
      model.parse_metadata_later(scan_batch_id: scan_batch_id)
    end
  rescue StandardError
    clear_scan_started_at!(model_id)
    raise
  end

  private

  def filesystem_file_list(model_path, library, include_all_subfolders:)
    root = library.path
    abs = File.join(root, model_path)
    return [] unless root.present? && File.directory?(abs)

    indexable = SupportedMimeTypes.indexable_extensions.map(&:downcase).to_set
    common = ApplicationJob.common_subfolders.keys.map(&:downcase).to_set
    results = []

    if include_all_subfolders
      # Stream Find instead of Dir.glob("**") — avoids memory bombs on deep NFS trees.
      Find.find(abs) do |path|
        base = File.basename(path)
        if File.directory?(path)
          Find.prune if base.start_with?(".") || base == "#recycle" || base == "@eaDir" || File.symlink?(path)
          next
        end
        next unless File.file?(path) && !File.symlink?(path)

        ext = File.extname(path).delete(".").downcase
        next unless indexable.include?(ext)

        rel = path.delete_prefix(root).delete_prefix(File::SEPARATOR).tr("\\", "/")
        next if rel.blank? || SiteSettings.ignored_file?(rel)
        next if File.basename(rel).casecmp("datapackage.json").zero?

        results << rel
      end
    else
      # Shallow: model dir + one common-subfolder level (same shape as Detect).
      Dir.children(abs).each do |name|
        next if name.start_with?(".")

        child = File.join(abs, name)
        if File.file?(child) && !File.symlink?(child)
          ext = File.extname(name).delete(".").downcase
          next unless indexable.include?(ext)
          next if name.casecmp("datapackage.json").zero?

          results << File.join(model_path, name)
        elsif File.directory?(child) && !File.symlink?(child) && common.include?(name.downcase)
          Dir.children(child).each do |fname|
            next if fname.start_with?(".")

            fpath = File.join(child, fname)
            next unless File.file?(fpath) && !File.symlink?(fpath)

            ext = File.extname(fname).delete(".").downcase
            next unless indexable.include?(ext)

            results << File.join(model_path, name, fname)
          end
        end
      rescue Errno::EACCES, Errno::ENOENT, Errno::EIO
        next
      end
    end

    results
  rescue Errno::EACCES, Errno::ENOENT, Errno::EIO
    []
  end

  def clear_scan_started_at!(model_id)
    return unless Model.column_names.include?("scan_started_at")

    Model.where(id: model_id).where.not(scan_started_at: nil)
      .update_all(scan_started_at: nil) # rubocop:disable Rails/SkipsModelValidations
  rescue ActiveRecord::StatementInvalid, ActiveRecord::RecordNotFound
    nil
  end
end
