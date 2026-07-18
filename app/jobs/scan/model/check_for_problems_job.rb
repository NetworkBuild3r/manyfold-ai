class Scan::Model::CheckForProblemsJob < ApplicationJob
  queue_as :scan
  unique :until_executed, lock_ttl: 15.minutes

  # Light pass during missing-file batch: structural problems only.
  # Full MissingFile / metadata problems run via FinalizeScanBatch / check_for_problems_later.
  def perform(model_id, light: false)
    model = Model.find(model_id)
    return if model.remote?
    Problems::MissingModel.detect(model)
    Problems::EmptyModel.detect(model)
    return if light

    Problems::Nesting.detect(model)
    Problems::NoImage.detect(model)
    Problems::No3dModel.detect(model)
    Problems::NoLicense.detect(model)
    Problems::NoLinks.detect(model)
    Problems::NoCreator.detect(model)
    Problems::NoTags.detect(model)
    Problems::FileNaming.detect(model)
    model.model_files.each do |f|
      Problems::MissingFile.detect(f)
    end
  end
end
