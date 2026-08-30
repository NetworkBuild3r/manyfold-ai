# frozen_string_literal: true

require "rails_helper"

# INIT-013/SPEC-003 — admin performance HTML shell + KPI JSON authz
RSpec.describe "Admin performance" do
  describe "GET /admin/performance" do
    context "when signed out" do
      it "redirects to sign in" do
        get "/admin/performance"
        expect(response).to redirect_to("/users/sign_in")
      end

      it "rejects unauthenticated JSON" do
        get "/admin/performance.json"
        # Devise HTML → redirect; JSON/API-style → 401
        expect(response).to have_http_status(:unauthorized).or be_redirect
      end
    end

    context "when signed in as non-admin", :as_member do
      it "denies HTML access" do
        get "/admin/performance"
        # Devise admin constraint → 404; Pundit alone would be 403
        expect(response).to have_http_status(:forbidden).or have_http_status(:not_found)
      end

      it "denies JSON access" do
        get "/admin/performance.json"
        expect(response).to have_http_status(:forbidden).or have_http_status(:not_found)
      end
    end

    context "when signed in as administrator", :as_administrator do
      let(:telemetry_result) do
        Performance::Telemetry::Result.new(
          p50: 12.5,
          p95: 40.0,
          p99: 55.0,
          throughput: [{datetime: "20260830T0800", rpm: 2}],
          sample_count: 3,
          budget_exceeded: false
        )
      end

      before do
        telemetry = instance_double(Performance::Telemetry, call: telemetry_result)
        allow(Performance::Telemetry).to receive(:new).and_return(telemetry)
      end

      it "returns HTML success" do
        get "/admin/performance"
        expect(response).to have_http_status(:success)
        expect(response.body).to include("Performance dashboard shell")
      end

      # rubocop:disable RSpec/ExampleLength, RSpec/MultipleExpectations
      it "returns KPI JSON from Performance::Telemetry" do
        get "/admin/performance.json"
        expect(response).to have_http_status(:success)
        json = response.parsed_body
        expect(json).to include(
          "p50" => 12.5,
          "p95" => 40.0,
          "p99" => 55.0,
          "sample_count" => 3,
          "budget_exceeded" => false
        )
        expect(json["throughput"]).to eq([{"datetime" => "20260830T0800", "rpm" => 2}])
      end
      # rubocop:enable RSpec/ExampleLength, RSpec/MultipleExpectations
    end
  end
end
