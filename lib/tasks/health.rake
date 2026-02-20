# Rake task for health checks used by worker containers (no web server).
# Usage: bundle exec rails health:check
# Exits 0 if healthy, 1 otherwise.
# Workers only need DB+Redis; set HEALTH_CHECK_SIDEKIQ=1 to also require Sidekiq (e.g. from web).
namespace :health do
  desc "Verify DB and Redis (and optionally Sidekiq). Exits 0 if healthy, 1 otherwise."
  task check: :environment do
    # Worker containers: DB+Redis only (they are Sidekiq; no need to check process set).
    # Web container uses /health endpoint which checks Sidekiq by default.
    sidekiq_required = ENV.fetch("HEALTH_CHECK_SIDEKIQ", "0") != "0"
    ok, reasons = HealthChecker.run(sidekiq_required: sidekiq_required)
    if ok
      puts "OK"
      exit 0
    else
      warn "Service Unavailable: #{reasons.join(", ")}"
      exit 1
    end
  end
end
