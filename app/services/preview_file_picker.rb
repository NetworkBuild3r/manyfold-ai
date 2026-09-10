# frozen_string_literal: true

# Picks a model's base preview: prefer an existing on-disk image, else a folder
# image (preview/cover/thumb names first), else a ready archive image, else mesh.
# Used by ParseMetadata and HealMissingPreviews so has_image filter and grid
# cards stay aligned. INIT-026/SPEC-003: may return a ModelFile or ArchiveEntry.
class PreviewFilePicker
  # Basename starts with preview/cover/thumb (optional images/ prefix).
  NAMED_IMAGE = %r{\A(?:.*/)?(?:preview|cover|thumb)[^/]*\z}i

  def initialize(model)
    @model = model
  end

  # When require_on_disk: only return an image that exists on storage (heal path).
  # When false: ParseMetadata path — may keep a missing image or fall back to mesh.
  def call(require_on_disk: false)
    files = @model.model_files.to_a
    current_file = @model.preview_file
    current_entry = @model.preview_archive_entry
    on_disk_images = files.select { |f| f.is_image? && f.exists_on_storage? }
    ready_archive_images = archive_image_candidates

    if current_file&.is_image? && current_file.exists_on_storage?
      return current_file
    end

    if archive_image_usable?(current_entry)
      return current_entry
    end

    best_on_disk = on_disk_images.min_by { |f| priority(f) }
    return best_on_disk if best_on_disk

    best_archive = ready_archive_images.min_by { |entry| priority(entry) }
    return best_archive if best_archive
    return nil if require_on_disk

    # Keep a missing image only when no on-disk replacement exists.
    return current_file if current_file&.is_image?

    best_image = files.select(&:is_image?).min_by { |f| priority(f) }
    return best_image if best_image

    current_file.presence || current_entry.presence || files.min_by { |f| priority(f) }
  end

  def self.priority(file)
    new(file.model).priority(file)
  end

  def priority(file)
    return named_image_rank(file) if image_source?(file)
    return 50 if file.is_renderable?

    100
  end

  private

  def archive_image_candidates
    @model.archive_entries.select { |entry| archive_image_usable?(entry) }
  end

  def archive_image_usable?(entry)
    entry.present? && entry.is_image? && entry.preview_ready? && entry.preview_exists?
  end

  def image_source?(file)
    file.is_image?
  end

  def named_image_rank(file)
    name = if file.is_a?(ArchiveEntry)
      file.basename.to_s
    else
      file.filename.to_s
    end
    return 0 if name.match?(NAMED_IMAGE)

    10
  end
end
