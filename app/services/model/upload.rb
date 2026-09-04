# frozen_string_literal: true

# Validate upload params and enqueue ProcessUploadedFileJob with ID-only args.
class Model::Upload
  Result = Data.define(:valid?, :model, :multiple?, :jobs, :job_options)
  MODEL_ATTRS = %i[creator_id collection_id license sensitive tag_list permission_preset name].freeze

  def self.call(library:, params:, owner:, enqueue: true)
    upload = new(library: library, owner: owner)
    result = upload.call(params)
    upload.enqueue!(result) if enqueue && result.valid?
    result
  end

  def initialize(library:, owner:)
    @library = library
    @owner = owner
  end

  def call(params)
    params = indifferent_hash(params)
    files = file_entries(params[:file])

    multiple = files.any? && files.all? { |it|
      SupportedMimeTypes.archive_extensions.include?(File.extname(it[:name].to_s).delete(".").downcase)
    }
    job_options = {
      owner_id: @owner&.id,
      creator_id: params[:creator_id],
      collection_id: params[:collection_id],
      license: params[:license],
      sensitive: (params[:sensitive] == "1"),
      tag_list: params[:tag_list],
      permission_preset: params[:permission_preset],
      name: multiple ? nil : params[:name]
    }
    dummy = Model.new(job_options.slice(*MODEL_ATTRS).merge(
      name: multiple ? nil : params[:name],
      library: @library
    ))
    validation_context = multiple ? :multi_upload : :single_upload
    unless dummy.valid?(validation_context)
      return Result.new(valid?: false, model: dummy, multiple?: multiple, jobs: [], job_options: job_options)
    end

    jobs = if multiple
      files.map { |it| cached_file_data(it) }
    else
      [files.map { |it| cached_file_data(it) }]
    end

    Result.new(valid?: true, model: dummy, multiple?: multiple, jobs: jobs, job_options: job_options.compact)
  end

  def enqueue!(result)
    result.jobs.each do |files|
      ProcessUploadedFileJob.perform_later(@library.id, files, **result.job_options)
    end
  end

  private

  def file_entries(file)
    return [] if file.blank?

    values = file.respond_to?(:values) ? file.values : Array.wrap(file)
    values.filter_map { |it| indifferent_hash(it).presence }
  end

  def indifferent_hash(obj)
    return {} if obj.nil?

    hash = obj.respond_to?(:to_unsafe_h) ? obj.to_unsafe_h : obj.to_h
    hash.with_indifferent_access
  rescue TypeError, NoMethodError
    {}
  end

  def cached_file_data(file)
    file = indifferent_hash(file)
    {
      id: file[:id],
      storage: "cache",
      metadata: {
        filename: Zaru.sanitize!(File.basename(file[:name].to_s))
      }
    }
  end
end
