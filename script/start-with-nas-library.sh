#!/bin/bash
# Mount organized NAS library via W: (drvfs) — Docker Desktop can bind this path.
# Direct UNC mounts under /mnt/3d-prints often appear empty inside containers.
set -euo pipefail

PROJECT="/mnt/c/Users/BrianNelson/Projects/manyfold-ai"
MOUNT_POINT="/mnt/w/3D-Prints"

echo "==> Ensuring W: is mounted at /mnt/w"
mkdir -p /mnt/w
if [ ! -d "${MOUNT_POINT}/Anime" ]; then
  umount /mnt/w 2>/dev/null || true
  mount -t drvfs -o metadata,uid=1000,gid=1000 'W:' /mnt/w
fi

echo "==> Categories:"
ls "${MOUNT_POINT}"
ANIME_COUNT=$(ls -1 "${MOUNT_POINT}/Anime" | wc -l)
echo "Anime model dirs: ${ANIME_COUNT}"
if [ "${ANIME_COUNT}" -lt 10 ]; then
  echo "ERROR: mount looks empty/wrong; aborting"
  exit 1
fi

echo "==> Smoke-test Docker bind of library"
docker run --rm -v "${MOUNT_POINT}:/data:ro" alpine ls /data | head -20
IN_CT=$(docker run --rm -v "${MOUNT_POINT}:/data:ro" alpine ls /data/Anime | wc -l)
echo "Anime dirs visible in container: ${IN_CT}"
if [ "${IN_CT}" -lt 10 ]; then
  echo "ERROR: Docker cannot see library files via bind mount"
  exit 1
fi

cd "${PROJECT}"
export LIBRARY_MOUNT="${MOUNT_POINT}"
export SKIP_LIBRARY_CHOWN=1

if grep -q '^LIBRARY_MOUNT=' .env 2>/dev/null; then
  sed -i "s|^LIBRARY_MOUNT=.*|LIBRARY_MOUNT=${MOUNT_POINT}|" .env
else
  echo "LIBRARY_MOUNT=${MOUNT_POINT}" >> .env
fi
if grep -q '^SKIP_LIBRARY_CHOWN=' .env 2>/dev/null; then
  sed -i 's|^SKIP_LIBRARY_CHOWN=.*|SKIP_LIBRARY_CHOWN=1|' .env
else
  echo "SKIP_LIBRARY_CHOWN=1" >> .env
fi

echo "==> Recreate web/workers"
docker compose up -d --force-recreate web worker worker_perf

echo "==> Wait for Sidekiq (must not stick on chown)"
for i in $(seq 1 60); do
  if docker compose exec -T worker ps aux 2>/dev/null | grep -q '[s]idekiq'; then
    echo "worker sidekiq is up"
    break
  fi
  if [ $((i % 5)) -eq 0 ]; then
    echo "still waiting for sidekiq..."
    docker compose exec -T worker ps aux 2>/dev/null | head -5 || true
  fi
  sleep 2
done

echo "==> Wait for web healthy"
for i in $(seq 1 40); do
  if docker compose exec -T web wget -q -O - http://localhost:3214/health >/dev/null 2>&1; then
    echo "web healthy"
    break
  fi
  sleep 3
done

echo "==> Verify library inside web container"
docker compose exec -T web sh -c 'ls /libraries/prints | head -20; echo ANIME=$(ls /libraries/prints/Anime | wc -l)'

echo "==> Enqueue full filesystem scan (streaming walk)"
docker cp "${PROJECT}/script/enqueue_full_scan.rb" manyfold-ai-web-1:/tmp/enqueue_full_scan.rb
docker compose exec -T web bundle exec rails runner /tmp/enqueue_full_scan.rb

echo "==> Snapshot"
docker compose exec -T worker ps aux | head -8
docker compose logs worker --tail 25
echo "DONE"
