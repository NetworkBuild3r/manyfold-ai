# frozen_string_literal: true

require "rails_helper"

RSpec.describe "Merge histories" do
  let(:library) { create(:library) }
  let(:target) { create(:model, library: library) }

  before do
    MergeHistory.create!(
      target_model: target,
      source_library_id: library.id,
      source_path: "Old/Source Model",
      source_name: "Source Model",
      moved_files: [
        {"id" => 1, "deduplicated" => false},
        {"id" => 2, "deduplicated" => true}
      ]
    )
  end

  context "when logged in as moderator", :as_moderator do
    it "lists merges with the merged model, target and file counts" do
      get "/merges"
      expect(response).to have_http_status(:ok)
      expect(response.body).to include("Source Model", target.name, "Old/Source Model")
      expect(response.body).to include("1 file moved", "1 duplicate dropped")
    end

    it "marks an undone merge as undone" do
      MergeHistory.update_all(undone_at: Time.current) # rubocop:disable Rails/SkipsModelValidations
      get "/merges"
      expect(response.body).to include("Undone")
    end

    it "is linked from the Problems page" do
      get "/problems"
      expect(response.body).to include(merge_histories_path)
    end
  end

  context "when logged in as a non-moderator", :as_contributor do
    it "denies access" do
      get "/merges"
      expect(response).to have_http_status(:not_found).or have_http_status(:forbidden)
    end
  end

  describe MergeHistory do
    let(:history) { described_class.first }

    it "counts adopted and deduplicated files" do
      expect(history.adopted_count).to eq 1
      expect(history.deduplicated_count).to eq 1
    end

    it "is undoable inside the window and not after" do
      expect(history).to be_undoable
      history.update!(created_at: (Model::UNMERGE_WINDOW + 1.day).ago)
      expect(history).not_to be_undoable
    end
  end
end
