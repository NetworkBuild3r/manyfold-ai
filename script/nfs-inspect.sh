#!/bin/bash
echo "=== mounts ==="
mount | grep nfs || echo none
echo "=== df ==="
df -h /mnt/nfs-backups 2>&1 || true
echo "=== ls ==="
ls -la /mnt/nfs-backups 2>&1 || true
echo "=== rpcinfo ==="
rpcinfo -p 192.168.11.102 2>&1 | head -20 || true
echo "=== showmount ==="
showmount -e 192.168.11.102 2>&1 || true
echo "=== try remount verbose ==="
umount /mnt/nfs-backups 2>/dev/null || true
mkdir -p /mnt/nfs-backups
timeout 15 mount -v -t nfs -o vers=3,nolock,tcp 192.168.11.102:/volume1/Backups /mnt/nfs-backups 2>&1
echo RC=$?
ls -la /mnt/nfs-backups 2>&1 | head -30
test -d /mnt/nfs-backups/3D-Prints && ls /mnt/nfs-backups/3D-Prints | head -20
echo DONE
