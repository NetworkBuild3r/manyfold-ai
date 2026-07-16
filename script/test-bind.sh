#!/bin/bash
set -e
umount /mnt/w 2>/dev/null || true
mkdir -p /mnt/w
mount -t drvfs -o metadata,uid=1000,gid=1000 'W:' /mnt/w
echo "Ubuntu categories: $(ls /mnt/w/3D-Prints | wc -l)"
ls /mnt/w/3D-Prints | head
echo "=== docker bind ==="
docker run --rm -v /mnt/w/3D-Prints:/data:ro alpine ls /data | head -20
echo "IN=$(docker run --rm -v /mnt/w/3D-Prints:/data:ro alpine ls /data/Anime | wc -l)"
