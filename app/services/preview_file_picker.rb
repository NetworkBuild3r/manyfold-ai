# frozen_string_literal: true

# Picks a model's preview_file: prefer an existing on-disk image, else a folder
# image (preview/cover/thumb names first), else mesh. Used by ParseMetadata and
# HealMissingPreviews so has_image filter and grid cards stay aligned.
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
    current = @model.preview_file
    on_disk_images = files.select { |f| f.is_image? && f.exists_on_storage? }

    if current&.is_image? && current.exists_on_storage?
      return current
    end

    best_on_disk = on_disk_images.min_by { |f| priority(f) }
    return best_on_disk if best_on_disk
    return nil if require_on_disk

    # Keep a missing image only when no on-disk replacement exists.
    return current if current&.is_image?

    best_image = files.select(&:is_image?).min_by { |f| priority(f) }
    return best_image if best_image

    current.presence || files.min_by { |f| priority(f) }
  end

  def self.priority(file)
    new(file.model).priority(file)
  end

  def priority(file)
    return named_image_rank(file) if file.is_image?
    return 50 if file.is_renderable?

    100
  end

  private

  def named_image_rank(file)
    name = file.filename.to_s
    return 0 if name.match?(NAMED_IMAGE)

    10
  end
end
