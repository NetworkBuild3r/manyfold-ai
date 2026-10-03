#!/usr/bin/env python3
"""INIT-032 SPEC-002/005 spike: exact-size stat walk. Never follows symlinks, never writes under root.
usage: walk.py ROOT OUT.tsv [threads]  -> TSV: relpath \t size \t mtime_ns \t kind(f|l|o)"""
import os, sys, time, threading, queue
root, out = sys.argv[1].rstrip('/'), sys.argv[2]
nthreads = int(sys.argv[3]) if len(sys.argv) > 3 else 8
q = queue.Queue(); lock = threading.Lock()
q.put(root); pending = [1]; stats = {'files': 0, 'dirs': 0, 'bytes': 0, 'errors': 0}
f = open(out, 'w', buffering=1 << 20)
t0 = time.time()
def work():
    global pending
    while True:
        d = q.get()
        if d is None: return
        buf = []
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            buf.append((e.path, 0, 0, 'l')); continue
                        if e.is_dir(follow_symlinks=False):
                            with lock:
                                stats["dirs"] += 1; pending[0] += 1
                            q.put(e.path)
                        elif e.is_file(follow_symlinks=False):
                            st = e.stat(follow_symlinks=False)
                            buf.append((e.path, st.st_size, st.st_mtime_ns, 'f'))
                        else: buf.append((e.path, 0, 0, 'o'))
                    except OSError: 
                        with lock: stats['errors'] += 1
        except OSError:
            with lock: stats['errors'] += 1
        with lock:
            for p, s, m, k in buf:
                f.write(f"{os.path.relpath(p, root)}\t{s}\t{m}\t{k}\n")
                if k == 'f': stats['files'] += 1; stats['bytes'] += s
            pending_done()
def pending_inc():
    pending[0] += 1
def pending_done():
    pending[0] -= 1
    if pending[0] == 0:
        for _ in range(nthreads): q.put(None)
ts = [threading.Thread(target=work) for _ in range(nthreads)]
[t.start() for t in ts]
def rep():
    while any(t.is_alive() for t in ts):
        time.sleep(30); print(f"{time.time()-t0:.0f}s {stats}", file=sys.stderr, flush=True)
threading.Thread(target=rep, daemon=True).start()
[t.join() for t in ts]; f.close()
print(f"DONE {time.time()-t0:.0f}s {stats}", file=sys.stderr, flush=True)
