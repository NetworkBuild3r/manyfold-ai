#!/bin/bash
# Wire Ubuntu docker CLI to Docker Desktop engine via shared sockets / npiperelay paths
set -e
echo "Looking for docker socket proxies..."
find /mnt/wsl /run /var/run -name '*docker*' 2>/dev/null | head -50
ls -la /mnt/wsl/docker-desktop/shared-sockets/guest-services/ 2>/dev/null || true
ls -la /mnt/wsl/docker-desktop/shared-sockets/host-services/ 2>/dev/null || true

# Docker Desktop sometimes places the socket after distro is "linked"
# Try common locations
for p in \
  /var/run/docker.sock \
  /mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.sock \
  /mnt/wsl/docker-desktop/shared-sockets/host-services/docker.proxy.sock \
  /mnt/wsl/docker-desktop/shared-sockets/host-services/docker.sock
 do
  if [ -S "$p" ]; then
    echo "FOUND socket: $p"
    export DOCKER_HOST="unix://$p"
    docker version && exit 0
  fi
done

# Try using docker.exe from Windows path inside WSL (interop)
if [ -x "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]; then
  echo "Trying Windows docker.exe via interop..."
  "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" version 2>&1 | head -30
fi

echo "No working docker socket found"
exit 1
