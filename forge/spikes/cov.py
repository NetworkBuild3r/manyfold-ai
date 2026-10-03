#!/usr/bin/env python3
"""INIT-032 SPEC-002 spike: libarchive coverage. Reads source READ-ONLY. Spool/scratch under $SCRATCH (local disk).
  cov.py one PATH [PATH...]     -> one JSON line (child process; reports own peak RSS)
  cov.py run SAMPLE.tsv OUT.tsv -> runs each sample row in a fresh child, appends result TSV
SAMPLE.tsv columns: stratum \t path[;path2;...] (volume-set paths in order) """
import os, sys, json, time, hashlib, resource, shutil, subprocess, tempfile
CAPS = dict(depth=3, member=8 << 30, total=64 << 30, ratio=200, secs=20 * 60, spool=24 << 30)
ARCH_EXT = ('.zip', '.rar', '.7z', '.tar', '.gz', '.tgz', '.bz2', '.xz', '.tar.gz', '.cbz', '.cbr')
SCRATCH = os.environ.get('SCRATCH', '/scratch')
class Fail(Exception):
    def __init__(s, reason): s.reason = reason
def is_arch(name): return name.lower().endswith(ARCH_EXT)
def open_reader(paths):
    import libarchive
    if len(paths) == 1: return libarchive.file_reader(paths[0])
    return libarchive.multi_file_reader(paths) if hasattr(libarchive, 'multi_file_reader') else libarchive.file_reader(paths[0])
def process(paths, depth, st, t0):
    if depth > CAPS['depth']: raise Fail('depth_exceeded')
    st['max_depth'] = max(st['max_depth'], depth)
    import libarchive
    try:
        rd = open_reader(paths)
        with rd as a:
            for e in a:
                if time.time() - t0 > CAPS['secs']: raise Fail('timeout')
                name = e.pathname or ''
                if e.isdir: continue
                if name.startswith('/') or '..' in name.split('/') or e.issym or e.islnk or not e.isreg:
                    st['refused'] += 1
                    for _ in e.get_blocks(): pass
                    continue
                if e.size is not None and e.size > CAPS['member']: raise Fail('member_too_large')
                h = hashlib.sha256(); n = 0
                spool = None
                if is_arch(name):
                    fd, spool = tempfile.mkstemp(dir=SCRATCH); f = os.fdopen(fd, 'wb')
                for b in e.get_blocks():
                    h.update(b); n += len(b)
                    if spool: f.write(b)
                    if n > CAPS['member']: raise Fail('member_too_large')
                st['members'] += 1; st['bytes'] += n
                if st['bytes'] > CAPS['total']: raise Fail('total_too_large')
                if spool:
                    f.close(); st['nested'] += 1
                    try: process([spool], depth + 1, st, t0)
                    except Fail as x: st['nested_fail'].append(x.reason)
                    finally: os.unlink(spool)
    except Fail: raise
    except libarchive.exception.ArchiveError as x:
        m = str(x).lower()
        raise Fail('encrypted' if 'encrypt' in m or 'passphrase' in m else 'missing_volume' if 'volume' in m else 'reader_error:' + str(x)[:80])
    except (MemoryError,): raise Fail('oom')
    except Exception as x: raise Fail('reader_error:' + type(x).__name__ + ':' + str(x)[:80])
def one(paths):
    st = dict(members=0, bytes=0, nested=0, nested_fail=[], refused=0, max_depth=0)
    t0 = time.time(); reason = None
    try: process(paths, 1, st, t0)
    except Fail as x: reason = x.reason
    csize = sum(os.path.getsize(p) for p in paths)
    st.update(paths=paths, ok=reason is None, reason=reason, secs=round(time.time() - t0, 2), csize=csize,
              rss_kb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, nested_fail=','.join(st['nested_fail'])[:200])
    print(json.dumps(st))
def run(sample, out):
    os.makedirs(SCRATCH, exist_ok=True)
    with open(out, 'a') as o:
        for line in open(sample):
            stratum, p = line.rstrip('\n').split('\t')
            paths = p.split(';')
            r = subprocess.run([sys.executable, __file__, 'one'] + paths, capture_output=True, text=True)
            try: j = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception:
                j = dict(paths=paths, ok=False, reason='oom' if r.returncode in (-9, 137) else 'child_crash:' + str(r.returncode), secs=0, csize=0, members=0, bytes=0, nested=0, rss_kb=0, max_depth=0, refused=0, nested_fail='')
            j['stratum'] = stratum
            o.write(json.dumps(j) + '\n'); o.flush()
if __name__ == '__main__':
    if sys.argv[1] == 'one': one(sys.argv[2:])
    else: run(sys.argv[2], sys.argv[3])
