# frozen_string_literal: true

# Clear or re-pick preview_file when the pointed-at image is gone from NFS.
# Does not delete Model rows — orphan missing-folder models stay for a later cleanup.
class Scan::Model::HealMissingPreviewsJob < ApplicationJob
  queue_as :low
  unique :until_executed, lock_ttl: 2.hours

  DEFAULT_LIMIT = 500

  def perform(limit: DEFAULT_LIMIT, library_id: nil)
    scope = Model.where.not(preview_file_id: nil).includes(:preview_file, :model_files, :library)
    scope = scope.where(library_id: library_id) if library_id.present?

    healed = 0
    scope.find_each do |model|
      break if healed >= limit

      preview = model.preview_file
      next if preview.nil? || preview.exists_on_storage?

      replacement = model.model_files
        .select { |f| f.is_image? && f.exists_on_storage? }
        .min_by { |f| f.filename.to_s }

      if replacement
        model.update!(preview_file: replacement)
      else
        model.update!(preview_file: nil)
      end
      model.check_for_problems_later(delay: 1.second)
      healed += 1
    end

    Rails.logger.info("[scan] HealMissingPreviewsJob healed=#{healed} limit=#{limit} library=#{library_id}")
    healed
  end
end
