# frozen_string_literal: true

class ProcessUploadedFileJob < ApplicationJob
  queue_as :critical

  def perform(library_id, uploaded_file, name: nil, owner: nil, owner_id: nil, creator_id: nil, collection_id: nil, tag_list: nil, license: nil, model: nil, model_id: nil, sensitive: nil, permission_preset: nil)
    owner = resolve_owner(owner, owner_id)
    model = resolve_model(model, model_id)
    new_files = []
    new_model = model.nil?
    attachers = []

    ActiveRecord::Base.transaction do
      library = Library.find(library_id)
      return if library.nil?

      attachers = Array.wrap(uploaded_file).map do |it|
        attacher = ModelFileUploader::Attacher.new
        attacher.attach_cached(it)
        attacher
      end

      name ||= File.basename(attachers.first.file.original_filename, ".*").humanize.tr("+", " ").careful_titleize
      model ||= create_new_model(library, name: name, owner: owner, creator_id: creator_id, collection_id: collection_id, tag_list: tag_list, license: license, sensitive: sensitive, permission_preset: permission_preset)

      attachers.each do |it|
        new_files << if new_model && (attachers.length == 1) && is_archive?(it.file)
          unzip_into_model(model, it.file)
        else
          add_single_file_to_model(model, it.file)
        end
      end
    end

    if new_model
      model.add_new_files_later(include_all_subfolders: true)
    else
      model.check_for_problems_later
    end
    new_files.flatten.each(&:parse_metadata_later)

    attachers.each(&:destroy)
  end

  def is_archive?(file)
    SupportedMimeTypes.archive_extensions.include? File.extname(file.original_filename).delete(".").downcase
  end

  def create_new_model(library, name: nil, owner: nil, creator_id: nil, collection_id: nil, tag_list: nil, license: nil, sensitive: nil, permission_preset: nil)
    params = {
      name: name,
      path: SecureRandom.uuid,
      creator_id: creator_id,
      collection_id: collection_id,
      tag_list: tag_list,
      license: license,
      sensitive: sensitive,
      permission_preset: permission_preset
    }.compact
    model = library.models.new(params)
    model.owner = owner if owner && model.respond_to?(:owner=)
    model.save!
    Permissions::ApplyPreset.call(model, permission_preset: permission_preset, owner: owner)
    model.organize!
    model
  end

  def add_single_file_to_model(model, file)
    case File.extname(file.original_filename).delete(".").downcase
    when *SupportedMimeTypes.indexable_extensions
      new_file = model.model_files.create(filename: file.original_filename, attachment: file)
    else
      Rails.logger.warn("Ignoring #{file.inspect}")
    end
    new_file
  end

  private

  def resolve_owner(owner, owner_id)
    owner || (User.find(owner_id) if owner_id.present?)
  end

  def resolve_model(model, model_id)
    model || (Model.find(model_id) if model_id.present?)
  end

  def unzip_into_model(model, file)
    new_files = []
    ModelFileUploader.with_file(file) do |archive|
      dirname = SecureRandom.uuid
      tmpdir = ModelFileUploader.find_storage(:cache).directory.join(dirname)
      tmpdir.mkdir
      strip = count_common_path_components(archive)
      Archive::Reader.open_filename(archive.path, strip_components: strip) do |reader|
        reader.each_entry do |entry|
          next if !entry.file? || entry.size > SiteSettings.max_file_extract_size
          next if SiteSettings.ignored_file?(entry.pathname)
          filename = entry.pathname
          reader.extract(entry, Archive::EXTRACT_SECURE, destination: tmpdir.to_s)
          new_files << model.model_files.create(filename: filename, attachment: ModelFileUploader.uploaded_file(
            storage: :cache,
            id: File.join(dirname, filename),
            metadata: {filename: File.basename(filename)}
          ))
        end
      end
    end
    new_files
  end

  def count_common_path_components(archive)
    paths = []
    files_in_root = false
    Archive::Reader.open_filename(archive.path) do |reader|
      reader.each_entry do |entry|
        paths << entry.pathname if entry.directory?
        files_in_root = true if entry.file? && entry.pathname.exclude?(File::SEPARATOR)
      end
    end
    return 0 if files_in_root
    paths = paths.map { |path| path.split(File::SEPARATOR) }
    count_common_elements(paths)
  end

  def count_common_elements(arrays)
    return 0 if arrays.empty?
    first = arrays.shift
    zip = first.zip(*arrays)
    zip.count { |it| it.uniq.count == 1 }
  end
end
