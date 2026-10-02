class MergeHistory < ApplicationRecord
  belongs_to :target_model, class_name: "Model"

  scope :active, -> { where(undone_at: nil) }

  def source_preview_filename
    source_metadata&.dig("preview_filename")
  end

  def undone?
    undone_at.present?
  end

  # Files that were actually moved onto the target.
  def adopted_count
    moved_files.count { |file| !file["deduplicated"] }
  end

  # Files dropped because identical bytes already lived on the target.
  def deduplicated_count
    moved_files.count { |file| file["deduplicated"] }
  end

  def undoable?
    !undone? && created_at >= Model::UNMERGE_WINDOW.ago
  end
end
