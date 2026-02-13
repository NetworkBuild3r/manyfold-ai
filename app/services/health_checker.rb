# Shared health check logic for /health endpoint and rake health:check.
# Used by load balancers, Docker healthchecks, and worker container probes.
class HealthChecker
  # Returns [ok, reasons]. ok is true when all required checks pass.
  # reasons is an array of failed check names when ok is false.
  def self.run(sidekiq_required: nil)
    sidekiq_required = sidekiq_required.nil? ? (ENV.fetch("HEALTH_CHECK_SIDEKIQ", "1") != "0") : sidekiq_required

    reasons = []
    reasons << "database" unless check_database
    reasons << "redis" unless check_redis
    reasons << "sidekiq" if sidekiq_required && !check_sidekiq

    [reasons.empty?, reasons]
  end

  def self.check_database
    ActiveRecord::Base.connection.execute("SELECT 1")
    true
  rescue StandardError
    false
  end

  def self.check_redis
    Sidekiq.redis { |conn| conn.ping == "PONG" }
  rescue StandardError
    false
  end

  def self.check_sidekiq
    require "sidekiq/api"
    Sidekiq::ProcessSet.new.size > 0
  rescue StandardError
    false
  end
end
