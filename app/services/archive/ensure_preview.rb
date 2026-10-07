# frozen_string_literal: true

module Archive
  # Scanner backfill. Assign an on-disk image as preview, or, when the only
  # pictures are inside an archive, copy one unmatched image onto the model
  # and set it as preview. Hash identity lives in AdoptImage.
  class EnsurePreview
    def self.call(model)
      new(model).call
    end

    def initialize(model)
      @model = model
    end

    def call
      return if image_preview?

      pick = PreviewFilePicker.new(@model).call(require_on_disk: true)
      if pick&.is_image?
        @model.update!(preview_file: pick) unless @model.preview_file_id == pick.id
        return
      end

      entry = best_archive_image
      return unless entry

      ArchiveEntryService.new(entry.model_file).extract_preview_image!(entry)
    rescue ArchiveEntryService::EntryTooLarge, ArchiveEntryService::EntryNotFound, ArchiveEntryService::UnsafePath
      nil
    end

    private

    def image_preview?
      current = @model.preview_file
      current&.is_image? && current.exists_on_storage?
    end

    def best_archive_image
      ArchiveEntry.joins(:model_file)
        .where(model_files: {model_id: @model.id}, kind: "image")
        .where.not(status: %w[too_large skipped])
        .min_by { |entry| [name_rank(entry), entry.size.to_i, entry.id] }
    end

    def name_rank(entry)
      name = entry.basename.to_s.downcase
      (name.include?("preview") || name.include?("cover") || name.include?("thumb")) ? 0 : 1
    end
  end
end
