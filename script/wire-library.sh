#!/bin/bash
set -e
echo "=== docker socket ==="
ls -la /var/run/docker.sock 2>&1 || true
docker info >/tmp/dinfo 2>&1 && echo DOCKER_OK || { echo DOCKER_FAIL; head -20 /tmp/dinfo; }

echo "=== remount library via Windows network (drvfs) ==="
mkdir -p /mnt/3d-prints
if [ ! -d /mnt/3d-prints/Anime ]; then
  umount /mnt/3d-prints 2>/dev/null || true
  # Use Windows credential session for SMB
  mount -t drvfs -o metadata,uid=1000,gid=1000 '\\\\192.168.11.102\\Backups\\3D-Prints' /mnt/3d-prints
fi
ls /mnt/3d-prints | head -20
echo "ANIME=$(ls -1 /mnt/3d-prints/Anime 2>/dev/null | wc -l)"

if docker info >/dev/null 2>&1; then
  echo "=== test bind from Ubuntu path ==="
  docker run --rm -v /mnt/3d-prints:/data alpine ls /data | head -20
  echo "ANIME_IN_CONTAINER=$(docker run --rm -v /mnt/3d-prints:/data alpine ls /data/Anime | wc -l)"
fi
echo DONE
