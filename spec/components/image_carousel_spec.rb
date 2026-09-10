# frozen_string_literal: true

# Provenance: INIT-006/SPEC-002
require "rails_helper"

RSpec.describe Components::ImageCarousel, type: :component do
  let(:model) { create(:model) }
  let!(:preview) { create(:model_file, model: model, filename: "a.jpg") }
  let!(:second) { create(:model_file, model: model, filename: "b.jpg") }

  before do
    model.update!(preview_file: preview)
    allow(controller).to receive(:policy).and_return(double(edit?: false, destroy?: false, update?: false))
  end

  it "renders browse carousel with prev/next when two or more images" do
    html = render described_class.new(images: [preview, second], browse: true)
    expect(html).to include('id="browseCarousel"')
    expect(html).to include('data-carousel-interval-value="0"')
    expect(html).to include("object-contain")
    expect(html).to include("carousel#prev")
    expect(html).to include("carousel#next")
    expect(html).to include("carousel-item")
  end

  it "omits prev/next for a single browse image" do
    html = render described_class.new(images: [preview], browse: true)
    expect(html).to include('id="browseCarousel"')
    expect(html).not_to include("carousel#prev")
    expect(html).not_to include("carousel#next")
  end

  # INIT-026/SPEC-006
  context "with a ready archive image" do
    let(:zip) { create(:model_file, model: model, filename: "pack.zip") }
    let(:entry) do
      ArchiveEntry.create!(
        model_file: zip,
        pathname: "pics/inner.png",
        kind: "image",
        status: "preview_ready",
        preview_path: "m/.manyfold/derivatives/archives/inner.png"
      )
    end

    it "renders the archive preview route instead of a ModelFile carousel derivative" do
      html = render described_class.new(images: [preview, entry], browse: true)
      preview_url = view_context.preview_model_model_file_archive_entry_path(model, zip, entry)
      expect(html).to include(preview_url)
      expect(html).not_to include("inner.png?derivative=carousel")
    end
  end

  context "when the operator can update" do
    let(:entry) do
      zip = create(:model_file, model: model, filename: "pack.zip")
      ArchiveEntry.create!(
        model_file: zip,
        pathname: "pics/inner.png",
        kind: "image",
        status: "preview_ready",
        preview_path: "m/.manyfold/derivatives/archives/inner.png"
      )
    end

    before do
      allow(controller).to receive(:policy).and_return(double(edit?: true, destroy?: true, update?: true))
    end

    it "labels loose vs archive sources" do
      html = render described_class.new(images: [preview, entry], browse: false)
      expect(html).to include(I18n.t("models.gallery.source_loose"))
      expect(html).to include(I18n.t("models.gallery.source_archive"))
    end

    it "uses distinct turbo-safe confirms for loose and archive delete" do
      html = render described_class.new(images: [preview, entry], browse: false)
      expect(html).to include(I18n.t("models.gallery.delete_confirm_loose"))
      expect(html).to include(I18n.t("models.gallery.delete_confirm_archive", archive: "pack.zip", name: entry.name))
      expect(html).to include(%(name="_method" value="delete"))
    end
  end
end
