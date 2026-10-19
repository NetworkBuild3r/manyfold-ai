require "rails_helper"

RSpec.describe "Follows", :multiuser do
  let(:user) { create(:user) }
  let(:model) { create(:model, :public) }
  let(:follows_path) { "/models/#{model.to_param}/follows" }

  before { sign_in user }

  describe "POST /create" do
    it "adds a follow relationship for the current user" do
      expect { post follows_path }.to change(Federails::Following, :count).by(1)
      expect(user).to be_following(model)
    end

    it "redirects back to the followed item" do
      post follows_path
      expect(response).to redirect_to(model)
    end

    it "does not add another follow relationship if one already exists" do
      post follows_path
      expect { post follows_path }.not_to change(Federails::Following, :count)
    end

    it "is denied when signed out" do
      sign_out user
      expect { post follows_path }.not_to change(Federails::Following, :count)
    end
  end

  describe "DELETE /" do
    it "removes the follow relationship for the current user" do
      post follows_path
      expect { delete follows_path }.to change(Federails::Following, :count).by(-1)
      expect(user).not_to be_following(model)
    end

    it "works even if the current user is not following the target" do
      expect { delete follows_path }.not_to change(Federails::Following, :count)
      expect(response).to redirect_to(model)
    end
  end
end
