# Internal health check for load balancers and containers.
# GET /health → 200 when DB, Redis (and optionally Sidekiq) are reachable, 503 otherwise.
# Response body is plain text; no internal details (DB name, host, etc.) are exposed.
#
# Env HEALTH_CHECK_SIDEKIQ=1 (default) verifies at least one Sidekiq process is registered
# for "fully operational" mode. Set to 0 for DB+Redis only.
class HealthController < ApplicationController
  skip_forgery_protection
  before_action :skip_all_app_filters

  def show
    ok, reasons = HealthChecker.run
    status = ok ? 200 : 503
    message = ok ? "OK" : "Service Unavailable: #{reasons.join(", ")}"
    render plain: message, status: status, content_type: "text/plain"
  end

  private

  def skip_all_app_filters
    # Ensure no auth, CSP, or other filters run for this endpoint
  end
end
