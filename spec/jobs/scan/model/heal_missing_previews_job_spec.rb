# frozen_string_literal: true

require "rails_helper"
require "support/mock_directory"

RSpec.describe Scan::Model::HealMissingPreviewsJob do
  let(:library) { create(:library, path: @library_path) } # rubocop:todo RSpec/InstanceVariable

  around do |ex|
    MockDirectory.create([
      "good_model/ok.jpg",
      "good_model/gone.jpg",
      "good_model/preview.jpg",
      "unset_model/photo.png",
      "mesh_model/part.stl",
      "mesh_model/cover.jpg"
    ]) do |path|
      @library_path = path
      File.delete(File.join(path, "good_model/gone.jpg"))
      ex.run
    end
  end

  it "re-picks an on-disk image when the preview is missing" do
    model = create(:model, library: library, path: "good_model")
    gone = create(:model_file, model: model, filename: "gone.jpg")
    create(:model_file, model: model, filename: "ok.jpg")
    model.update!(preview_file: gone)

    described_class.perform_now(limit: 10)
    expect(model.reload.preview_file.filename).to eq "ok.jpg"
  end

  it "prefers preview.jpg over other on-disk images when healing" do
    model = create(:model, library: library, path: "good_model")
    gone = create(:model_file, model: model, filename: "gone.jpg")
    create(:model_file, model: model, filename: "ok.jpg")
    create(:model_file, model: model, filename: "preview.jpg")
    model.update!(preview_file: gone)

    described_class.perform_now(limit: 10)
    expect(model.reload.preview_file.filename).to eq "preview.jpg"
  end

  it "clears preview_file when no on-disk image remains" do
    model = create(:model, library: library, path: "good_model")
    gone = create(:model_file, model: model, filename: "gone.jpg")
    model.update!(preview_file: gone)

    expect {
      described_class.perform_now(limit: 10)
    }.to change { model.reload.preview_file_id }.from(gone.id).to(nil)
  end

  it "assigns an on-disk image when preview_file is unset" do
    model = create(:model, library: library, path: "unset_model")
    photo = create(:model_file, model: model, filename: "photo.png")
    expect(model.preview_file).to be_nil

    expect {
      described_class.perform_now(limit: 10)
    }.to change { model.reload.preview_file_id }.from(nil).to(photo.id)
  end

  it "upgrades a mesh preview to an on-disk image" do
    model = create(:model, library: library, path: "mesh_model")
    stl = create(:model_file, model: model, filename: "part.stl")
    cover = create(:model_file, model: model, filename: "cover.jpg")
    model.update!(preview_file: stl)

    expect {
      described_class.perform_now(limit: 10)
    }.to change { model.reload.preview_file_id }.from(stl.id).to(cover.id)
  end

  it "keeps an existing on-disk image preview" do
    model = create(:model, library: library, path: "good_model")
    ok = create(:model_file, model: model, filename: "ok.jpg")
    create(:model_file, model: model, filename: "preview.jpg")
    model.update!(preview_file: ok)

    expect {
      described_class.perform_now(limit: 10)
    }.not_to change { model.reload.preview_file_id }
  end
end
