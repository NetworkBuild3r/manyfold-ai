"""`forge classify` — category, folder name, creator, source and tags for every resolved pack.

Deterministic first: the pack's current top-level folder when it is a category, spark-curate
metadata (datapackage.json title / keywords / creator), cleaned folder or archive names. Sources
(AnySTL, Cults3D, Gumroad, ...) become `source_tag`, never a category. The LLM only places packs
code cannot (closed list enforced by schema and re-checked); unsure or low confidence -> Misc +
needs_review. `Unknown` is never an outcome. Human overrides (classify_overrides) win.

Results are cached in classify_decisions by an input fingerprint (units + their mesh-set hashes +
metadata file stats + rule/prompt version), so a re-run with unchanged inputs makes no LLM call.

INIT-032/SPEC-011
"""

from __future__ import annotations

import json
import posixpath
import sys
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from forge.classify import judge as cls_judge
from forge.classify.datapackage import DATAPACKAGE, SPARK_META, MetaReader, ModelMeta
from forge.classify.names import (
    NameRequest,
    assign_names,
    clamp,
    clean_name,
    finalize,
    fs_safe,
    hash8,
    is_weak,
    strip_archive_ext,
)
from forge.classify.vocab import (
    CATEGORIES,
    FALLBACK_CATEGORY,
    folder_category,
    folder_source,
    keyword_category,
    source_keyword,
)
from forge.config import optional_env, require_db_url
from forge.packs.llm import LlmEndpoint, fingerprint, map_concurrent
from forge.packs.resolve import acquire_lock, release_lock
from forge.packs.sqlutil import copy_rows, temp_table

RULES_VERSION = "classify-rules-v1"
RETRYABLE_ERROR_PREFIXES = ("transport:", "http 5", "no attempt")
DEFAULT_MIN_CONFIDENCE = 0.6


@dataclass
class UnitInfo:
    key: str
    kind: str
    path: str
    model_root: str | None
    coloc_root: str | None
    mesh_count: int
    set_hash: str | None
    role: str | None


@dataclass
class PackInfo:
    id: int
    name: str | None
    units: list[UnitInfo] = field(default_factory=list)

    @property
    def primary(self) -> UnitInfo:
        for u in self.units:
            if u.role == "primary":
                return u
        return max(self.units, key=lambda u: (u.mesh_count, u.key))


@dataclass
class Record:
    category: str
    display_name: str
    creator: str | None
    source_tag: str | None
    tags: list[str]
    decided_by: str
    confidence: float
    reasons: list[str]
    verdict: str = "ok"
    error: str | None = None
    evidence: dict = field(default_factory=dict)


@dataclass
class ClassifyResult:
    counts: dict
    dry_run: bool


def run(
    *,
    dry_run: bool = False,
    db_url: str | None = None,
    use_llm: bool = True,
    llm_limit: int | None = None,
    endpoint: LlmEndpoint | None = None,
    source_root: str | None = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    concurrency: int = 4,
    log=None,
) -> ClassifyResult:
    if not dry_run and use_llm and endpoint is None:
        endpoint = LlmEndpoint.from_env()
    log = log or (lambda msg: print(msg, file=sys.stderr, flush=True))
    root = source_root if source_root is not None else optional_env("FORGE_SOURCE_ROOT")
    reader = MetaReader(root)
    if not reader.enabled:
        log("classify: FORGE_SOURCE_ROOT unset or missing — datapackage seed disabled")
    engine = create_engine(db_url or require_db_url(), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            acquire_lock(conn)
            conn.commit()
            try:
                c = _Classifier(
                    conn,
                    reader,
                    endpoint if use_llm else None,
                    dry_run,
                    min_confidence,
                    concurrency,
                    log,
                )
                counts = c.run(llm_limit)
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
    return ClassifyResult(counts=counts, dry_run=dry_run)


def _majority(values: list[str]) -> str | None:
    if not values:
        return None
    tally = Counter(values)
    best = max(tally.values())
    winners = sorted(v for v, n in tally.items() if n == best)
    return winners[0] if len(winners) == 1 else None


def _dedupe(tags: list[str]) -> list[str]:
    seen, out = set(), []
    for t in tags:
        k = t.casefold()
        if t and k not in seen:
            seen.add(k)
            out.append(t)
    return out[:40]


class _Classifier:
    def __init__(self, conn, reader, endpoint, dry_run, min_confidence, concurrency, log) -> None:
        self.conn: Connection = conn
        self.reader: MetaReader = reader
        self.endpoint: LlmEndpoint | None = endpoint
        self.dry_run = dry_run
        self.min_conf = min_confidence
        self.concurrency = concurrency
        self.log = log
        self.counts: Counter[str] = Counter()

    def _q(self, sql: str, **params):
        return self.conn.execute(text(sql), params)

    def run(self, llm_limit: int | None) -> dict:
        packs = self._load_packs()
        self.counts["packs"] = len(packs)
        meta_stats = self._meta_stats()
        cache = self._cache()
        overrides = {
            r[0]: r[1:]
            for r in self._q(
                "SELECT unit_key, category, name, creator, tags FROM classify_overrides"
            )
        }

        records: dict[int, Record] = {}
        fps: dict[int, str] = {}
        fresh: list[int] = []
        llm_queue: list[tuple[PackInfo, Record, dict]] = []
        for p in packs:
            fp = self._fingerprint(p, meta_stats)
            fps[p.id] = fp
            hit = cache.get(fp)
            if hit is not None:
                records[p.id] = hit
                self.counts["cached"] += 1
                continue
            rec, needs_llm = self._deterministic(p)
            records[p.id] = rec
            if needs_llm:
                llm_queue.append((p, rec, self._llm_evidence(p, rec)))
            else:
                fresh.append(p.id)

        self.counts["llm_needed"] = len(llm_queue)
        todo = llm_queue
        if self.endpoint is None or self.dry_run:
            todo = []
        elif llm_limit is not None:
            todo = llm_queue[:llm_limit]
        deferred = llm_queue[len(todo) :]
        for p, rec, _ev in deferred:
            rec.category = FALLBACK_CATEGORY
            rec.reasons = ["classify_deferred"]
            rec.decided_by = "deterministic"
            rec.confidence = 0.0
        self.counts["llm_deferred"] = len(deferred)

        endpoint = self.endpoint
        done = 0
        for (p, rec, ev), result in map_concurrent(
            lambda item: cls_judge.classify(endpoint, item[2]), todo, self.concurrency
        ):
            self._apply_llm(p, rec, ev, result)
            self._insert(fps[p.id], rec, endpoint.model if endpoint else None)
            done += 1
            self.counts["llm_called"] += 1
            if done % 10 == 0:
                if not self.dry_run:
                    self.conn.commit()
                self.log(f"classify: llm {done}/{len(todo)}")
        for pid in fresh:
            self._insert(fps[pid], records[pid], None)

        self._apply_overrides(packs, records, overrides)
        self._write(packs, records, fps)
        for rec in records.values():
            self.counts[f"category:{rec.category}"] += 1
            self.counts[f"source:{rec.source_tag or '-'}"] += 1
            self.counts[f"decided_by:{rec.decided_by}"] += 1
            if rec.reasons:
                self.counts["needs_review"] += 1
        self.counts["meta_files_read"] = self.reader.read
        return dict(sorted(self.counts.items()))

    # ------------------------------------------------------------------------------ loading
    def _load_packs(self) -> list[PackInfo]:
        rows = self._q(
            """
            SELECT p.id, p.name, u.unit_key, u.kind, u.path, u.model_root, u.coloc_root,
                   u.mesh_count, u.set_hash, u.role::text
            FROM packs p JOIN pack_units u ON u.pack_id = p.id
            WHERE p.status <> 'provisional'
            ORDER BY p.id, u.id
            """
        ).all()
        packs: dict[int, PackInfo] = {}
        for pid, name, *u in rows:
            packs.setdefault(pid, PackInfo(pid, name)).units.append(UnitInfo(*u))
        self.root_mesh_units = {
            r[0]: int(r[1])
            for r in self._q(
                """
                SELECT model_root, count(*) FROM pack_units
                WHERE present AND mesh_count > 0 AND model_root IS NOT NULL
                GROUP BY model_root
                """
            )
        }
        return list(packs.values())

    def _meta_stats(self) -> dict[str, tuple]:
        rows = self._q(
            """
            SELECT path, size, mtime FROM source_files
            WHERE present
              AND (path LIKE '%datapackage.json' OR path LIKE '%.spark-curate-meta.json')
            """
        )
        return {r[0]: (int(r[1]), r[2].isoformat()) for r in rows}

    def _cache(self) -> dict[str, Record]:
        rows = self._q(
            """
            SELECT DISTINCT ON (input_fingerprint) input_fingerprint, verdict, decided_by,
                   category, display_name, creator, source_tag, tags, review_reasons, confidence,
                   error
            FROM classify_decisions WHERE prompt_hash = :ph
            ORDER BY input_fingerprint, id DESC
            """,
            ph=cls_judge.PROMPT_HASH,
        ).all()
        out = {}
        for fp, verdict, by, cat, name, creator, source, tags, reasons, conf, error in rows:
            if error and error.startswith(RETRYABLE_ERROR_PREFIXES):
                continue
            if cat not in CATEGORIES:
                continue
            out[fp] = Record(
                cat,
                name or "",
                creator,
                source,
                list(tags or []),
                by,
                float(conf or 0),
                list(reasons or []),
                verdict,
                error,
            )
        return out

    def _fingerprint(self, p: PackInfo, meta_stats: dict) -> str:
        roots = sorted({u.model_root for u in p.units if u.model_root is not None})
        meta = []
        for r in roots:
            for fname in (DATAPACKAGE, SPARK_META):
                path = posixpath.join(r, fname) if r else fname
                meta.append([path, *meta_stats.get(path, (None, None))])
        return fingerprint(
            {
                "rules": RULES_VERSION,
                "prompt": cls_judge.PROMPT_HASH,
                "meta_enabled": self.reader.enabled,
                "owns_root": self._owns_root(p),
                "primary": p.primary.key,
                "units": [[u.key, u.set_hash, u.coloc_root] for u in p.units],
                "meta": meta,
            }
        )

    # ------------------------------------------------------------------------------ deterministic
    def _metas(self, p: PackInfo) -> list[ModelMeta]:
        prim = p.primary
        roots = [prim.model_root] + sorted(
            {u.model_root for u in p.units if u.model_root and u.model_root != prim.model_root}
        )
        return [self.reader.for_root(r) for r in roots if r is not None]

    def _owns_root(self, p: PackInfo) -> bool:
        """True when the pack holds every mesh unit under its primary unit's model root, so the
        root's title / folder name names this pack and not a multi-release collection."""
        root = p.primary.model_root
        if root is None:
            return False
        mine = sum(1 for u in p.units if u.model_root == root and u.mesh_count > 0)
        return mine >= self.root_mesh_units.get(root, 0)

    def _name_candidates(self, p: PackInfo, metas: list[ModelMeta]) -> list[str]:
        prim = p.primary
        cands = []
        if self._owns_root(p):
            if metas and metas[0].title:
                cands.append(metas[0].title)
            cands.append(posixpath.basename(prim.model_root or ""))
        if prim.kind == "loose":
            cands.append(posixpath.basename(prim.path))
        else:
            cands.append(strip_archive_ext(posixpath.basename(prim.path)))
            cands.append(posixpath.basename(posixpath.dirname(prim.path)))
        return [clean_name(c) for c in cands if c]

    def _deterministic(self, p: PackInfo) -> tuple[Record, bool]:
        tops = [u.path.split("/", 1)[0] for u in p.units]
        metas = self._metas(p)
        keywords = _dedupe([k for m in metas for k in m.keywords])
        cats = [c for c in (folder_category(t) for t in tops) if c]
        category = _majority(cats)
        how = "folder" if category else None
        if category is None and not cats:
            kw = {c for c in (keyword_category(k) for k in keywords) if c}
            if len(kw) == 1:
                category, how = kw.pop(), "datapackage_keywords"
        sources = [s for s in (folder_source(t) for t in tops) if s]
        source = _majority(sources) or (sorted(sources)[0] if sources else None)
        if source is None:
            kws = sorted({s for s in (source_keyword(k) for k in keywords) if s})
            source = kws[0] if kws else None
        creator = next((m.creator for m in metas if m.creator), None)
        names = self._name_candidates(p, metas)
        name = next((n for n in names if n and not is_weak(n)), next((n for n in names if n), ""))
        rec = Record(
            category=category or FALLBACK_CATEGORY,
            display_name=name,
            creator=clamp(fs_safe(creator), 80) if creator else None,
            source_tag=source,
            tags=keywords,
            decided_by="deterministic",
            confidence=1.0 if category else 0.0,
            reasons=[],
            evidence={"category_from": how, "tops": sorted(set(tops))},
        )
        if category is None:
            rec.evidence["category_candidates"] = sorted(set(cats))
        return rec, category is None

    def _mesh_names(self, pack_id: int, limit: int = 20) -> list[str]:
        shas = [
            r[0]
            for r in self._q(
                """
                SELECT m.blob_sha FROM pack_units u
                JOIN pack_unit_meshes m ON m.unit_id = u.id
                JOIN blobs b ON b.sha256 = m.blob_sha
                WHERE u.pack_id = :p
                GROUP BY m.blob_sha, b.size ORDER BY b.size DESC, m.blob_sha LIMIT :n
                """,
                p=pack_id,
                n=limit,
            )
        ]
        if not shas:
            return []
        rows = self._q(
            """
            SELECT DISTINCT ON (blob_sha) member_chain[cardinality(member_chain)]
            FROM occurrences WHERE blob_sha = ANY(:s) ORDER BY blob_sha, id
            """,
            s=shas,
        )
        return sorted({posixpath.basename(r[0] or "") for r in rows})

    def _llm_evidence(self, p: PackInfo, rec: Record) -> dict:
        metas = self._metas(p)
        units = sorted(p.units, key=lambda u: (-u.mesh_count, u.key))
        meta = next((m for m in metas if m.title or m.keywords), None)
        return {
            "paths": [u.path for u in units[:8]],
            "more_paths": max(0, len(units) - 8),
            "top_folders": rec.evidence.get("tops", []),
            "folder_categories": rec.evidence.get("category_candidates", []),
            "source": rec.source_tag,
            "datapackage": meta.as_evidence() if meta else None,
            "mesh_names": self._mesh_names(p.id),
        }

    def _apply_llm(self, p: PackInfo, rec: Record, ev: dict, res: cls_judge.Classification) -> None:
        rec.decided_by = "llm"
        rec.verdict = res.verdict
        rec.error = res.error
        rec.confidence = res.confidence
        rec.evidence = {
            **rec.evidence,
            "llm_input": ev,
            "llm": {
                "category": res.category,
                "display_name": res.display_name,
                "creator": res.creator,
                "tags": res.tags,
                "confidence": res.confidence,
                "error": res.error,
            },
        }
        if res.verdict != "ok":
            rec.category = FALLBACK_CATEGORY
            rec.reasons = ["classify_unsure"]
            self.counts["llm_unsure"] += 1
        elif res.confidence < self.min_conf:
            rec.category = FALLBACK_CATEGORY
            rec.reasons = ["classify_low_confidence"]
            self.counts["llm_low_confidence"] += 1
        else:
            rec.category = res.category or FALLBACK_CATEGORY
        if res.verdict == "ok" and (not rec.display_name or is_weak(rec.display_name)):
            llm_name = clean_name(res.display_name)
            if llm_name and not is_weak(llm_name):
                rec.display_name = llm_name
        if not rec.creator and res.creator:
            rec.creator = clamp(fs_safe(res.creator), 80) or None
        rec.tags = _dedupe(rec.tags + res.tags)

    def _insert(self, fp: str, rec: Record, model: str | None) -> None:
        self._q(
            """
            INSERT INTO classify_decisions (input_fingerprint, prompt_hash, model, verdict,
                decided_by, category, display_name, creator, source_tag, tags, review_reasons,
                confidence, error, evidence)
            VALUES (:fp, :ph, :model, :verdict, :by, :cat, :name, :creator, :source, :tags,
                :reasons, :conf, :error, CAST(:ev AS jsonb))
            """,
            fp=fp,
            ph=cls_judge.PROMPT_HASH,
            model=model,
            verdict=rec.verdict,
            by=rec.decided_by,
            cat=rec.category,
            name=rec.display_name,
            creator=rec.creator,
            source=rec.source_tag,
            tags=rec.tags,
            reasons=rec.reasons,
            conf=round(rec.confidence, 4),
            error=rec.error,
            ev=json.dumps(rec.evidence, ensure_ascii=False, default=str),
        )

    # ------------------------------------------------------------------------------ overrides
    def _apply_overrides(self, packs, records, overrides) -> None:
        for p in packs:
            keys = sorted(u.key for u in p.units)
            hits = [overrides[k] for k in keys if k in overrides]
            if not hits:
                continue
            rec = records[p.id]
            cat = next((h[0] for h in hits if h[0]), None)
            name = next((h[1] for h in hits if h[1]), None)
            creator = next((h[2] for h in hits if h[2]), None)
            tags = next((h[3] for h in hits if h[3]), None)
            if cat:
                rec.category = cat
            if name:
                rec.display_name = clean_name(name) or rec.display_name
            if creator:
                rec.creator = clamp(fs_safe(creator), 80)
            if tags:
                rec.tags = _dedupe(list(tags))
            rec.decided_by = "human"
            rec.confidence = 1.0
            rec.reasons = []
            self.counts["human_overrides"] += 1

    # ------------------------------------------------------------------------------ write
    def _write(self, packs: list[PackInfo], records: dict[int, Record], fps: dict[int, str]):
        requests = []
        for p in packs:
            rec = records[p.id]
            base = rec.display_name or f"Pack {hash8(p.primary.key)}"
            requests.append(
                NameRequest(
                    pack_id=p.id,
                    category=rec.category,
                    base=base,
                    anchor_key=p.primary.key,
                    creator=rec.creator,
                    source=rec.source_tag,
                    current=p.name,
                )
            )
        names = assign_names(requests)
        self.counts["names_disambiguated"] = sum(
            1 for r in requests if names[r.pack_id] != finalize(r.base)
        )
        temp_table(
            self.conn,
            "tmp_classify",
            "pack_id bigint PRIMARY KEY, name text, category text, creator text, "
            "source_tag text, tags text[], decided_by text, confidence numeric, fp text, "
            "reasons text[]",
        )
        copy_rows(
            self.conn,
            "tmp_classify",
            (
                "pack_id",
                "name",
                "category",
                "creator",
                "source_tag",
                "tags",
                "decided_by",
                "confidence",
                "fp",
                "reasons",
            ),
            (
                (
                    p.id,
                    names[p.id],
                    records[p.id].category,
                    records[p.id].creator,
                    records[p.id].source_tag,
                    records[p.id].tags,
                    records[p.id].decided_by,
                    round(records[p.id].confidence, 4),
                    fps[p.id],
                    records[p.id].reasons,
                )
                for p in packs
            ),
        )
        self._q("UPDATE packs SET name = NULL WHERE id IN (SELECT pack_id FROM tmp_classify)")
        self._q(
            """
            UPDATE packs p SET name = t.name, category = t.category, creator = t.creator,
                   source_tag = t.source_tag, tags = t.tags, decided_by = t.decided_by,
                   classify_confidence = t.confidence, classify_fingerprint = t.fp,
                   classified_at = now(), updated_at = now(),
                   review_reasons = ARRAY(
                       SELECT DISTINCT x FROM unnest(
                           t.reasons ||
                           ARRAY(SELECT y FROM unnest(p.review_reasons) y
                                 WHERE y NOT LIKE 'classify_%')) x ORDER BY x)
            FROM tmp_classify t WHERE p.id = t.pack_id
            """
        )
        self._q(
            """
            UPDATE packs SET needs_review = cardinality(review_reasons) > 0
            WHERE id IN (SELECT pack_id FROM tmp_classify)
            """
        )
