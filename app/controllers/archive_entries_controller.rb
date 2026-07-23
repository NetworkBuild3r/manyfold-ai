# frozen_string_literal: true

class ArchiveEntriesController < ApplicationController
  PAGE_SIZE = 100

  before_action :get_model
  before_action :get_file
  before_action :get_entry, except: [:index, :scan]
  before_action -> { set_indexable @file }

  def index
    # Listing archive members is a full-view action (not preview-only).
    authorize @file, :download?
    @offset = [params[:offset].to_i, 0].max
    requested = params[:per_page].to_i
    @per_page = (requested.positive? ? [requested, PAGE_SIZE].min : PAGE_SIZE)
    scope = @file.archive_entries.order(:pathname)
    @total_count = scope.count
    @entries = scope.offset(@offset).limit(@per_page).to_a
    @next_offset = @offset + @entries.size
    @has_more = @next_offset < @total_count
  end

  def show
    authorize @file, :show?
  end

  def scan
    authorize @file, :scan_archive?
    @file.scan_archive_later
    redirect_back_or_to [@model, @file], notice: t(".started")
  end

  def download
    authorize @file, :download?
    send_entry(disposition: :attachment)
  end

  def content
    authorize @file, :download?
    send_entry(disposition: :inline)
  end

  def preview
    # Thumbnail/preview remains available under show? (preview grants OK).
    authorize @file, :show?
    unless @entry.preview_exists?
      head :not_found
      return
    end

    path = @entry.absolute_preview_path
    send_file path,
      type: "image/png",
      disposition: "inline",
      filename: "#{@entry.basename}.png"
  end

  private

  def get_model
    @model = policy_scope(Model).find_param(params[:model_id])
  end

  def get_file
    @file = @model.model_files.find_param(params[:model_file_id].presence || params[:id])
  end

  def get_entry
    @entry = @file.archive_entries.find_param(params[:id])
  end

  def send_entry(disposition:)
    service = ArchiveEntryService.new(@file)

    if @entry.is_renderable?
      begin
        service.extract_to_cache!(@entry) unless @entry.extracted_exists?
      rescue ArchiveEntryService::EntryTooLarge
        head :payload_too_large
        return
      rescue ArchiveEntryService::EntryNotFound
        head :not_found
        return
      end

      path = @entry.absolute_extracted_path
      unless path && File.file?(path)
        head :not_found
        return
      end

      send_file path,
        type: Mime::Type.lookup_by_extension(@entry.extension)&.to_s || "application/octet-stream",
        disposition: disposition,
        filename: @entry.basename
      return
    end

    begin
      tmp = service.extract_to_tempfile(@entry)
      # Keep tempfile until process exit; unlinking before send_file races the IO.
      ObjectSpace.define_finalizer(tmp, tmp.method(:close!).to_proc) rescue nil
      send_file tmp.path,
        type: Mime::Type.lookup_by_extension(@entry.extension)&.to_s || "application/octet-stream",
        disposition: disposition,
        filename: @entry.basename
    rescue ArchiveEntryService::EntryTooLarge
      head :payload_too_large
    rescue ArchiveEntryService::EntryNotFound
      head :not_found
    end
  end
end
