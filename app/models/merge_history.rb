class MergeHistory < ApplicationRecord
  belongs_to :target_model, class_name: "Model"

  scope :active, -> { where(undone_at: nil) }

  def source_preview_filename
    source_metadata&.dig("preview_filename")
  end
end

