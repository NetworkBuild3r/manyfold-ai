# frozen_string_literal: true

class ArchiveEntry < ApplicationRecord
  include PublicIDable

  KINDS = %w[mesh image other].freeze
  STATUSES = %w[listed preview_pending preview_ready preview_failed too_large skipped].freeze

  RENDERABLE_EXTENSIONS = %w[stl obj 3mf ply gltf glb drc fbx 3ds gcode mpd ldr 3dm].freeze

  belongs_to :model_file, touch: true
  # INIT-026/SPEC-002: models.preview_archive_entry_id nullifies when this entry is destroyed.
  has_many :previewing_models, class_name: "Model", foreign_key: :preview_archive_entry_id,
    dependent: :nullify, inverse_of: :preview_archive_entry

  validates :pathname, presence: true, uniqueness: {scope: :model_file_id}
  validates :kind, inclusion: {in: KINDS}
  validates :status, inclusion: {in: STATUSES}

  scope :meshes, -> { where(kind: "mesh") }
  scope :images, -> { where(kind: "image") }
  scope :previewable, -> { where(kind: %w[mesh image]) }
  scope :with_preview, -> { where(status: "preview_ready") }

  # Image search: a ready archive image set as preview_archive_entry counts.
  def self.image_preview_exists_sql
    Arel.sql(
      "EXISTS (SELECT 1 FROM archive_entries WHERE archive_entries.id = models.preview_archive_entry_id" \
      " AND archive_entries.kind = 'image' AND archive_entries.status = 'preview_ready'" \
      " AND archive_entries.preview_path IS NOT NULL)"
    )
  end

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
