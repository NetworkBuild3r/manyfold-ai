#!/bin/bash
echo START
whoami
sudo -n true && echo SUDO_OK || echo SUDO_NEEDS_PASSWORD
mount | grep -i nfs || echo NO_NFS_MOUNT
ls -la /mnt/nfs-backups 2>&1 || echo NO_DIR
# timeout the mount so we don't hang forever
sudo mkdir -p /mnt/nfs-backups
echo ATTEMPTING_MOUNT
timeout 15 sudo mount -t nfs -o vers=3,nolock,tcp,timeo=50,retrans=1 192.168.11.102:/volume1/Backups /mnt/nfs-backups
rc=$?
echo MOUNT_RC=$rc
ls /mnt/nfs-backups 2>&1 | head -20
ls /mnt/nfs-backups/3D-Prints 2>&1 | head -20
echo DONE
