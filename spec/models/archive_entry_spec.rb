require "rails_helper"

RSpec.describe ArchiveEntry do
  let(:model) { create(:model) }
  let(:archive) { create(:model_file, model: model, filename: "pack.zip") }
  let(:image) { create(:model_file, model: model, filename: "shot.png") }

  def entry(pathname, status: "listed", kind: "image")
    archive.archive_entries.create!(pathname: pathname, kind: kind, status: status)
  end

  describe "adopted_model_file link" do
    it "records the ModelFile an entry was adopted into" do
      e = entry("pics/shot.png")
      e.update!(adopted_model_file: image)

      expect(e.reload.adopted_model_file).to eq(image)
      expect(image.adopted_from_entries).to contain_exactly(e)
    end

    it "lets several entries point at one adopted file" do
      a = entry("a/shot.png")
      b = entry("b/shot.png")
      [a, b].each { |e| e.update!(adopted_model_file: image) }

      expect(image.adopted_from_entries).to contain_exactly(a, b)
    end

    it "keeps the entry and clears the link when the adopted file is destroyed" do
      e = entry("pics/shot.png")
      e.update!(adopted_model_file: image)

      image.destroy

      expect(e.reload).to be_persisted
      expect(e.adopted_model_file_id).to be_nil
    end
  end

  describe "dismissed status" do
    it "is a valid status" do
      expect(entry("pics/gone.png", status: "dismissed")).to be_valid
    end
  end

  describe ".adoptable" do
    it "returns image entries that are not too_large, skipped or dismissed" do
      listed = entry("ok.png")
      ready = entry("ready.png", status: "preview_ready")
      entry("big.png", status: "too_large")
      entry("skip.png", status: "skipped")
      entry("gone.png", status: "dismissed")
      entry("part.stl", kind: "mesh")

      expect(described_class.adoptable).to contain_exactly(listed, ready)
    end
  end
end
