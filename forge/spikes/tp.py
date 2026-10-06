#!/usr/bin/env python3
"""NFS read throughput. usage: tp.py FILELIST N_READERS [GiB_per_reader=4] [offset]  (distinct files per reader; read-only)"""
import sys, subprocess, time
files = [l.strip() for l in open(sys.argv[1]) if l.strip()]
n = int(sys.argv[2]); gib = int(sys.argv[3]) if len(sys.argv) > 3 else 4; off = int(sys.argv[4]) if len(sys.argv) > 4 else 0
t = time.time(); ps = []
for i in range(n):
    f = files[off + i]
    ps.append(subprocess.Popen(['dd', f'if={f}', 'of=/dev/null', 'bs=4M', f'count={gib*256}', 'iflag=direct','status=none']))
[p.wait() for p in ps]; d = time.time() - t
print(f'readers={n} gib_each={gib} secs={d:.1f} aggregate_MBps={n*gib*1024/d:.0f} per_reader_MBps={gib*1024/d:.0f}')
