require "rails_helper"

RSpec.describe "GET /health" do
  # Test env has no Sidekiq workers; use DB+Redis-only check
  around do |example|
    orig = ENV["HEALTH_CHECK_SIDEKIQ"]
    ENV["HEALTH_CHECK_SIDEKIQ"] = "0"
    example.run
  ensure
    ENV["HEALTH_CHECK_SIDEKIQ"] = orig
  end

  it "returns 200 OK when database and Redis are reachable" do
    get "/health"
    expect(response).to have_http_status(:ok)
    expect(response.body).to eq("OK")
    expect(response.media_type).to eq("text/plain")
  end

  context "when Sidekiq check is required and workers are present" do
    before do
      allow(HealthChecker).to receive(:run).and_return([true, []])
    end

    it "returns 200 OK" do
      get "/health"
      expect(response).to have_http_status(:ok)
      expect(response.body).to eq("OK")
    end
  end

  context "when a check fails" do
    before do
      allow(HealthChecker).to receive(:run).and_return([false, %w[database]])
    end

    it "returns 503 with reason in body" do
      get "/health"
      expect(response).to have_http_status(:service_unavailable)
      expect(response.body).to eq("Service Unavailable: database")
    end
  end
end
