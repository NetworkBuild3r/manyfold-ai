#!/bin/ash
set -e
if [ -f tmp/pids/server.pid ]; then
  rm tmp/pids/server.pid
fi

# Wait for PostgreSQL to accept connections (safety net on top of depends_on)
if [ -n "${DATABASE_HOST}" ]; then
  echo "Waiting for PostgreSQL at ${DATABASE_HOST}..."
  tries=0
  until bundle exec rails runner "ActiveRecord::Base.connection.execute('SELECT 1')" 2>/dev/null; do
    tries=$((tries + 1))
    if [ "$tries" -ge 60 ]; then
      echo "PostgreSQL did not become ready in time."
      exit 1
    fi
    sleep 1
  done
  echo "PostgreSQL is ready."
fi

# Only web runs migrations to avoid ConcurrentMigrationError when multiple containers start.
if [ -z "${SKIP_MIGRATIONS}" ]; then
  echo "Preparing database..."
  bundle exec rails db:prepare:with_data
else
  echo "Skipping migrations (SKIP_MIGRATIONS set)."
fi

# Ensure app user can write to config and library paths
if [ -d /config ] && [ -n "${PUID}" ] && [ "${PUID}" != "0" ]; then
  chown -R "$PUID:$PGID" /config
fi
if [ -d /libraries ] && [ -n "${PUID}" ] && [ "${PUID}" != "0" ]; then
  chown -R "$PUID:$PGID" /libraries 2>/dev/null || true
fi

echo "Cleaning up old cache files..."
bundle exec rake tmp:cache:clear

echo "Setting temporary directory permissions..."
chown -R "${PUID:-0}:${PGID:-0}" tmp log 2>/dev/null || true

echo "Launching application..."
export RAILS_PORT=$PORT
export RAILS_LOG_TO_STDOUT=true
exec "$@"
