# frozen_string_literal: true

# INIT-027/SPEC-010
require "rails_helper"

RSpec.describe Components::SetPreviewControl, type: :component do
  include Rails.application.routes.url_helpers

  let(:model) { create(:model) }
  let(:file) { create(:model_file, model: model, filename: "cover.jpg") }

  it "PATCHes the model with preview_file_id" do
    html = render described_class.new(model: model, preview_file_id: file.id)
    expect(html).to include("<form")
    expect(html).to include(model_path(model))
    expect(html).to include('name="_method"')
    expect(html).to include('value="patch"')
    expect(html).to include(%(name="model[preview_file_id]"))
    expect(html).to include(I18n.t("models.file.set_as_preview"))
  end

  it "PATCHes the model with preview_archive_entry_id" do # rubocop:todo RSpec/ExampleLength, RSpec/MultipleExpectations
    zip = create(:model_file, model: model, filename: "pack.zip")
    entry = ArchiveEntry.create!(
      model_file: zip,
      pathname: "pics/inner.png",
      kind: "image",
      status: "preview_ready",
      preview_path: "m/.manyfold/derivatives/archives/inner.png"
    )
    html = render described_class.new(model: model, preview_archive_entry_id: entry.id)
    expect(html).to include(%(name="model[preview_archive_entry_id]"))
    expect(html).to include(entry.id.to_s)
  end
end
