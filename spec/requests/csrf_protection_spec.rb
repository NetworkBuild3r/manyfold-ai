# frozen_string_literal: true

# INIT-027/SPEC-013 — VULN-027-005: enable forgery protection only in this file.
require "rails_helper"

RSpec.describe "HTML CSRF verification", :after_first_run do
  around do |example|
    previous = ActionController::Base.allow_forgery_protection
    ActionController::Base.allow_forgery_protection = true
    example.run
  ensure
    ActionController::Base.allow_forgery_protection = previous
  end

  let(:creator) { create(:creator) }

  def authenticity_token_from(html)
    doc = Nokogiri::HTML5.parse(html)
    doc.at('meta[name="csrf-token"]')&.[]("content") ||
      doc.at('input[name="authenticity_token"]')&.[]("value")
  end

  describe "unsafe HTML" do
    it "rejects a mutation without an authenticity token", :as_moderator do
      patch "/creators/#{creator.to_param}", params: {creator: {name: "forged"}}
      expect(response).to have_http_status(:unprocessable_content)
      expect(creator.reload.name).not_to eq("forged")
    end

    it "reaches authorization when a valid token is present", :as_contributor do
      get "/creators"
      token = authenticity_token_from(response.body)
      expect(token).to be_present

      patch "/creators/#{creator.to_param}",
        params: {authenticity_token: token, creator: {name: "authed"}}
      expect(response).to have_http_status(:forbidden)
      expect(creator.reload.name).not_to eq("authed")
    end

    it "updates when a moderator submits a valid token", :as_moderator do
      get "/creators/#{creator.to_param}/edit"
      token = authenticity_token_from(response.body)
      expect(token).to be_present

      patch "/creators/#{creator.to_param}",
        params: {authenticity_token: token, creator: {slug: "csrf-ok"}}
      expect(response).to redirect_to("/creators/csrf-ok")
    end
  end

  describe "Manyfold API Bearer mutation", :multiuser do
    it "accepts a write-scoped mutation without a CSRF token" do
      access = create(:oauth_access_token, scopes: "write")
      patch "/creators/#{creator.to_param}",
        params: {name: "api-no-csrf"}.to_json,
        headers: {
          "Authorization" => "Bearer #{access.plaintext_token}",
          "Accept" => Mime[:manyfold_api_v0].to_s,
          "Content-Type" => Mime[:manyfold_api_v0].to_s
        }
      expect(response).to have_http_status(:success)
      expect(creator.reload.name).to eq("api-no-csrf")
    end
  end
end
