# frozen_string_literal: true

require "rails_helper"

RSpec.describe ArchiveEntriesController, :after_first_run, type: :request do
  let(:user) { create(:admin) }
  let(:model) { create(:model) }
  let(:file) { create(:model_file, model: model, filename: "pack.zip") }

  before do
    sign_in user
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
end
