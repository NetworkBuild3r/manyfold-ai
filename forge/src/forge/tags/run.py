"""`forge tags` — searchable tags for every pack, deterministic first, one LLM call per pack.

Per pack, in order (earlier tags first in the stored list; when the list is capped the tail goes):

1. **code** (derive.py): category, creator, source, file formats, supports, scale, part kinds,
   has-preview — from catalog names and paths;
2. **LLM** (judge.py): ONE schema-bound call (temperature 0, json_schema strict, <= 4 in flight)
   returning franchise / characters / genre / object type / art style, from names and paths only;
3. **classify**: the keywords `forge classify` stored for the pack (spark-curate keywords + its
   own LLM tags), or the owner's classify override tags.

The union is stable-ordered and capped; owner overrides (``tag_overrides``: add / remove /
replace) always win. Results are cached in ``tag_decisions`` by an input fingerprint + prompt hash
(the model is recorded, never part of the key), so a rerun with unchanged inputs makes no call.
The merged list is written to ``packs.tags`` together with ``tags_fingerprint``; ``forge classify``
then leaves ``tags`` alone for that pack. Packs are processed in waves and each wave is committed,
so a killed run resumes where it stopped. Packs in the active materialize plan go first.

INIT-032/SPEC-016
"""

from __future__ import annotations

import json
import posixpath
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from forge.config import require_db_url
from forge.packs.llm import LlmEndpoint, fingerprint, map_concurrent
from forge.packs.resolve import acquire_lock, release_lock
from forge.packs.sqlutil import copy_rows, temp_table
from forge.tags import judge
from forge.tags.derive import (
    MESH_EXTS,
    RULES_VERSION,
    PackFacts,
    components,
    derive_tags,
    extension,
)
from forge.tags.normalize import merge_tags, normalise_tags

# Any HTTP / transport error is retried on the next run: a 404 after the served model changed, a
# 429 or a dropped connection say nothing about the evidence and must not be cached as `unsure`.
RETRYABLE_ERROR_PREFIXES = ("transport:", "http ", "no attempt")
WAVE = 100  # packs per wave: facts -> LLM -> write -> commit
PATH_CAP = 3000  # member paths read per pack (sorted, so the cut is deterministic)
EVIDENCE_PATHS = 8
EVIDENCE_FILES = 20
EVIDENCE_FOLDERS = 20
EVIDENCE_STR = 120


@dataclass
class TagsResult:
    counts: dict
    dry_run: bool
    model: str | None = None
    top_tags: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class PackRow:
    id: int
    name: str | None
    category: str | None
    creator: str | None
    source_tag: str | None
    tags: list[str]
    tags_fingerprint: str | None
    classify_fingerprint: str | None
    in_plan: bool
    units: list[tuple] = field(default_factory=list)  # (key, kind, path, mesh_count, images)
    paths: list[str] = field(default_factory=list)


@dataclass
class Work:
    pack: PackRow
    det: list[str]
    base: list[str]
    evidence: dict
    lfp: str
    override: tuple[list[str], list[str], list[str] | None]  # add, remove, replace
    llm: judge.TagVerdict | None = None


def run(
    *,
    dry_run: bool = False,
    db_url: str | None = None,
    use_llm: bool = True,
    llm_limit: int | None = None,
    endpoint: LlmEndpoint | None = None,
    concurrency: int = 4,
    pack_ids: list[int] | None = None,
    limit: int | None = None,
    log=None,
) -> TagsResult:
    if not dry_run and use_llm and endpoint is None:
        endpoint = LlmEndpoint.from_env()  # fails before any DB write
    log = log or (lambda msg: print(msg, file=sys.stderr, flush=True))
    engine = create_engine(db_url or require_db_url(), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            acquire_lock(conn)
            conn.commit()
            try:
                job = _Tagger(
                    conn,
                    endpoint if use_llm and not dry_run else None,
                    dry_run,
                    max(1, min(4, int(concurrency))),
                    log,
                )
                counts = job.run(pack_ids, limit, llm_limit)
                model = job.endpoint.model if job.endpoint is not None else None
                top = job.top_tags(30)
                if dry_run:
                    conn.rollback()
                else:
                    conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                release_lock(conn)
                conn.commit()
    finally:
        engine.dispose()
    return TagsResult(counts=counts, dry_run=dry_run, model=model, top_tags=top)


def _clamp(s: str, n: int = EVIDENCE_STR) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


class _Tagger:
    def __init__(self, conn, endpoint, dry_run, concurrency, log) -> None:
        self.conn: Connection = conn
        self.endpoint: LlmEndpoint | None = endpoint
        self.dry_run = dry_run
        self.concurrency = concurrency
        self.log = log
        self.counts: Counter[str] = Counter()
        self.llm_budget: int | None = None
        self.final_sizes: list[int] = []
        self.tag_freq: Counter[str] = Counter()
        self.llm_seconds = 0.0

    def _q(self, sql: str, **params):
        return self.conn.execute(text(sql), params)

    # ----------------------------------------------------------------------------- driver
    def run(self, pack_ids: list[int] | None, limit: int | None, llm_limit: int | None) -> dict:
        self.llm_budget = llm_limit
        packs = self._select(pack_ids, limit)
        self.counts["packs"] = len(packs)
        self.counts["packs_in_plan"] = sum(1 for p in packs if p.in_plan)
        if pack_ids:
            self.counts["packs_not_found"] = len(set(pack_ids) - {p.id for p in packs})
        for start in range(0, len(packs), WAVE):
            wave = packs[start : start + WAVE]
            self._wave(wave)
            if not self.dry_run:
                self.conn.commit()
            self.log(f"tags: packs {min(start + WAVE, len(packs))}/{len(packs)}")
        self._summarize()
        return dict(sorted(self.counts.items()))

    def _select(self, pack_ids: list[int] | None, limit: int | None) -> list[PackRow]:
        plan = self._q(
            "SELECT id FROM materialize_plans WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        ).scalar()
        rows = self._q(
            """
            SELECT p.id, p.name, p.category, p.creator, p.source_tag, p.tags,
                   p.tags_fingerprint, p.classify_fingerprint,
                   EXISTS (SELECT 1 FROM materialize_packs m
                           WHERE m.plan_id = CAST(:plan AS bigint) AND m.pack_id = p.id) AS in_plan
            FROM packs p
            WHERE p.status <> 'provisional'
              AND EXISTS (SELECT 1 FROM pack_units u WHERE u.pack_id = p.id)
              AND (CAST(:ids AS bigint[]) IS NULL OR p.id = ANY(CAST(:ids AS bigint[])))
            ORDER BY in_plan DESC, p.id
            LIMIT CAST(:lim AS bigint)
            """,
            plan=plan,
            ids=pack_ids or None,
            lim=limit,
        ).all()
        return [
            PackRow(r[0], r[1], r[2], r[3], r[4], list(r[5] or []), r[6], r[7], r[8]) for r in rows
        ]

    # ------------------------------------------------------------------------------- wave
    def _wave(self, wave: list[PackRow]) -> None:
        self._load_facts(wave)
        base = self._classify_tags(wave)
        overrides = self._overrides(wave)
        works = [self._work(p, base.get(p.id, []), overrides.get(p.id)) for p in wave]
        cache = self._cache([w.lfp for w in works])
        jobs: list[Work] = []
        for w in works:
            hit = cache.get(w.lfp)
            if hit is not None:
                w.llm = hit
                self.counts["llm_cached"] += 1
            else:
                jobs.append(w)
        self.counts["llm_needed"] += len(jobs)
        todo = jobs
        if self.endpoint is None:
            todo = []
        elif self.llm_budget is not None:
            todo = jobs[: max(0, self.llm_budget)]
        self.counts["llm_deferred"] += len(jobs) - len(todo)
        self._call(todo)
        self._write(works)

    def _call(self, todo: list[Work]) -> None:
        endpoint = self.endpoint
        if not todo or endpoint is None:
            return
        started = time.monotonic()
        for w, result in map_concurrent(
            lambda w: judge.tag_pack(endpoint, w.evidence), todo, self.concurrency
        ):
            # Audit data, never a cache key: read after the call (a 404 may have re-resolved it).
            self._insert_decision(w, result, endpoint.model)
            self.counts["llm_called"] += 1
            if result.verdict != "ok":
                self.counts["llm_unsure"] += 1
            if not (result.error or "").startswith(RETRYABLE_ERROR_PREFIXES):
                w.llm = result
            if self.llm_budget is not None:
                self.llm_budget -= 1
            if self.counts["llm_called"] % 10 == 0:
                if not self.dry_run:
                    self.conn.commit()
                self.log(f"tags: llm {self.counts['llm_called']} calls")
        self.llm_seconds += time.monotonic() - started

    # ----------------------------------------------------------------------------- facts
    def _load_facts(self, wave: list[PackRow]) -> None:
        by_id = {p.id: p for p in wave}
        ids = list(by_id)
        for pid, key, kind, path, meshes, images in self._q(
            """
            SELECT pack_id, unit_key, kind, path, mesh_count, image_count
            FROM pack_units WHERE pack_id = ANY(CAST(:ids AS bigint[]))
            ORDER BY pack_id, mesh_count DESC, unit_key
            """,
            ids=ids,
        ):
            by_id[pid].units.append((key, kind, path, int(meshes), int(images)))
        truncated: set[int] = set()
        for pid, path, total in self._q(
            """
            WITH RECURSIVE s(pack_id, cid) AS (
                SELECT pc.pack_id, pc.container_id FROM pack_containers pc
                WHERE pc.pack_id = ANY(CAST(:ids AS bigint[]))
                UNION
                SELECT s.pack_id, c.id FROM containers c JOIN s ON c.parent_container_id = s.cid
            ),
            m AS (
                SELECT s.pack_id, array_to_string(o.member_chain, '/') AS path
                FROM s JOIN occurrences o ON o.container_id = s.cid
                UNION
                SELECT pu.pack_id, sf.path
                FROM pack_units pu
                JOIN pack_unit_sources pus ON pus.unit_id = pu.id
                JOIN source_files sf ON sf.id = pus.source_file_id
                WHERE pu.pack_id = ANY(CAST(:ids AS bigint[])) AND pu.kind = 'loose' AND pu.present
            ),
            r AS (
                SELECT pack_id, path,
                       row_number() OVER (PARTITION BY pack_id ORDER BY path) AS rn,
                       count(*) OVER (PARTITION BY pack_id) AS total
                FROM m
            )
            SELECT pack_id, path, total FROM r WHERE rn <= :cap ORDER BY pack_id, path
            """,
            ids=ids,
            cap=PATH_CAP,
        ):
            by_id[pid].paths.append(path)
            if total > PATH_CAP:
                truncated.add(pid)
        if truncated:
            self.counts["paths_truncated_packs"] += len(truncated)

    def _classify_tags(self, wave: list[PackRow]) -> dict[int, list[str]]:
        """The tags `forge classify` decided: its decision row for the pack's classify
        fingerprint, replaced by the owner's classify override tags when one exists."""
        ids = [p.id for p in wave]
        out: dict[int, list[str]] = {}
        for pid, tags in self._q(
            """
            SELECT p.id, d.tags FROM packs p
            JOIN LATERAL (
                SELECT x.tags FROM classify_decisions x
                WHERE x.input_fingerprint = p.classify_fingerprint
                  AND coalesce(x.evidence->>'row', 'record') = 'record'
                ORDER BY x.id DESC LIMIT 1
            ) d ON true
            WHERE p.id = ANY(CAST(:ids AS bigint[]))
            """,
            ids=ids,
        ):
            out[pid] = list(tags or [])
        human: dict[int, list[str]] = {}
        for pid, tags in self._q(
            """
            SELECT u.pack_id, o.tags FROM classify_overrides o
            JOIN pack_units u ON u.unit_key = o.unit_key
            WHERE u.pack_id = ANY(CAST(:ids AS bigint[])) AND o.tags IS NOT NULL
            ORDER BY u.pack_id, o.unit_key
            """,
            ids=ids,
        ):
            human.setdefault(pid, list(tags))  # first unit key wins, as in `forge classify`
        out.update(human)
        # Packs never classified keep whatever tags they already carry (spark keywords).
        for p in wave:
            if p.id not in out and p.tags_fingerprint is None:
                out[p.id] = list(p.tags)
        return out

    def _overrides(self, wave: list[PackRow]) -> dict[int, tuple]:
        rows = self._q(
            """
            SELECT u.pack_id, o.add_tags, o.remove_tags, o.set_tags
            FROM tag_overrides o JOIN pack_units u ON u.unit_key = o.unit_key
            WHERE u.pack_id = ANY(CAST(:ids AS bigint[]))
            ORDER BY u.pack_id, o.unit_key
            """,
            ids=[p.id for p in wave],
        )
        out: dict[int, tuple] = {}
        for pid, add, remove, set_tags in rows:
            a, r, s = out.get(pid, ([], [], None))
            out[pid] = (
                a + list(add or []),
                r + list(remove or []),
                list(set_tags) if set_tags is not None and s is None else s,
            )
        return out

    # ------------------------------------------------------------------------- derivation
    def _work(self, p: PackRow, base: list[str], override) -> Work:
        unit_paths = tuple(u[2] for u in p.units)
        facts = PackFacts(
            category=p.category,
            creator=p.creator,
            source_tag=p.source_tag,
            name=p.name,
            unit_paths=unit_paths,
            member_paths=tuple(p.paths),
            image_count=sum(u[4] for u in p.units),
        )
        det = derive_tags(facts)
        evidence = self._evidence(p)
        lfp = fingerprint({"evidence": evidence, "prompt": judge.PROMPT_HASH})
        return Work(
            pack=p,
            det=det,
            base=normalise_tags(base, cap=None),
            evidence=evidence,
            lfp=lfp,
            override=override or ([], [], None),
        )

    def _evidence(self, p: PackRow) -> dict:
        units = sorted(p.units, key=lambda u: (-u[3], u[0]))
        files, seen_files = [], set()
        folders, seen_folders = [], set()
        for path in p.paths:
            comps = components(path)
            for d in comps[:-1]:
                if d.casefold() not in seen_folders:
                    seen_folders.add(d.casefold())
                    folders.append(d)
            if comps and extension(path) in MESH_EXTS:
                name = posixpath.basename(path)
                if name.casefold() not in seen_files:
                    seen_files.add(name.casefold())
                    files.append(name)
        return {
            "name": _clamp(p.name or ""),
            "category": p.category,
            "creator": p.creator,
            "source": p.source_tag,
            "paths": [_clamp(u[2]) for u in units[:EVIDENCE_PATHS]],
            "more_paths": max(0, len(units) - EVIDENCE_PATHS),
            "folders": [_clamp(f) for f in folders[:EVIDENCE_FOLDERS]],
            "mesh_names": [_clamp(f) for f in files[:EVIDENCE_FILES]],
        }

    # -------------------------------------------------------------------------------- cache
    def _cache(self, lfps: list[str]) -> dict[str, judge.TagVerdict]:
        rows = self._q(
            """
            SELECT DISTINCT ON (input_fingerprint) input_fingerprint, verdict, tags, raw_tags, error
            FROM tag_decisions
            WHERE prompt_hash = :ph AND input_fingerprint = ANY(CAST(:fps AS text[]))
            ORDER BY input_fingerprint, id DESC
            """,
            ph=judge.PROMPT_HASH,
            fps=lfps,
        ).all()
        out = {}
        for fp, verdict, tags, raw, error in rows:
            if error and error.startswith(RETRYABLE_ERROR_PREFIXES):
                continue
            out[fp] = judge.TagVerdict(verdict, list(tags or []), list(raw or []), error)
        return out

    def _insert_decision(self, w: Work, res: judge.TagVerdict, model: str | None) -> None:
        self._q(
            """
            INSERT INTO tag_decisions (input_fingerprint, prompt_hash, model, verdict, tags,
                raw_tags, error, evidence)
            VALUES (:fp, :ph, :model, :verdict, :tags, :raw, :error, CAST(:ev AS jsonb))
            """,
            fp=w.lfp,
            ph=judge.PROMPT_HASH,
            model=model,
            verdict=res.verdict,
            tags=res.tags,
            raw=res.raw,
            error=res.error,
            ev=json.dumps({"input": w.evidence}, ensure_ascii=False),
        )

    # -------------------------------------------------------------------------------- write
    def _final(self, w: Work) -> tuple[list[str], str]:
        add, remove, replace = w.override
        llm_tags = w.llm.tags if w.llm is not None and w.llm.verdict == "ok" else None
        final = merge_tags(w.det, llm_tags or [], w.base, add=add, remove=remove, replace=replace)
        fp = fingerprint(
            {
                "rules": RULES_VERSION,
                "prompt": judge.PROMPT_HASH,
                "det": w.det,
                "base": w.base,
                "llm": llm_tags,
                "override": [add, remove, replace],
            }
        )
        return final, fp

    def _write(self, works: list[Work]) -> None:
        rows = []
        for w in works:
            final, fp = self._final(w)
            self.final_sizes.append(len(final))
            self.tag_freq.update(final)
            if w.llm is not None and w.llm.verdict == "ok":
                self.counts["with_llm_tags"] += 1
            p = w.pack
            if p.tags_fingerprint == fp and p.tags == final:
                self.counts["unchanged"] += 1
                continue
            self.counts["tags_written"] += 1
            rows.append((p.id, final, fp))
        if not rows or self.dry_run:
            return
        temp_table(self.conn, "tmp_tags", "pack_id bigint PRIMARY KEY, tags text[], fp text")
        copy_rows(self.conn, "tmp_tags", ("pack_id", "tags", "fp"), rows)
        self._q(
            """
            UPDATE packs p SET tags = t.tags, tags_fingerprint = t.fp, tagged_at = now(),
                   updated_at = now()
            FROM tmp_tags t WHERE p.id = t.pack_id
            """
        )

    def _summarize(self) -> None:
        sizes = sorted(self.final_sizes)
        if sizes:
            self.counts["tags_per_pack_min"] = sizes[0]
            self.counts["tags_per_pack_median"] = int(statistics.median(sizes))
            self.counts["tags_per_pack_p90"] = sizes[min(len(sizes) - 1, int(len(sizes) * 0.9))]
            self.counts["tags_per_pack_max"] = sizes[-1]
            self.counts["packs_with_no_tags"] = sum(1 for s in sizes if s == 0)
        self.counts["distinct_tags"] = len(self.tag_freq)
        if self.counts.get("llm_called") and self.llm_seconds > 0:
            self.counts["llm_seconds"] = round(self.llm_seconds, 1)
            self.counts["llm_calls_per_minute"] = round(
                self.counts["llm_called"] * 60 / self.llm_seconds, 1
            )

    def top_tags(self, n: int = 30) -> list[tuple[str, int]]:
        return self.tag_freq.most_common(n)
