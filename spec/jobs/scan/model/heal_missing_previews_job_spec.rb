# frozen_string_literal: true

require "rails_helper"
require "support/mock_directory"

RSpec.describe Scan::Model::HealMissingPreviewsJob do
  let(:library) { create(:library, path: @library_path) } # rubocop:todo RSpec/InstanceVariable

  around do |ex|
    MockDirectory.create([
      "good_model/ok.jpg",
      "good_model/gone.jpg"
    ]) do |path|
      @library_path = path
      File.delete(File.join(path, "good_model/gone.jpg"))
      ex.run
    end
  end

  it "re-picks an on-disk image when the preview is missing" do
    model = create(:model, library: library, path: "good_model")
    gone = create(:model_file, model: model, filename: "gone.jpg")
    ok = create(:model_file, model: model, filename: "ok.jpg")
    model.update!(preview_file: gone)

    expect {
      described_class.perform_now(limit: 10)
    }.to change { model.reload.preview_file_id }.from(gone.id).to(ok.id)
  end

  it "clears preview_file when no on-disk image remains" do
    model = create(:model, library: library, path: "good_model")
    gone = create(:model_file, model: model, filename: "gone.jpg")
    model.update!(preview_file: gone)

    expect {
      described_class.perform_now(limit: 10)
    }.to change { model.reload.preview_file_id }.from(gone.id).to(nil)
  end
end
