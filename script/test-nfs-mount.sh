#!/bin/bash
set -x
python3 - <<'PY'
import socket
s=socket.socket()
s.settimeout(3)
try:
  s.connect(("192.168.11.102",2049))
  print("local", s.getsockname(), "remote", s.getpeername())
except Exception as e:
  print("err", e)
finally:
  s.close()
PY

sudo mkdir -p /mnt/nfs-backups
for opts in "vers=3,nolock,tcp" "vers=4" "vers=3,nolock,tcp,noresvport" "vers=3,nolock,tcp,sec=sys"; do
  sudo umount /mnt/nfs-backups 2>/dev/null
  echo "TRY $opts"
  if sudo mount -t nfs -o "$opts" 192.168.11.102:/volume1/Backups /mnt/nfs-backups 2>/tmp/nfserr; then
    echo SUCCESS
    ls /mnt/nfs-backups | head
    ls /mnt/nfs-backups/3D-Prints | head
    exit 0
  else
    cat /tmp/nfserr
  fi
done
exit 1
