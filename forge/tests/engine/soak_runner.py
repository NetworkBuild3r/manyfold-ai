"""Real-data soak for the engine (not collected by pytest; run in a throwaway pod, never on
the control node): ``python soak_runner.py SAMPLE.tsv OUT.jsonl [workers]``.

SAMPLE.tsv rows: ``stratum<TAB>path[;path2;...]`` (volume sets in order). Each row is one
``process()`` call; results are appended as JSON lines, then summarized per stratum.
"""

from __future__ import annotations

import collections
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from forge.engine import Caps, ContainerRef, process


class CountSink:
    def __init__(self) -> None:
        self.members = 0
        self.bytes = 0
        self.kinds: collections.Counter = collections.Counter()
        self.refused: collections.Counter = collections.Counter()
        self.nested = 0
        self.nested_status: collections.Counter = collections.Counter()
        self.max_chain = 0
        self.triangles = 0

    def member(self, chain, sha256, size, kind, triangles, depth) -> None:
        self.members += 1
        self.bytes += size
        self.kinds[kind] += 1
        self.max_chain = max(self.max_chain, len(chain))
        self.triangles += triangles or 0

    def refused(self, chain, reason) -> None:
        self.refused[reason] += 1

    def nested_archive(self, chain, sha256, size) -> None:
        self.nested += 1

    def nested_result(self, chain, result) -> None:
        self.nested_status[
            result.status if result.status == "done" else result.reason
        ] += 1


def one(stratum: str, paths: list[str], scratch: Path) -> dict:
    sink = CountSink()
    t0 = time.monotonic()
    ref = ContainerRef("archive", tuple(Path(p) for p in paths), paths[0])
    res = process(ref, sink, Caps(), scratch)
    loose = None
    if res.reason == "unsupported_format" and res.format is None:
        # No archive signature at all: the sweep runner re-routes the file to loose hashing.
        lsink = CountSink()
        lres = process(
            ContainerRef("loose_batch", ref.paths, ref.display), lsink, Caps()
        )
        loose = {
            "status": lres.status,
            "members": lsink.members,
            "kinds": dict(lsink.kinds),
        }
    return {
        "loose_fallback": loose,
        "stratum": stratum,
        "paths": paths,
        "status": res.status,
        "reason": res.reason,
        "reader": res.reader,
        "format": res.format,
        "detail": res.detail,
        "secs": round(time.monotonic() - t0, 2),
        "csize": sum(os.path.getsize(p) for p in paths if os.path.exists(p)),
        "peak_rss_kb": res.peak_rss_kb,
        "max_depth": res.max_depth,
        "members_tree": sink.members,
        "bytes_tree": sink.bytes,
        "kinds": dict(sink.kinds),
        "refused": dict(sink.refused),
        "nested": sink.nested,
        "nested_status": dict(sink.nested_status),
        "triangles": sink.triangles,
    }


def main(sample: str, out: str, workers: int = 3) -> None:
    scratch = Path(os.environ.get("FORGE_SCRATCH", "/scratch"))
    rows = []
    for line in Path(sample).read_text().splitlines():
        if line.strip():
            stratum, p = line.split("\t", 1)
            rows.append((stratum, p.split(";")))
    results = []
    with open(out, "a") as f, ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(one, s, p, scratch) for s, p in rows]
        for fut in futures:
            r = fut.result()
            results.append(r)
            f.write(json.dumps(r) + "\n")
            f.flush()
            print(
                r["stratum"],
                r["status"],
                r["reason"],
                r["reader"],
                r["secs"],
                r["paths"][0][-60:],
                flush=True,
            )
    by = collections.defaultdict(list)
    for r in results:
        by[r["stratum"]].append(r)
    print(
        "\n| stratum | n | done | done % | readers | failures | members | GB in | MB/s | max RSS MiB |"
    )
    for s, rs in sorted(by.items()):
        done = [r for r in rs if r["status"] == "done"]
        readers = collections.Counter(r["reader"] for r in done)
        fails = collections.Counter(r["reason"] for r in rs if r["status"] != "done")
        secs = sum(r["secs"] for r in rs) or 1
        gb = sum(r["csize"] for r in rs) / 1e9
        print(
            f"| {s} | {len(rs)} | {len(done)} | {100 * len(done) / len(rs):.1f} | {dict(readers)} | "
            f"{dict(fails)} | {sum(r['members_tree'] for r in rs)} | {gb:.1f} | {gb * 1000 / secs:.1f} | "
            f"{max((r['peak_rss_kb'] or 0) for r in rs) / 1024:.0f} |",
            flush=True,
        )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 3)
