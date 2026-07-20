# frozen_string_literal: true

require "rails_helper"

RSpec.describe "Model personal list toggles", :after_first_run do
  let(:user) { create(:user) }
  let(:model) { create(:model) }

  before { sign_in user }

  describe "POST /models/:id/toggle_favorite" do
    it "toggles favorite and returns turbo streams that replace card controls" do
      expect {
        post toggle_favorite_model_path(model), as: :turbo_stream
      }.to change { user.reload.favorited_model?(model) }.from(false).to(true)

      expect(response).to have_http_status(:ok)
      expect(response.media_type).to eq(Mime[:turbo_stream].to_s)
      expect(response.body).to include(%(target="#{Components::ModelListActions.dom_id_for(model)}"))
      expect(response.body).to include(%(target="#{Components::ModelCardStatusPills.dom_id_for(model)}"))
      expect(response.body).to include("bi-heart-fill")
    end

    it "falls back to redirect for HTML requests" do
      post toggle_favorite_model_path(model)
      expect(response).to redirect_to(model_path(model))
      expect(user.reload.favorited_model?(model)).to be(true)
    end
  end

  describe "POST /models/:id/toggle_queue" do
    it "toggles queue without a full-page redirect when turbo_stream" do
      post toggle_queue_model_path(model), as: :turbo_stream
      expect(response).to have_http_status(:ok)
      expect(response.media_type).to eq(Mime[:turbo_stream].to_s)
      expect(user.reload.queued_model?(model)).to be(true)
      expect(response.body).to include("bi-bookmark-fill")
    end
  end
end
