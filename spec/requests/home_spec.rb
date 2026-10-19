require "rails_helper"

# root GET    /                                                                       home#index

RSpec.describe "Home" do
  context "when signed out" do
    context "when multiuser is enabled", :after_first_run, :multiuser do
      it "shows the home page without exposing private models" do
        private_model = create(:model, name: "Hidden private thing")
        public_model = create(:model, :public, name: "Visible public thing")
        get "/"
        expect(response).to have_http_status(:ok)
        expect(response.body).not_to include(private_model.name)
        expect(response.body).to include(public_model.name)
      end
    end
  end

  context "when signed in" do
    describe "GET /" do
      it "redirects to library creation if there isn't one already", :as_member do
        get "/"
        expect(response).to redirect_to("/libraries/new")
      end

      it "shows the homepage if a library has been created", :as_member do
        create(:library)
        get "/"
        expect(response).to have_http_status(:success)
      end
    end
  end
end
