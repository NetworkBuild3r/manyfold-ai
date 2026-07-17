#!/bin/ash
set -e
if [ -f tmp/pids/server.pid ]; then
  rm tmp/pids/server.pid
fi

echo "Preparing database..."
bundle exec rails db:prepare:with_data

echo "Setting database file ownership (SQLite3 only)..."
bundle exec rake db:chown

echo "Cleaning up old cache files..."
bundle exec rake tmp:cache:clear

echo "Setting temporary directory permissions..."
chown -R $PUID:$PGID tmp log

if [ ! -d $PLUGINS_PATH ]; then
  echo "Creating plugin directory..."
  mkdir -p "$PLUGINS_PATH"
fi
echo "Setting plugin directory owner..."
chown $PUID:$PGID "$PLUGINS_PATH"

# NEVER recursively chown network library mounts (NFS). Multi-TB trees stall PID 1 for hours.
# Set SKIP_LIBRARY_CHOWN=1 to force-skip. Check /libraries and /models (k8s mount).
for lib in /libraries /models; do
  if [ -d "$lib" ]; then
    if [ -n "${SKIP_LIBRARY_CHOWN}" ]; then
      echo "Skipping $lib chown (SKIP_LIBRARY_CHOWN set)."
    elif mount 2>/dev/null | grep -E " on ${lib}( |$)" | grep -qiE "nfs|cifs|smb|9p|fuse|drvfs|sshfs"; then
      echo "Skipping $lib chown (network mount detected)."
    else
      echo "Fixing ownership on $lib top-level entries only..."
      chown "$PUID:$PGID" "$lib" 2>/dev/null || true
      for entry in "$lib"/* "$lib"/.[!.]*; do
        [ -e "$entry" ] || continue
        chown "$PUID:$PGID" "$entry" 2>/dev/null || true
      done
    fi
  fi
done


echo "Launching application..."
export RAILS_PORT=$PORT
export RAILS_LOG_TO_STDOUT=true
exec s6-setuidgid $PUID:$PGID $@
