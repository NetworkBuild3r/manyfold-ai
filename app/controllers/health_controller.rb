# Internal health check for load balancers and containers.
# GET /health → 200 when DB, Redis (and optionally Sidekiq) are reachable, 503 otherwise.
# Response body is plain text; no internal details (DB name, host, etc.) are exposed.
#
# Env HEALTH_CHECK_SIDEKIQ=1 (default) verifies at least one Sidekiq process is registered
# for "fully operational" mode. Set to 0 for DB+Redis only.
class HealthController < ApplicationController
  skip_forgery_protection
  skip_before_action :authenticate_user!, raise: false
  skip_before_action :check_for_first_use, raise: false
  skip_before_action :show_security_alerts, raise: false
  skip_before_action :check_scan_status, raise: false
  skip_before_action :restore_failed_search, raise: false
  skip_after_action :verify_authorized, raise: false
  skip_after_action :verify_policy_scoped, raise: false

  def show
    ok, reasons = HealthChecker.run
    status = ok ? 200 : 503
    message = ok ? "OK" : "Service Unavailable: #{reasons.join(", ")}"
    render plain: message, status: status, content_type: "text/plain"
  end
end
