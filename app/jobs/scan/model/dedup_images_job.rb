# frozen_string_literal: true

# Drop extra images on a model that share a SHA-512 with one we already keep.
class Scan::Model::DedupImagesJob < ApplicationJob
  queue_as :low
  unique :until_executed, lock_ttl: 30.minutes

  def perform(model_id)
    model = Model.find(model_id)
    return if model.remote?

    Archive::CollapseDuplicateImages.call(model)
  end
end
