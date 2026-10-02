# frozen_string_literal: true

# INIT-031/SPEC-003 — digest/size without running AnalyseModelFileJob callbacks.
module DuplicateTriageSpecHelpers
  def digested_file(model, filename:, digest:, size:)
    create(:model_file, model: model, filename: filename).tap do |file|
      file.update_columns(digest: digest, size: size) # rubocop:disable Rails/SkipsModelValidations -- digest fixture
    end
  end

  def sized_file(model, filename:, size:)
    create(:model_file, model: model, filename: filename).tap do |file|
      file.update_columns(digest: nil, size: size) # rubocop:disable Rails/SkipsModelValidations -- undigested size fixture
    end
  end
end

RSpec.configure do |config|
  config.include DuplicateTriageSpecHelpers, type: :duplicate_triage
end
