# frozen_string_literal: true

require "rails_helper"

RSpec.describe ArchiveEntriesController, :after_first_run, type: :request do
  let(:user) { create(:admin) }
  let(:model) { create(:model) }
  let(:file) { create(:model_file, model: model, filename: "pack.zip", previewable: true) }

  before do
    120.times do |i|
      ArchiveEntry.create!(
        model_file: file,
        pathname: format("parts/part_%03d.stl", i),
        kind: "mesh",
        status: "listed"
      )
    end
  end

  describe "GET #index turbo_stream" do
    before { sign_in user }

    it "returns a page of entries and has_more when more remain" do
      get model_model_file_archive_entries_path(model, file, offset: 0, per_page: 100),
        as: :turbo_stream

      expect(response).to have_http_status(:ok)
      expect(response.media_type).to eq(Mime[:turbo_stream].to_s)
      expect(response.body).to include("archive-entry-card")
      expect(response.body).to include(I18n.t("archive_entries.panel.load_more"))
    end

    it "omits load more on the final page" do
      get model_model_file_archive_entries_path(model, file, offset: 100, per_page: 100),
        as: :turbo_stream

      expect(response).to have_http_status(:ok)
      expect(response.body).not_to include(I18n.t("archive_entries.panel.load_more"))
    end
  end

  describe "preview-only vs view authz", :multiuser do
    let(:member) { create(:user) }
    let(:entry) { file.archive_entries.first }

    before do
      model.revoke_all_permissions(Role.find_by!(name: :member))
      sign_in member
    end

    context "with preview grant only" do
      before { model.grant_permission_to "preview", member }

      it "denies archive index listing" do
        get model_model_file_archive_entries_path(model, file)
        expect(response).to have_http_status(:forbidden)
      end

      it "denies archive member download" do
        get download_model_model_file_archive_entry_path(model, file, entry)
        expect(response).to have_http_status(:forbidden)
      end

      it "denies archive member content" do
        get content_model_model_file_archive_entry_path(model, file, entry)
        expect(response).to have_http_status(:forbidden)
      end
    end

    context "with view grant" do
      before { model.grant_permission_to "view", member }

      it "allows archive index listing" do
        get model_model_file_archive_entries_path(model, file)
        expect(response).to have_http_status(:ok)
      end
    end
  end

  describe "DELETE #destroy", :multiuser do
    let(:member) { create(:user) }
    let(:entry) { file.archive_entries.first }

    it "maps DELETE to destroy and GET to show (CSRF-safe, no GET mutate)" do
      path = model_model_file_archive_entry_path(model, file, entry)
      expect(Rails.application.routes.recognize_path(path, method: :get)).to include(action: "show")
      expect(Rails.application.routes.recognize_path(path, method: :delete)).to include(action: "destroy")
    end

    context "when the caller can update the model" do
      before { sign_in user }

      it "authorizes update? and invokes the rewrite-delete service" do
        svc = instance_spy(ArchiveEntryService)
        allow(ArchiveEntryService).to receive(:new).and_return(svc)

        delete model_model_file_archive_entry_path(model, file, entry)

        expect(svc).to have_received(:delete_member!).with(entry)
        expect(response).to redirect_to(model_model_file_path(model, file))
        expect(flash[:notice]).to eq(I18n.t("archive_entries.destroy.success"))
      end
    end

    context "with preview grant only" do
      before do
        model.revoke_all_permissions(Role.find_by!(name: :member))
        model.grant_permission_to "preview", member
        sign_in member
      end

      it "denies archive member delete" do
        delete model_model_file_archive_entry_path(model, file, entry)
        expect(response).to have_http_status(:forbidden)
        expect(ArchiveEntry.find_by(id: entry.id)).to be_present
      end
    end

    context "with view grant only" do
      before do
        model.revoke_all_permissions(Role.find_by!(name: :member))
        model.grant_permission_to "view", member
        sign_in member
      end

      it "denies archive member delete" do
        delete model_model_file_archive_entry_path(model, file, entry)
        expect(response).to have_http_status(:forbidden)
        expect(ArchiveEntry.find_by(id: entry.id)).to be_present
      end
    end
  end
end
