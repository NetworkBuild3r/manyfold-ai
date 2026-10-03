#!/usr/bin/env python3
"""stratified sample from walk TSV. usage: sample.py WALK.tsv ROOT OUT.tsv seed per_stratum maxbytes"""
import sys, re, random, collections
walk, root, out, seed, per, maxb = sys.argv[1], sys.argv[2].rstrip('/'), sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
random.seed(seed)
cand = collections.defaultdict(list); parts = collections.defaultdict(list)
for line in open(walk):
    p, s, m, k = line.rstrip('\n').split('\t')
    if k != 'f': continue
    s = int(s); lp = p.lower()
    mt = re.search(r'\.part0*(\d+)\.rar$', lp)
    if mt:
        base = re.sub(r'\.part0*\d+\.rar$', '', lp)
        parts[base].append((int(mt.group(1)), p, s)); continue
    if lp.endswith('.zip'): cand['zip'].append((p, s))
    elif lp.endswith('.rar'): cand['rar'].append((p, s))
    elif lp.endswith('.7z'): cand['7z'].append((p, s))
    elif lp.endswith(('.tar.gz', '.tgz', '.tar', '.gz', '.bz2', '.xz')): cand['tar_gz'].append((p, s))
def sig(p):
    with open(f'{root}/{p}', 'rb') as f: return f.read(8)
rows = []
for fmt in ('zip', '7z', 'tar_gz'):
    c = [x for x in cand[fmt] if x[1] <= maxb]; random.shuffle(c)
    for p, s in c[:per]: rows.append((fmt, f'{root}/{p}'))
rar = [x for x in cand['rar'] if x[1] <= maxb]; random.shuffle(rar)
r4 = r5 = 0
for p, s in rar:
    if r4 >= per and r5 >= per: break
    try: g = sig(p)
    except OSError: continue
    if g.startswith(b'Rar!\x1a\x07\x01\x00') and r5 < per: rows.append(('rar5', f'{root}/{p}')); r5 += 1
    elif g.startswith(b'Rar!\x1a\x07\x00') and r4 < per: rows.append(('rar4', f'{root}/{p}')); r4 += 1
sets = [v for v in parts.values() if sum(x[2] for x in v) <= maxb * 3]; random.shuffle(sets)
for v in sets[:max(10, per // 4)]:
    v.sort(); rows.append(('rar_split', ';'.join(f'{root}/{x[1]}' for x in v)))
with open(out, 'w') as o:
    for st, p in rows: o.write(f'{st}\t{p}\n')
print({k: len(v) for k, v in cand.items()}, 'split sets', len(parts), 'sample', len(rows))
