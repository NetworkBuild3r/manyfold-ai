# frozen_string_literal: true

# INIT-027/SPEC-010
require "rails_helper"

RSpec.describe "Model show gallery file chrome", :as_moderator do
  let(:model) { create(:model) }
  let!(:image) { create(:model_file, model: model, filename: "cover.jpg") }

  before { model.update!(preview_file: image) }

  describe "GET /models/:id" do
    it "keeps model DELETE in labeled overflow only" do # rubocop:todo RSpec/ExampleLength, RSpec/MultipleExpectations
      get model_path(model)
      expect(response).to have_http_status(:success)
      expect(response.body).to include(I18n.t("models.show.delete_model"))
      expect(response.body).to include(I18n.t("models.destroy.confirm"))
      doc = Nokogiri::HTML(response.body)
      toolbar = doc.at('[role="toolbar"][aria-label="Model actions"]')
      expect(toolbar).to be_present
      model_deletes = toolbar.css("form").select do |form|
        form.at('input[name="_method"][value="delete"]') &&
          form["action"].to_s.end_with?(model_path(model))
      end
      expect(model_deletes.size).to eq(1)
      expect(model_deletes.first.text).to include(I18n.t("models.show.delete_model"))
      expect(toolbar.at("a[data-method='delete']")).to be_nil
    end

    it "targets current-slide delete at the loose file, not the model" do
      get model_path(model)
      expect(response.body).to include(model_model_file_path(model, image))
      expect(response.body).to include(I18n.t("models.gallery.delete_confirm_loose"))
      expect(response.body).to include(I18n.t("models.gallery.delete_image"))
      expect(response.body).not_to include("hidden md:block")
    end

    it "renders file-card images contain-in-slot" do
      get model_path(model)
      expect(response.body).to include("aspect-square")
      expect(response.body).to include("object-contain")
    end
  end

  describe "GET /models/:id with an archive slide", :as_moderator do
    let(:zip) { create(:model_file, model: model, filename: "pack.zip") }
    let!(:entry) do
      ArchiveEntry.create!(
        model_file: zip,
        pathname: "pics/inner.png",
        kind: "image",
        status: "preview_ready",
        preview_path: "m/.manyfold/derivatives/archives/inner.png"
      )
    end

    it "targets archive-slide delete at the archive entry path" do
      get model_path(model)
      expect(response.body).to include(model_model_file_archive_entry_path(model, zip, entry))
      expect(response.body).to include(I18n.t("models.gallery.delete_confirm_archive", archive: "pack.zip", name: entry.name))
      expect(response.body).to include(I18n.t("models.gallery.delete_archive_member"))
    end
  end
end
