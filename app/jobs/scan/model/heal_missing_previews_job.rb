# frozen_string_literal: true

# Assign or repair preview_file from on-disk folder images.
# - Broken preview (set but missing on NFS) → replace or clear
# - Unset / non-image preview when an on-disk image exists → assign best image
# Does not delete Model rows — ghost missing-folder models stay for later cleanup.
class Scan::Model::HealMissingPreviewsJob < ApplicationJob
  queue_as :low
  unique :until_executed, lock_ttl: 2.hours

  DEFAULT_LIMIT = 500

  def perform(limit: DEFAULT_LIMIT, library_id: nil)
    # LIMIT=0 means no cap (heal entire library in one rake pass).
    max = (limit.to_i <= 0) ? Float::INFINITY : limit.to_i

    healed = 0
    healed += heal_broken_previews(library_id: library_id, max: max - healed)
    healed += heal_nil_previews(library_id: library_id, max: max - healed) if healed < max
    healed += heal_non_image_previews(library_id: library_id, max: max - healed) if healed < max

    Rails.logger.info(
      "[scan] HealMissingPreviewsJob healed=#{healed} limit=#{limit} library=#{library_id}"
    )
    healed
  end

  private

  def heal_broken_previews(library_id:, max:)
    return 0 if max <= 0

    scope = Model.where.not(preview_file_id: nil)
      .includes(:preview_file, :model_files, :library)
    scope = scope.where(library_id: library_id) if library_id.present?

    healed = 0
    scope.find_each do |model|
      break if healed >= max

      preview = model.preview_file
      next if preview.nil? || preview.exists_on_storage?

      apply_pick!(model, PreviewFilePicker.new(model).call(require_on_disk: true))
      healed += 1
    end
    healed
  end

  def heal_nil_previews(library_id:, max:)
    return 0 if max <= 0

    scope = Model.where(preview_file_id: nil)
      .includes(:preview_file, :model_files, :library)
    scope = scope.where(library_id: library_id) if library_id.present?

    healed = 0
    scope.find_each do |model|
      break if healed >= max

      pick = PreviewFilePicker.new(model).call(require_on_disk: true)
      next if pick.nil?

      apply_pick!(model, pick)
      healed += 1
    end
    healed
  end

  def heal_non_image_previews(library_id:, max:)
    return 0 if max <= 0

    scope = Model.joins(:preview_file)
      .where.not(image_filename_sql("model_files"))
      .includes(:preview_file, :model_files, :library)
    scope = scope.where(library_id: library_id) if library_id.present?

    healed = 0
    scope.find_each do |model|
      break if healed >= max

      current = model.preview_file
      next if current&.is_image? && current.exists_on_storage?

      pick = PreviewFilePicker.new(model).call(require_on_disk: true)
      next if pick.nil?
      next if current&.id == pick.id

      apply_pick!(model, pick)
      healed += 1
    end
    healed
  end

  def apply_pick!(model, pick)
    model.update!(preview_file: pick)
    model.check_for_problems_later(delay: 1.second)
  end

  def image_filename_sql(table)
    exts = SupportedMimeTypes.image_extensions.map(&:downcase).uniq
    return "FALSE" if exts.empty?

    exts.map { |ext|
      "LOWER(#{table}.filename) LIKE #{ActiveRecord::Base.connection.quote("%.#{ext}")}"
    }.join(" OR ")
  end
end
