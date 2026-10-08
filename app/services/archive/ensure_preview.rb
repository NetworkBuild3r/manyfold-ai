# frozen_string_literal: true

module Archive
  # Scanner backfill. Assign an on-disk image as preview, or, when the only
  # pictures are inside an archive, queue the best unadopted archive image so
  # PreviewArchiveEntryJob adopts it (and AdoptImage sets it as preview).
  # Best-effort: never raises, so problem checks and heal batches keep going
  # (INIT-001/SPEC-003). Returns :assigned, :enqueued or nil.
  class EnsurePreview
    PREFERRED_NAMES = %w[preview cover thumb].freeze

    def self.call(model)
      new(model).call
    end

    def initialize(model)
      @model = model
    end

    def call
      return if image_preview?

      # Archive entries are adopted below rather than used as the preview.
      pick = PreviewFilePicker.new(@model).call(require_on_disk: true)
      if pick.is_a?(ModelFile) && pick.is_image?
        @model.update!(preview_file: pick) unless @model.preview_file_id == pick.id
        return :assigned
      end

      entry = best_archive_image
      return unless entry

      entry.update!(status: "preview_pending", error_message: nil)
      Scan::ModelFile::PreviewArchiveEntryJob.perform_later(entry.id)
      :enqueued
    rescue => e
      Rails.logger.warn("[EnsurePreview] model=#{@model.id} #{e.class}: #{e.message}")
      nil
    end

    private

    def image_preview?
      current = @model.preview_file
      current&.is_image? && current.exists_on_storage?
    end

    def best_archive_image
      ArchiveEntry.adoptable.joins(:model_file) # rubocop:disable Pundit/UsePolicyScope -- background job, no user
        .where(model_files: {model_id: @model.id}, adopted_model_file_id: nil)
        .where.not(status: "preview_failed")
        .where(archive_entries: {size: ..SiteSettings.max_file_extract_size})
        .min_by { |entry| [name_rank(entry), entry.size.to_i, entry.id] }
    end

    def name_rank(entry)
      name = entry.basename.to_s.downcase
      (PREFERRED_NAMES.any? { |word| name.include?(word) }) ? 0 : 1
    end
  end
end
