#!/bin/ash
set -e

# Refuse to run as root; require PUID/PGID for a non-root user
if [ "${PUID}" = "0" ] || [ "${PGID}" = "0" ]; then
  echo "Manyfold must not run as root. Set PUID and PGID to a non-root user (e.g. 1000:1000)."
  exit 1
fi

if [ -f tmp/pids/server.pid ]; then
  rm tmp/pids/server.pid
fi

# Solo mode: start Redis in this container when REDIS_URL points to localhost
case "${REDIS_URL}" in
  redis://127.0.0.1*|redis://localhost*)
    echo "Solo mode: starting Redis..."
    redis-server &
    ;;
esac

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
  if [ -f db/schema.rb ]; then
    echo "Preparing database (loading schema.rb then data migrations)..."
  else
    echo "Preparing database (full schema + data migrations; consider generating db/schema.rb for faster boots)..."
  fi
  if ! bundle exec rails db:prepare:with_data 2>&1; then
    echo "ERROR: Database preparation failed. Migration status below:"
    bundle exec rails db:migrate:status 2>&1 || true
    echo "Data migration status:"
    bundle exec rails db:data:migrate:status 2>&1 || echo "(data migration status unavailable)"
    exit 1
  fi
else
  echo "Skipping migrations (SKIP_MIGRATIONS set)."
fi

# Use runtime user for PUID:PGID (built-in manyfold for 1000:1000, else create appuser)
if [ "$PUID" = "1000" ] && [ "$PGID" = "1000" ]; then
  RUN_USER=manyfold
else
  addgroup -g "$PGID" appgroup 2>/dev/null || true
  adduser -D -u "$PUID" -G appgroup appuser 2>/dev/null || true
  RUN_USER=appuser
fi

# Ensure app user can write to config and library paths
if [ -d /config ]; then
  chown -R "$PUID:$PGID" /config
fi
# NEVER recursively chown network library mounts (NFS/SMB/9p/drvfs). On a multi-thousand
# model NAS tree this can run for hours, freeze workers at PID 1, and look like Docker is hung.
# Set SKIP_LIBRARY_CHOWN=1 to force-skip, or leave unset to auto-detect network FS types.
if [ -d /libraries ]; then
  if [ -n "${SKIP_LIBRARY_CHOWN}" ]; then
    echo "Skipping /libraries chown (SKIP_LIBRARY_CHOWN set)."
  else
    lib_fs="$(stat -f -c %T /libraries 2>/dev/null || stat -f /libraries 2>/dev/null || echo unknown)"
    # Also check mount table for network-ish mounts under /libraries
    if mount 2>/dev/null | grep -E ' on /libraries' | grep -qiE 'nfs|cifs|smb|9p|fuse|drvfs|sshfs'; then
      echo "Skipping /libraries chown (network mount detected in mount table)."
    elif echo "$lib_fs" | grep -qiE 'nfs|cifs|smb|9p|fuse|drvfs|sshfs'; then
      echo "Skipping /libraries chown (network filesystem type: $lib_fs)."
    else
      # Local/disk only: still avoid deep recursion on huge trees by only fixing top-level dirs.
      # Full recursive chown of large libraries is a known startup stall.
      echo "Fixing ownership on /libraries top-level entries only (not recursive)..."
      chown "$PUID:$PGID" /libraries 2>/dev/null || true
      for entry in /libraries/* /libraries/.[!.]*; do
        [ -e "$entry" ] || continue
        chown "$PUID:$PGID" "$entry" 2>/dev/null || true
      done
    fi
  fi
fi

echo "Cleaning up old cache files..."
bundle exec rake tmp:cache:clear

echo "Setting temporary directory permissions..."
chown -R "$PUID:$PGID" tmp log 2>/dev/null || true
[ -d storage ] && chown -R "$PUID:$PGID" storage 2>/dev/null || true

echo "Launching application..."
export RAILS_PORT=$PORT
export RAILS_LOG_TO_STDOUT=true
# Drop privileges: run CMD as RUN_USER (su-exec does not parse our args, so -b etc. are safe)
exec su-exec "$RUN_USER" "$@"
