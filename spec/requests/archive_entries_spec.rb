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
        expect(response).to have_http_status(:not_found)
      end

      it "denies archive member download" do
        get download_model_model_file_archive_entry_path(model, file, entry)
        expect(response).to have_http_status(:not_found)
      end

      it "denies archive member content" do
        get content_model_model_file_archive_entry_path(model, file, entry)
        expect(response).to have_http_status(:not_found)
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
end
