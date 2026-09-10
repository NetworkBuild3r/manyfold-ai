# frozen_string_literal: true

require "rails_helper"

RSpec.describe Components::ArchiveEntryCard, type: :component do
  let(:model) { create(:model) }
  let(:file) { create(:model_file, model: model, filename: "pack.zip") }
  let(:entry) { build_entry(status: "listed") }
  let(:html) { render described_class.new(entry: entry, file: file) }
  let(:slot) { Nokogiri::HTML.fragment(html).at_css(".archive-entry-preview-slot") }

  def build_entry(status:, preview_path: nil)
    ArchiveEntry.create!(
      model_file: file,
      pathname: "meshes/widget.stl",
      kind: "mesh",
      status: status,
      preview_path: preview_path,
      size: 2048
    )
  end

  it "keeps the pathname as a truncated caption, not a renderer canvas" do
    expect(html).to include('title="meshes/widget.stl"')
    expect(html).to include("truncate")
    expect(html).not_to include('data-controller="renderer"')
    expect(html).not_to include("ObjectPreview")
  end

  context "when a real preview PNG exists" do
    let(:entry) { build_entry(status: "preview_ready", preview_path: ".manyfold/derivatives/archives/widget.png") }

    before { allow(entry).to receive(:preview_exists?).and_return(true) }

    it "renders image_tag for the authenticated preview route" do
      preview_url = view_context.preview_model_model_file_archive_entry_path(model, file, entry)
      expect(html).to include("<img")
      expect(html).to include(preview_url)
      expect(html).to include("archive-entry-preview-image")
    end

    it "does not use a loading or failed slot" do
      expect(html).not_to include("archive-entry-preview-loading")
      expect(html).not_to include("archive-entry-preview-failed")
    end
  end

  shared_examples "a loading object slot" do
    it "shows a loading slot instead of a filename or img" do
      expect(html).to include("archive-entry-preview-loading")
      expect(html).not_to include("<img")
      expect(slot.text).not_to include("meshes/widget.stl")
      expect(slot.text).not_to include("widget.stl")
    end
  end

  context "when the mesh is listed" do
    let(:entry) { build_entry(status: "listed") }

    it_behaves_like "a loading object slot"
  end

  context "when the mesh is preview_pending" do
    let(:entry) { build_entry(status: "preview_pending") }

    it_behaves_like "a loading object slot"
  end

  context "when the mesh preview failed" do
    let(:entry) { build_entry(status: "preview_failed") }

    it "shows a failed affordance instead of a filename or img" do
      expect(html).to include("archive-entry-preview-failed")
      expect(html).not_to include("archive-entry-preview-loading")
      expect(html).not_to include("<img")
      expect(slot.text).not_to include("meshes/widget.stl")
      expect(slot.text).not_to include("widget.stl")
    end
  end

  # INIT-026/SPEC-006
  context "when the operator can update" do
    let(:entry) do
      ArchiveEntry.create!(
        model_file: file,
        pathname: "pics/inner.png",
        kind: "image",
        status: "preview_ready",
        preview_path: ".manyfold/derivatives/archives/inner.png"
      )
    end

    before do
      allow(controller).to receive(:policy).and_return(double(edit?: true, update?: true, destroy?: true, show?: true))
      allow(entry).to receive(:preview_exists?).and_return(true)
    end

    it "offers set-as-preview and a confirmed archive delete" do
      expect(html).to include(I18n.t("models.file.set_as_preview"))
      expect(html).to include(%(name="model[preview_archive_entry_id]"))
      expect(html).to include(I18n.t("models.gallery.delete_confirm_archive", archive: "pack.zip", name: entry.name))
      expect(html).to include(%(name="_method" value="delete"))
    end
  end

  context "when the caller cannot update" do
    let(:entry) do
      ArchiveEntry.create!(
        model_file: file,
        pathname: "pics/inner.png",
        kind: "image",
        status: "preview_ready",
        preview_path: ".manyfold/derivatives/archives/inner.png"
      )
    end

    before do
      allow(controller).to receive(:policy).and_return(double(edit?: false, update?: false, destroy?: false, show?: true))
      allow(entry).to receive(:preview_exists?).and_return(true)
    end

    it "omits archive delete confirm" do
      expect(html).not_to include(I18n.t("models.gallery.delete_confirm_archive", archive: "pack.zip", name: entry.name))
      expect(html).not_to include(%(name="_method" value="delete"))
    end
  end
end
