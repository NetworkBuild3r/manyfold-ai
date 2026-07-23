# frozen_string_literal: true

# Repair public models that bypassed validate_publishable (e.g. raw SQL /
# grant_permission_to). Default action demotes the public view grant; pass
# dry_run: true to only report.
#
# Usage:
#   Scan::RepairUnpublishablePublicModelsJob.perform_now
#   Scan::RepairUnpublishablePublicModelsJob.perform_now(dry_run: true)
#   rake manyfold:repair_unpublishable_public_models
class Scan::RepairUnpublishablePublicModelsJob < ApplicationJob
  queue_as :low
  unique :until_executed, lock_ttl: 2.hours

  def perform(dry_run: false)
    repaired = 0
    skipped = 0

    Model.find_each do |model|
      next unless model.public?

      issues = []
      issues << :license if model.license.blank?
      issues << :creator if model.creator.nil?
      issues << :creator_private if model.creator && !model.creator.public?
      if issues.empty?
        skipped += 1
        next
      end

      Rails.logger.warn(
        "[repair] model=#{model.id} public_id=#{model.public_id} issues=#{issues.join(",")}"
      )

      unless dry_run
        # Demote public view grant — do not invent license/creator metadata.
        model.caber_relations.where(subject: nil).find_each(&:destroy)
        repaired += 1
      else
        repaired += 1
      end
    end

    Rails.logger.info(
      "[repair] RepairUnpublishablePublicModelsJob dry_run=#{dry_run} " \
      "affected=#{repaired} ok=#{skipped}"
    )
    {affected: repaired, ok: skipped, dry_run: dry_run}
  end
end
