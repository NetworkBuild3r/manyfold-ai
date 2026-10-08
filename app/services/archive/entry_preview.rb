# frozen_string_literal: true

module Archive
  # INIT-026 fallback preview: when an archive image has no loose copy, the
  # entry itself (or a same-digest match) becomes the model's preview so image
  # search can see it. Used only if Archive::AdoptImage could not adopt it.
  class EntryPreview
    def initialize(model, entry)
      @model = model
      @entry = entry
    end

    def assign_preview!
      return if image_preview?

      source = preview_source(matching_image(@entry.digest))
      case source
      when ModelFile
        @model.update!(preview_file: source)
      when ArchiveEntry
        @model.update!(preview_archive_entry: source) unless @model.preview_archive_entry_id == source.id
      end
    end

    private

    def preview_source(match)
      case match
      when ModelFile
        match
      when ArchiveEntry
        match.preview_exists? ? match : @entry
      else
        @entry
      end
    end

    def image_preview?
      file = @model.preview_file
      return true if file&.is_image? && file.exists_on_storage?

      current = @model.preview_archive_entry
      current&.is_image? && current.preview_exists?
    end

    def matching_image(digest)
      return if digest.blank?

      file = @model.model_files.where(digest: digest).detect(&:is_image?)
      return file if file

      @model.archive_entries.where(digest: digest, kind: "image").where.not(id: @entry.id).first
    end
  end
end
