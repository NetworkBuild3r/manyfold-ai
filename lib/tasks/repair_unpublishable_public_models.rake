# frozen_string_literal: true

namespace :manyfold do
  desc "Demote public models that are missing license/creator (bypassed validate_publishable). " \
       "DRY_RUN=1 to report only."
  task repair_unpublishable_public_models: :environment do
    dry_run = ENV["DRY_RUN"].present? && ENV["DRY_RUN"] != "0"
    result = Scan::RepairUnpublishablePublicModelsJob.perform_now(dry_run: dry_run)
    puts result.inspect
  end
end
