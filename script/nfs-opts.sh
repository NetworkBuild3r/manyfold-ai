#!/bin/bash
# Try NFS option combos with short timeouts
mkdir -p /mnt/nfs-backups
umount /mnt/nfs-backups 2>/dev/null || true

opts_list=(
  "vers=3,proto=tcp,nolock,port=2049,mountport=892"
  "vers=3,proto=udp,nolock"
  "vers=3,tcp,nolock,soft,timeo=30,retrans=1"
  "nfsvers=3,addr=192.168.11.102,nolock"
)

for o in "${opts_list[@]}"; do
  echo "TRY: $o"
  umount /mnt/nfs-backups 2>/dev/null || true
  if timeout 10 mount -t nfs -o "$o" 192.168.11.102:/volume1/Backups /mnt/nfs-backups 2>/tmp/e; then
    echo SUCCESS
    ls /mnt/nfs-backups | head -10
    ls /mnt/nfs-backups/3D-Prints 2>/dev/null | head -10
    exit 0
  else
    echo FAIL rc=$?
    cat /tmp/e
  fi
done
echo ALL_FAILED
exit 1
