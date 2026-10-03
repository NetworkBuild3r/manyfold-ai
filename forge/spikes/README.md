# SPEC-002 feasibility spikes (read-only)

These scripts measured the live `3D-Prints` tree for INIT-032/SPEC-002. They
are **read-only against the source**: they never create, unlink, rename, or
open-for-write any path under the library root. Scratch/spool (coverage) must
be a local disk directory via `$SCRATCH`, never a path under the source.

| File | What it does |
| --- | --- |
| `walk.py` | Multi-thread `os.scandir` stat walk. Writes a TSV of relpath / size / mtime_ns / kind. Never follows symlinks. |
| `sample.py` | Stratified sample from a walk TSV (zip / rar / 7z / split volumes / gz). |
| `sample.tsv` | The sample used for the coverage run. |
| `cov.py` | One sequential libarchive pass per sample row (SHA-256 every member, nest ≤ 3). Child process per archive; peak RSS reported. |
| `coverage-results.jsonl.gz` | Raw per-archive coverage rows from the 191-archive run. |
| `tp.py` | NFS `dd iflag=direct` throughput with N concurrent readers. |

Do not point these at production except from a read-only mount. See
`design/INIT-032-feasibility-report.md` for the numbers they produced.
