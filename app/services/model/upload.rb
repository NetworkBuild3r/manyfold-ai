# frozen_string_literal: true

# Validate upload params and enqueue ProcessUploadedFileJob with ID-only args.
class Model::Upload
  Result = Data.define(:valid?, :model, :multiple?, :jobs, :job_options)

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
    multiple = params[:file]&.values&.all? { |it|
      SupportedMimeTypes.archive_extensions.include?(File.extname(it[:name]).delete(".").downcase)
    }
    job_options = {
      owner_id: @owner.id,
      creator_id: params[:creator_id],
      collection_id: params[:collection_id],
      license: params[:license],
      sensitive: (params[:sensitive] == "1"),
      tag_list: params[:tag_list],
      permission_preset: params[:permission_preset],
      name: multiple ? nil : params[:name]
    }
    dummy = Model.new(job_options.merge(
      name: multiple ? nil : params[:name],
      library: @library
    ))
    validation_context = multiple ? :multi_upload : :single_upload
    unless dummy.valid?(validation_context)
      return Result.new(valid?: false, model: dummy, multiple?: multiple, jobs: [], job_options: job_options)
    end

    jobs = if multiple
      params[:file].values.map { |it| cached_file_data(it) }
    else
      [params[:file].values.map { |it| cached_file_data(it) }]
    end

    Result.new(valid?: true, model: dummy, multiple?: multiple, jobs: jobs, job_options: job_options.compact)
  end

  def enqueue!(result)
    result.jobs.each do |files|
      ProcessUploadedFileJob.perform_later(@library.id, files, **result.job_options)
    end
  end

  private

  def cached_file_data(file)
    {
      id: file[:id],
      storage: "cache",
      metadata: {
        filename: Zaru.sanitize!(File.basename(file[:name]))
      }
    }
  end
end
