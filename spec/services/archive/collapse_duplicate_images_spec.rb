# frozen_string_literal: true

require "rails_helper"

RSpec.describe Archive::CollapseDuplicateImages do
  let(:model) { create(:model) }

  def image_entry(file, pathname, digest:)
    ArchiveEntry.create!(
      model_file: file,
      pathname: pathname,
      kind: "image",
      status: "preview_ready",
      preview_path: "m/.manyfold/#{pathname.tr("/", "-")}",
      digest: digest
    )
  end

  it "skips an archive image that matches a loose file and keeps the file" do
    loose = create(:model_file, model: model, filename: "cover.jpg", digest: "abc")
    archive = create(:model_file, model: model, filename: "pack.zip")
    entry = image_entry(archive, "pics/cover.jpg", digest: "abc")

    described_class.call(model)

    expect(entry.reload.status).to eq("skipped")
    expect(entry.error_message).to eq("duplicate image")
    expect(ModelFile.exists?(loose.id)).to be(true)
  end

  it "keeps the preview file and removes the other loose copy" do
    keeper = create(:model_file, model: model, filename: "keep.jpg", digest: "abc")
    extra = create(:model_file, model: model, filename: "extra.jpg", digest: "abc")
    model.update!(preview_file: keeper)

    described_class.call(model)

    expect(ModelFile.exists?(keeper.id)).to be(true)
    expect(ModelFile.exists?(extra.id)).to be(false)
    expect(model.reload.preview_file).to eq(keeper)
  end

  it "moves preview from a duplicate archive image onto the loose file" do
    loose = create(:model_file, model: model, filename: "cover.jpg", digest: "abc")
    archive = create(:model_file, model: model, filename: "pack.zip")
    entry = image_entry(archive, "pics/cover.jpg", digest: "abc")
    model.update!(preview_archive_entry: entry)

    described_class.call(model)

    expect(model.reload.preview_file).to eq(loose)
    expect(model.preview_archive_entry).to be_nil
    expect(entry.reload.status).to eq("skipped")
  end
end
