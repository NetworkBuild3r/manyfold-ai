# frozen_string_literal: true

# Provenance: INIT-026/SPEC-006
require "rails_helper"

RSpec.describe "Models gallery archive images" do
  let(:model) { create(:model) }
  let!(:loose) { create(:model_file, model: model, filename: "cover.jpg") }
  let!(:archive) { create(:model_file, model: model, filename: "pack.zip") }
  let!(:ready_entry) { create_image_entry(archive, "pics/inner.png") }

  def create_image_entry(file, pathname, status: "preview_ready")
    ArchiveEntry.create!(
      model_file: file,
      pathname: pathname,
      kind: "image",
      status: status,
      preview_path: "m/.manyfold/derivatives/archives/#{File.basename(pathname)}"
    )
  end

  def preview_url
    preview_model_model_file_archive_entry_path(model, archive, ready_entry)
  end

  def archive_delete_confirm
    I18n.t("models.gallery.delete_confirm_archive", archive: archive.filename, name: ready_entry.name)
  end

  describe "GET /models/:id/gallery", :as_member do
    it "includes the loose image and the ready archive image" do
      get gallery_model_path(model)
      expect(response).to have_http_status(:success)
      expect(response.body).to include("#{loose.to_param}.jpg")
      expect(response.body).to include(preview_url)
    end

    it "does not include pending archive images or mesh members" do
      create_image_entry(archive, "pics/pending.jpg", status: "preview_pending")
      mesh = ArchiveEntry.create!(
        model_file: archive,
        pathname: "meshes/part.stl",
        kind: "mesh",
        status: "preview_ready",
        preview_path: "m/.manyfold/derivatives/archives/part.png"
      )
      get gallery_model_path(model)
      expect(response.body).not_to include("pending.jpg")
      expect(response.body).not_to include(preview_model_model_file_archive_entry_path(model, archive, mesh))
    end
  end

  describe "GET /models/:id as a member", :as_member, :multiuser do
    it "does not expose archive rewrite-delete without update?" do
      get model_path(model)
      expect(response).to have_http_status(:success)
      expect(response.body).not_to include(archive_delete_confirm)
    end
  end

  describe "GET /models/:id", :as_moderator do
    it "shows the union carousel with loose and archive source labels" do
      get model_path(model)
      expect(response).to have_http_status(:success)
      expect(response.body).to include("#{loose.to_param}.jpg")
      expect(response.body).to include(preview_url)
      expect(response.body).to include(I18n.t("models.gallery.source_loose"))
      expect(response.body).to include(I18n.t("models.gallery.source_archive"))
    end
  end

  describe "PATCH /models/:id preview source", :as_moderator do
    before { model.update!(preview_file: loose) }

    it "sets a ready archive image as the base preview" do
      patch model_path(model), params: {model: {preview_archive_entry_id: ready_entry.id}}
      expect(response).to redirect_to(model_path(model))
      model.reload
      expect(model.preview_archive_entry).to eq(ready_entry)
      expect(model.preview_file).to be_nil
    end

    it "renders the archive preview on show after reload" do
      model.update!(preview_archive_entry: ready_entry)
      get model_path(model)
      expect(response.body).to include(preview_url)
    end

    it "rejects an archive entry that belongs to another model" do
      other_zip = create(:model_file, model: create(:model), filename: "other.zip")
      foreign = create_image_entry(other_zip, "pics/foreign.png")
      patch model_path(model), params: {model: {preview_archive_entry_id: foreign.id}}
      expect(response).to have_http_status(:unprocessable_content)
      expect(model.reload.preview_archive_entry_id).not_to eq(foreign.id)
    end
  end

  describe "DELETE archive member from gallery", :as_moderator do
    it "maps GET to show and DELETE to destroy" do
      path = model_model_file_archive_entry_path(model, archive, ready_entry)
      expect(Rails.application.routes.recognize_path(path, method: :get)).to include(action: "show")
      expect(Rails.application.routes.recognize_path(path, method: :delete)).to include(action: "destroy")
    end

    it "shows a turbo confirm that names the archive source" do
      get model_path(model)
      expect(response.body).to include(archive_delete_confirm)
      expect(response.body).to include("data-turbo-confirm")
      expect(response.body).to include(%(name="_method" value="delete"))
    end

    it "surfaces unsupported rewrite errors and leaves the entry" do
      svc = instance_spy(ArchiveEntryService)
      allow(ArchiveEntryService).to receive(:new).and_return(svc)
      allow(svc).to receive(:delete_member!).and_raise(ArchiveEntryService::UnsupportedFormat)
      delete model_model_file_archive_entry_path(model, archive, ready_entry)
      expect(response).to redirect_to(model_model_file_path(model, archive))
      expect(flash[:alert]).to eq(I18n.t("archive_entries.destroy.unsupported_format"))
      expect(ArchiveEntry.find_by(id: ready_entry.id)).to be_present
    end
  end

  describe "authorization", :after_first_run, :multiuser do
    before do
      member = create(:user)
      model.revoke_all_permissions(Role.find_by!(name: :member))
      model.grant_permission_to "preview", member
      sign_in member
    end

    it "does not show archive delete confirm on show" do
      get model_path(model)
      expect(response).to have_http_status(:success)
      expect(response.body).not_to include(archive_delete_confirm)
    end

    it "rejects archive member delete without update?" do
      delete model_model_file_archive_entry_path(model, archive, ready_entry)
      expect(response).to have_http_status(:forbidden)
      expect(ArchiveEntry.find_by(id: ready_entry.id)).to be_present
    end
  end
end
