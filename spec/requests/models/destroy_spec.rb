# frozen_string_literal: true

require "rails_helper"

RSpec.describe "Model destroy", :after_first_run do
  let(:user) { create(:admin) }
  let!(:model) { create(:model) }

  before { sign_in user }

  describe "DELETE /models/:id" do
    it "removes the card via turbo_stream when deleting from the library" do
      model_param = model.to_param
      expect {
        delete model_path(model),
          as: :turbo_stream,
          headers: {"HTTP_REFERER" => models_url}
      }.to change(Model, :count).by(-1)

      expect(response).to have_http_status(:ok)
      expect(response.media_type).to eq(Mime[:turbo_stream].to_s)
      expect(response.body).to include(%(action="remove"))
      expect(response.body).to include(%(target="#{Components::ModelCard.dom_id_for_param(model_param)}"))
    end

    it "redirects away when deleting from the show page" do
      delete model_path(model),
        as: :turbo_stream,
        headers: {"HTTP_REFERER" => model_url(model)}
      expect(response).to redirect_to(models_path)
    end
  end
end
