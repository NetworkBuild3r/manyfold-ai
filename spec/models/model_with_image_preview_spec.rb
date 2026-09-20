# frozen_string_literal: true

# Provenance: INIT-009/SPEC-005
require "rails_helper"

RSpec.describe "Model.with_image_preview" do
  it "uses EXISTS + filename_lower instead of IN (SELECT … LOWER(filename))" do
    sql = Model.with_image_preview.to_sql
    expect(sql).to match(/EXISTS\s*\(/i)
    expect(sql).to include("filename_lower")
    expect(sql).not_to match(/preview_file_id\s+IN\s*\(/i)
    expect(sql).not_to match(/LOWER\(\s*model_files\.filename\s*\)/i)
  end

  it "keeps only models whose preview_file is an image" do
    with_image = create(:model)
    image = create(:model_file, model: with_image, filename: "cover.jpg")
    with_image.update!(preview_file: image)

    orphan = create(:model)
    create(:model_file, model: orphan, filename: "photo.png")

    mesh = create(:model)
    stl = create(:model_file, model: mesh, filename: "part.stl")
    create(:model_file, model: mesh, filename: "photo.jpg")
    mesh.update!(preview_file: stl)

    expect(Model.with_image_preview).to contain_exactly(with_image)
  end

  it "includes a model whose preview is a ready archive image" do
    model = create(:model)
    file = create(:model_file, model: model, filename: "pack.zip")
    entry = ArchiveEntry.create!(
      model_file: file,
      pathname: "pics/shot.png",
      kind: "image",
      status: "preview_ready",
      preview_path: "m/.manyfold/preview.png"
    )
    model.update!(preview_archive_entry: entry)

    expect(Model.with_image_preview).to contain_exactly(model)
  end
end
