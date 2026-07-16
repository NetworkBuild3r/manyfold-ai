#!/bin/bash
set -e
sudo mkdir -p /mnt/nfs-backups
if [ ! -d /mnt/nfs-backups/3D-Prints ]; then
  sudo umount /mnt/nfs-backups 2>/dev/null || true
  sudo mount -t nfs -o vers=3,nolock,tcp,rw 192.168.11.102:/volume1/Backups /mnt/nfs-backups
fi
echo "MOUNT_OK"
ls /mnt/nfs-backups/3D-Prints
echo "ANIME_COUNT=$(ls -1 /mnt/nfs-backups/3D-Prints/Anime | wc -l)"
echo "DC_COUNT=$(ls -1 /mnt/nfs-backups/3D-Prints/DC | wc -l)"
# Docker CLI check
if docker info >/dev/null 2>&1; then
  echo "DOCKER_OK"
  docker version --format '{{.Server.Version}}'
else
  echo "DOCKER_NOT_READY"
  ls -la /var/run/docker.sock 2>/dev/null || true
  ls -la /mnt/wsl/docker-desktop/shared-sockets/ 2>/dev/null || true
fi
