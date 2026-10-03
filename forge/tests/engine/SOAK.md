# Engine real-data soak (INIT-032/SPEC-006)

**Where:** throwaway pod `init032-engine-soak` (label `purpose=init032-engine-soak`), namespace `manyfold`, node `k82`,
`python:3.12-slim-bookworm` + apt `libarchive13` **3.6.2** + official static `7zz` 26.03 (sha256-pinned), memory limit
4 GiB, PVC `3d-prints` mounted `readOnly` at `/models`, scratch = 30 GiB `emptyDir`. Pod and ConfigMap deleted after
each pass; nothing was written under the source tree.

**What:** `soak_runner.py` over the SPEC-002 stratified sample (`forge-work/sample.tsv`, 193 rows, 60.7 GB compressed,
volume sets as one row), default `Caps()`, 3 containers in parallel, every container in its own isolated reader process.

## Final result — commit `ab5ef2275`

| stratum | n | done | done % | readers | typed failures | members (tree) | GB in | MB/s per container | max reader RSS MiB |
|---|---:|---:|---:|---|---|---:|---:|---:|---:|
| zip | 40 | 40 | **100.0** | libarchive 40 | — | 1,947 | 13.9 | 27.0 | 115 |
| 7z | 40 | 40 | **100.0** | libarchive 40 | — | 14,999 | 12.0 | 14.0 | 93 |
| rar5 | 40 | 40 | **100.0** | libarchive 40 | — | 1,031 | 13.7 | 40.1 | 62 |
| rar4 | 40 | 40 | **100.0** | libarchive 37, **7zz 3** | — | 1,285 | 7.2 | 23.2 | 58 |
| rar_split | 10 | 2 | 20.0 | libarchive 2 | `reader_error` 8 | 1,773 | 13.7 | 37.5 | 74 |
| `.gz` single files | 23 | 4 | 17.4 | stream 4 | `unsupported_format` 19 → loose re-route 19/19 done | 4 | 0.1 | 20.5 | 37 |

Totals: 21,039 members hashed (5,805 mesh, 14,798 image), 132.7 GB uncompressed, 1,773,751,669 STL triangles counted,
193 nested archives opened (all `done`), max depth 3 (4 containers), 0 refused members, reader peak RSS p50 37 MiB /
p95 89 MiB / max 114 MiB (ADR worker limit 2 GiB), slowest container 197 s (cap 5,400 s).

Targets: zip / 7z / rar5 = 100 % ✔; rar4 ≥ 97 % after 7zz ✔ (100 %; the 3 libarchive `File CRC error` archives from
SPEC-002 — *Fang Clan of Dogor*, *GOT Tyrion Lannister*, *Mazinger Z* — all succeed through 7zz with per-member CRC32
verification); multi-volume set **`Clorehaven and Goblin Grotto.part1-3.rar` done** via `archive_read_open_filenames`
(3 volumes, 935 members, 6.0 GB uncompressed, 80 s).

Agreement with the SPEC-002 spike reader: on the 158 archives both read successfully, member counts match on 157. The one
difference (*Rocket Pig Games – Shield Construct.7z*: spike 3, engine 5) is the spike under-counting: 7zz lists 5 regular
files; two carry the Windows sparse attribute (`AP`), which the spike's `isreg` test rejected.

## The non-successes are not engine coverage gaps

- **rar_split 8 × `reader_error`**: each row is a *single* `*.partN.rar` file in its own folder (e.g. `Skies of Sordane KS -
  Ships.part02/…part02.rar`, `…part11/…part11.rar`) — a mid-set or orphan volume, not a complete set. Both libarchive
  (`Too small block encountered`, `Truncated RAR file data`, `Unpacker has written too many bytes`) and 7zz (cannot open)
  reject them. Members before the break are recorded; the broken member is not (GR-004). The fix is in SPEC-005
  grouping: sibling volumes live in **sibling folders named after each part**, so grouping by directory alone misses them.
- **`.gz` 19 × `unsupported_format` (format=None)**: `model_file.bin.gz` / `*.osgjs.gz` web-viewer exports are plain JSON
  or raw binary despite the name (first bytes `{\n  "Generator":` / `8cfd0af5…`; no gzip magic). The runner re-routes them
  to `loose_batch` (19/19 hashed, kind `other`), which is what SPEC-007 must do (engine contract). The 4 real gzip files
  are hashed through the stream path.

## Defects the soak found (fixed before the final pass)

| pass | finding | fix |
|---|---|---|
| 1 (`26af6a6`) | 15 × 7z, 1 × zip, 1 × rar4, 1 × rar split failed `ratio_exceeded` with a *negative* compressed delta (`member 17825792 B from ~-501435270 B`) | `archive_filter_bytes` is an input position and seekable readers move it backwards; count forward progress only (`ffe6581`, regression test `test_large_compressible_members_are_not_bombs`) |
| 2 (`ffe6581`) | signature-less `*.gz` re-routed as loose files were labelled kind `archive`; one nested `.rar` part with no signature was opened as a child | archive kind needs an archive signature (`ab5ef22`, `test_archive_extension_without_signature_is_not_opened`) |

Pass 1 (pre-fix) already showed rar4 39/40 with all three CRC archives recovered by 7zz and the Clorehaven set done.

## Reproduce

```bash
tar -czf forge.tgz forge/pyproject.toml forge/src forge/tests/engine/soak_runner.py
kubectl -n manyfold create configmap init032-engine-soak --from-file=forge.tgz --from-file=fetch7z.py --from-file=sample.tsv
# pod: nodeSelector k82, image python:3.12-slim-bookworm, limits.memory 4Gi, PVC 3d-prints readOnly at /models,
# emptyDir /scratch; apt libarchive13; fetch7z.py (Dockerfile snippet, sha256-pinned); pip install ./forge;
# python forge/tests/engine/soak_runner.py /code/sample.tsv /out/soak.jsonl 3
kubectl -n manyfold delete pod,configmap -l purpose=init032-engine-soak
```
