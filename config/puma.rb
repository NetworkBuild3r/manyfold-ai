# This configuration file will be evaluated by Puma. The top-level methods that
# are invoked here are part of Puma's configuration DSL. For more information
# about methods provided by the DSL, see https://puma.io/puma/Puma/DSL.html.
#
# Puma starts a configurable number of processes (workers) and each process
# serves each request in a thread from an internal thread pool.
#
# Default is single-process (workers=0) to keep memory low for self-hosted /
# Docker setups. Raise WEB_CONCURRENCY only when you have RAM to spare.
#
workers_count = Integer(ENV.fetch("WEB_CONCURRENCY", 0))
if workers_count > 0
  workers workers_count
  # Load app once before forking so workers share copy-on-write pages.
  preload_app!
end

# The ideal number of threads per worker depends both on how much time the
# application spends waiting for IO operations and on how much you wish to
# prioritize throughput over latency.
#
# Keep the default modest: each thread holds a DB connection and stack.
# Override with RAILS_MAX_THREADS / RAILS_MIN_THREADS.
max_threads_count = Integer(ENV.fetch("RAILS_MAX_THREADS", 5))
min_threads_count = Integer(ENV.fetch("RAILS_MIN_THREADS", 2))
threads min_threads_count, max_threads_count

# Specifies the `worker_timeout` threshold that Puma will use to wait before
# terminating a worker in development environments.
#
worker_timeout 3600 if ENV.fetch("RAILS_ENV", "development") == "development"

# Specifies the `port` that Puma will listen on to receive requests; default is 3000.
# Support IPv6 by binding to host `::` instead of `0.0.0.0`
port(ENV.fetch("PORT", 3000), "::")

# Specifies the `environment` that Puma will run in.
#
environment ENV.fetch("RAILS_ENV") { "development" }

# Specifies the `pidfile` that Puma will use.
pidfile ENV.fetch("PIDFILE") { "tmp/pids/server.pid" }

# Allow puma to be restarted by `rails restart` command.
plugin :tmp_restart

# Run the Solid Queue supervisor inside of Puma for single-server deployments
plugin :solid_queue if ENV["SOLID_QUEUE_IN_PUMA"]
