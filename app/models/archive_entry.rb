# frozen_string_literal: true

class ArchiveEntry < ApplicationRecord
  include PublicIDable

  KINDS = %w[mesh image other].freeze
  STATUSES = %w[listed preview_pending preview_ready preview_failed too_large skipped].freeze

  RENDERABLE_EXTENSIONS = %w[stl obj 3mf ply gltf glb drc fbx 3ds gcode mpd ldr 3dm].freeze

  belongs_to :model_file, touch: true

  validates :pathname, presence: true, uniqueness: {scope: :model_file_id}
  validates :kind, inclusion: {in: KINDS}
  validates :status, inclusion: {in: STATUSES}

  scope :meshes, -> { where(kind: "mesh") }
  scope :images, -> { where(kind: "image") }
  scope :previewable, -> { where(kind: %w[mesh image]) }
  scope :with_preview, -> { where(status: "preview_ready") }

  delegate :model, to: :model_file

  def extension
    File.extname(pathname.to_s).delete(".").downcase
  end

  def basename
    File.basename(pathname)
  end

  def name
    basename.humanize.careful_titleize
  rescue
    basename
  end

  def is_renderable?
    kind == "mesh"
  end

  def is_image?
    kind == "image"
  end

  def y_up
    false
  end

  def preview_ready?
    status == "preview_ready" && preview_path.present?
  end

  def absolute_preview_path
    return nil if preview_path.blank?
    File.join(model.library.path, preview_path)
  end

  def absolute_extracted_path
    return nil if extracted_path.blank?
    File.join(model.library.path, extracted_path)
  end

  def preview_exists?
    preview_ready? && model.library.has_file?(preview_path)
  end

  def extracted_exists?
    extracted_path.present? && model.library.has_file?(extracted_path)
  end

  def self.kind_for_pathname(pathname)
    ext = File.extname(pathname.to_s).delete(".").downcase
    return "image" if SupportedMimeTypes.image_extensions.include?(ext)
    return "mesh" if RENDERABLE_EXTENSIONS.include?(ext)
    "other"
  end
end
