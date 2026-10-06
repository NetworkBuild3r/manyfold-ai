"""`forge packs resolve` — turn resolution units into final packs (ADR D-7, deterministic first).

Tiers, in order (every join goes through one union-find; a human `separate` is a cannot-link that
no tier can cross, a human `same_pack` is joined first):

1. human same_pack overrides
2. co-location under one non-bundle model root (units.py): by default only mesh-less units
   (previews, img.zip, datapackage) attach to the root's largest mesh unit; `colocate=all`
   also joins mesh-bearing units
3. exact: provisional packs with identical mesh-blob sets
4. subset: a provisional pack whose mesh set is a strict subset of another's (and that has at
   least one non-commons mesh) is absorbed into its largest superset
5. partial overlap, commons removed (a blob in >= K packs): ratio below the band -> separate,
   above -> same, inside -> LLM judge (same_pack | separate | unsure; unsure / low confidence ->
   separate + needs_review). LLM verdicts are cached by input fingerprint + prompt hash.

All overlap work is set-based SQL over pack_unit_meshes and temp tables; Python only walks the
(bounded) candidate pairs. Units whose containers are not all done/failed wait for a later run.

INIT-032/SPEC-010
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from forge.config import require_db_url
from forge.packs import judge as pair_judge
from forge.packs.llm import LlmEndpoint, fingerprint, map_concurrent
from forge.packs.settings import PacksSettings
from forge.packs.sqlutil import analyze, copy_rows, temp_table
from forge.packs.unionfind import ConstrainedUnionFind
from forge.packs.units import load_plan, refresh_units

ADVISORY_LOCK_KEY = 0x464F5247  # one curation job (resolve / classify) at a time
# Any HTTP error is retried on the next run, not just 5xx: a 404 ("model does not exist" after the
# served model changed) or 429 says nothing about the evidence, and caching it would pin the pair
# at `unsure` until the prompt hash changes.
RETRYABLE_ERROR_PREFIXES = ("transport:", "http ", "no attempt")


class ResolveBusy(RuntimeError):
    pass


@dataclass
class Unit:
    id: int
    key: str
    kind: str
    path: str
    model_root: str | None
    root_container_id: int | None
    mesh_count: int
    mesh_bytes: int
    tri_sum: int


@dataclass
class Decision:
    verdict: str
    a: int
    b: int
    rationale: str
    evidence: dict = field(default_factory=dict)
    kind: str = "deterministic"


@dataclass
class ResolveResult:
    counts: dict[str, int]
    dry_run: bool


def acquire_lock(conn: Connection) -> None:
    got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY}).scalar()
    if not got:
        raise ResolveBusy("another forge packs/classify run holds the curation lock")


def release_lock(conn: Connection) -> None:
    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})


def run(
    *,
    dry_run: bool = False,
    settings: PacksSettings | None = None,
    db_url: str | None = None,
    use_llm: bool = True,
    llm_limit: int | None = None,
    endpoint: LlmEndpoint | None = None,
    log=None,
) -> ResolveResult:
    settings = settings or PacksSettings.from_env()
    if not dry_run and use_llm and endpoint is None:
        endpoint = LlmEndpoint.from_env()  # fails before any DB write (AC2)
    engine = create_engine(db_url or require_db_url(), pool_pre_ping=True)
    log = log or (lambda msg: print(msg, file=sys.stderr, flush=True))
    try:
        with engine.connect() as conn:
            acquire_lock(conn)
            conn.commit()
            try:
                resolver = _Resolver(conn, settings, endpoint if use_llm else None, dry_run, log)
                counts = resolver.run(llm_limit=llm_limit)
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
    return ResolveResult(counts=counts, dry_run=dry_run)


class _Resolver:
    def __init__(
        self,
        conn: Connection,
        settings: PacksSettings,
        endpoint: LlmEndpoint | None,
        dry_run: bool,
        log,
    ) -> None:
        self.conn = conn
        self.s = settings
        self.endpoint = endpoint
        self.dry_run = dry_run
        self.log = log
        self.counts: Counter[str] = Counter()
        self.decisions: list[Decision] = []
        self.review: dict[int, set[str]] = defaultdict(set)  # unit id -> reasons
        self.absorbed_units: set[int] = set()

    # ------------------------------------------------------------------------------ helpers
    def _commit(self) -> None:
        if not self.dry_run:
            self.conn.commit()

    def _q(self, sql: str, **params):
        return self.conn.execute(text(sql), params)

    # ------------------------------------------------------------------------------ pipeline
    def run(self, *, llm_limit: int | None) -> dict[str, int]:
        self.conn.execute(text("SET work_mem = '128MB'"))
        plan = load_plan(self.conn, bundle_items=self.s.bundle_items)
        self.counts.update(refresh_units(self.conn, plan))
        self._commit()
        self.log(f"packs: units refreshed {dict(self.counts)}")
        coloc = {u.key: u.coloc for u in plan}

        self.units = self._load_units()
        self.counts["units_resolvable"] = len(self.units)
        self.counts["units_meshless"] = sum(1 for u in self.units.values() if u.mesh_count == 0)
        key_to_id = {u.key: u.id for u in self.units.values()}

        must, cannot = self._human_overrides(key_to_id)
        self.uf = ConstrainedUnionFind(sorted(self.units), cannot)
        for a, b in must:
            if self.uf.union(a, b):
                self.counts["human_same_applied"] += 1
            else:
                self.counts["human_conflicts"] += 1
        self.counts["human_separate_applied"] = len(cannot)

        self._colocate(coloc)
        self._exact_and_subset()
        pairs = self._partial_overlap()
        self._llm_tier(pairs, llm_limit)
        self._write()
        self.counts["tier_deterministic"] = sum(
            1 for d in self.decisions if d.kind == "deterministic"
        )
        return dict(sorted(self.counts.items()))

    def _load_units(self) -> dict[int, Unit]:
        rows = self._q(
            """
            SELECT id, unit_key, kind, path, model_root, root_container_id, mesh_count,
                   mesh_bytes, tri_sum
            FROM pack_units WHERE present AND complete ORDER BY id
            """
        )
        return {int(r[0]): Unit(int(r[0]), *r[1:]) for r in rows}

    def _human_overrides(self, key_to_id: dict[str, int]):
        rows = self._q(
            """
            SELECT DISTINCT ON (least(key_a, key_b), greatest(key_a, key_b))
                   key_a, key_b, verdict::text
            FROM pack_decisions
            WHERE kind = 'human' AND key_a IS NOT NULL AND key_b IS NOT NULL
            ORDER BY least(key_a, key_b), greatest(key_a, key_b), id DESC
            """
        ).all()
        must, cannot = [], []
        for ka, kb, verdict in rows:
            a, b = key_to_id.get(ka), key_to_id.get(kb)
            if a is None or b is None:
                self.counts["human_unmatched"] += 1
                continue
            if verdict == "same_pack":
                must.append((a, b))
            elif verdict == "separate":
                cannot.append((a, b))
        return must, cannot

    # ------------------------------------------------------------------------------ tier 2
    def _colocate(self, coloc: dict[str, str | None]) -> None:
        mode = self.s.colocate
        if mode == "off":
            return
        groups: dict[str, list[int]] = defaultdict(list)
        for u in self.units.values():
            root = coloc.get(u.key)
            if root is not None:
                groups[root].append(u.id)
        for root, ids in groups.items():
            ids.sort()
            meshy = [i for i in ids if self.units[i].mesh_count > 0]
            if mode == "all" or not meshy:
                anchor, joiners = ids[0], ids[1:]
                why = f"co-located under model root {root}"
            else:
                anchor = min(meshy, key=lambda i: (-self.units[i].mesh_bytes, i))
                joiners = [i for i in ids if self.units[i].mesh_count == 0]
                why = f"mesh-less unit attached to the largest mesh unit under model root {root}"
            for uid in joiners:
                if self.uf.union(anchor, uid):
                    self.counts["coloc_joined"] += 1
                    self.decisions.append(Decision("same_pack", anchor, uid, why))
                else:
                    self.counts["coloc_blocked"] += 1

    # ------------------------------------------------------------------------------ tiers 3-4
    def _comp_table(self, name: str) -> dict[int, int]:
        comp = self.uf.comp_of()
        temp_table(self.conn, name, "unit_id bigint PRIMARY KEY, comp_id bigint NOT NULL")
        copy_rows(self.conn, name, ("unit_id", "comp_id"), comp.items())
        analyze(self.conn, name)
        return comp

    def _exact_and_subset(self) -> None:
        k, cap = self.s.commons_k, self.s.candidate_cap
        self._comp_table("tmp_comp0")
        temp_table(
            self.conn,
            "tmp_cm",
            "",
            as_select="""
                SELECT DISTINCT c.comp_id, m.blob_sha
                FROM pack_unit_meshes m JOIN tmp_comp0 c ON c.unit_id = m.unit_id
            """,
        )
        self._q("CREATE INDEX ON tmp_cm (comp_id, blob_sha)")
        self._q("CREATE INDEX ON tmp_cm (blob_sha)")
        analyze(self.conn, "tmp_cm")

        sets = self._q(
            """
            SELECT comp_id, md5(string_agg(blob_sha, ',' ORDER BY blob_sha)) AS h, count(*) AS n
            FROM tmp_cm GROUP BY comp_id
            """
        ).all()
        by_hash: dict[str, list[int]] = defaultdict(list)
        size: dict[int, int] = {}
        for comp_id, h, n in sets:
            by_hash[h].append(int(comp_id))
            size[int(comp_id)] = int(n)
        eg_of: dict[int, int] = {}
        for h, comps in by_hash.items():
            comps.sort()
            for c in comps:
                eg_of[c] = comps[0]
            for c in comps[1:]:
                if self.uf.union(comps[0], c):
                    self.counts["exact_joined"] += 1
                    self.decisions.append(
                        Decision(
                            "same_pack",
                            comps[0],
                            c,
                            f"identical mesh set ({size[c]} meshes)",
                            {"meshes": size[c]},
                        )
                    )
                else:
                    self.counts["exact_blocked"] += 1
        members_of_eg: dict[int, list[int]] = defaultdict(list)
        for c, g in eg_of.items():
            members_of_eg[g].append(c)

        temp_table(self.conn, "tmp_eg", "comp_id bigint PRIMARY KEY, eg bigint NOT NULL")
        copy_rows(self.conn, "tmp_eg", ("comp_id", "eg"), eg_of.items())
        temp_table(
            self.conn,
            "tmp_gm",
            "",
            as_select="""
                SELECT cm.comp_id AS eg, cm.blob_sha
                FROM tmp_cm cm JOIN tmp_eg e ON e.comp_id = cm.comp_id AND e.eg = cm.comp_id
            """,
        )
        self._q("CREATE INDEX ON tmp_gm (eg, blob_sha)")
        self._q("CREATE INDEX ON tmp_gm (blob_sha)")
        temp_table(
            self.conn,
            "tmp_dg",
            "",
            as_select="SELECT blob_sha, count(*) AS dg FROM tmp_gm GROUP BY blob_sha",
        )
        self._q("ALTER TABLE tmp_dg ADD PRIMARY KEY (blob_sha)")
        analyze(self.conn, "tmp_gm", "tmp_dg")

        # per exact group: n, dg=1 (unique), 2..cap (low), >cap (high), <k (non-commons)
        temp_table(
            self.conn,
            "tmp_gstats",
            "",
            as_select=f"""
                SELECT gm.eg, count(*) AS n,
                       count(*) FILTER (WHERE d.dg = 1) AS u1,
                       count(*) FILTER (WHERE d.dg BETWEEN 2 AND {int(cap)}) AS low,
                       count(*) FILTER (WHERE d.dg > {int(cap)}) AS high,
                       count(*) FILTER (WHERE d.dg < {int(k)}) AS nc
                FROM tmp_gm gm JOIN tmp_dg d ON d.blob_sha = gm.blob_sha
                GROUP BY gm.eg
            """,
        )
        self._q("ALTER TABLE tmp_gstats ADD PRIMARY KEY (eg)")
        stats = {
            int(r[0]): (int(r[1]), int(r[2]), int(r[3]), int(r[4]), int(r[5]))
            for r in self._q("SELECT eg, n, u1, low, high, nc FROM tmp_gstats")
        }
        # (small, big): small is smaller, has no unique blob, and shares every low-degree blob
        maybe = [
            (int(r[0]), int(r[1]))
            for r in self._q(
                """
                WITH cand AS (
                    SELECT a.eg AS ga, b.eg AS gb, count(*) AS shared_low
                    FROM tmp_gm a
                    JOIN tmp_dg d ON d.blob_sha = a.blob_sha AND d.dg BETWEEN 2 AND :cap
                    JOIN tmp_gm b ON b.blob_sha = a.blob_sha AND b.eg <> a.eg
                    GROUP BY a.eg, b.eg
                )
                SELECT c.ga, c.gb
                FROM cand c
                JOIN tmp_gstats s ON s.eg = c.ga
                JOIN tmp_gstats t ON t.eg = c.gb
                WHERE s.n < t.n AND s.u1 = 0 AND c.shared_low = s.low
                """,
                cap=cap,
            )
        ]
        self.counts["subset_pairs"] = len(maybe)
        need_high = [(a, b) for a, b in maybe if stats[a][3] > 0]
        high_ok: set[tuple[int, int]] = set()
        if need_high:
            temp_table(self.conn, "tmp_chk", "ga bigint, gb bigint")
            copy_rows(self.conn, "tmp_chk", ("ga", "gb"), need_high)
            for ga, gb, n in self._q(
                """
                SELECT c.ga, c.gb, count(*)
                FROM tmp_chk c
                JOIN tmp_gm x ON x.eg = c.ga
                JOIN tmp_dg d ON d.blob_sha = x.blob_sha AND d.dg > :cap
                JOIN tmp_gm y ON y.eg = c.gb AND y.blob_sha = x.blob_sha
                GROUP BY c.ga, c.gb
                """,
                cap=cap,
            ):
                if int(n) == stats[int(ga)][3]:
                    high_ok.add((int(ga), int(gb)))
        supersets: dict[int, list[int]] = defaultdict(list)
        for a, b in maybe:
            if stats[a][3] == 0 or (a, b) in high_ok:
                supersets[a].append(b)
        for a in sorted(supersets):
            if stats[a][4] == 0:
                self.counts["subset_commons_only"] += 1
                continue
            best = min(supersets[a], key=lambda g: (-stats[g][0], g))
            if self.uf.union(a, best):
                self.counts["subset_absorbed"] += 1
                for c in members_of_eg[a]:
                    self.absorbed_units.update(self._units_of_comp0(c))
                self.decisions.append(
                    Decision(
                        "absorb",
                        a,
                        best,
                        f"strict subset ({stats[a][0]} of {stats[best][0]} meshes), no unique"
                        f" meshes; {len(supersets[a])} superset(s)",
                        {"small": stats[a][0], "big": stats[best][0], "supersets": supersets[a]},
                    )
                )
            else:
                self.counts["subset_blocked"] += 1

    def _units_of_comp0(self, comp_id: int) -> list[int]:
        if not hasattr(self, "_comp0_members"):
            rows = self._q("SELECT unit_id, comp_id FROM tmp_comp0").all()
            members: dict[int, list[int]] = defaultdict(list)
            for uid, cid in rows:
                members[int(cid)].append(int(uid))
            self._comp0_members = members
        return self._comp0_members.get(comp_id, [])

    # ------------------------------------------------------------------------------ tier 5
    def _partial_overlap(self) -> list[dict]:
        k = self.s.commons_k
        comp = self._comp_table("tmp_comp1")
        self.comp1 = comp
        self.comp1_members: dict[int, list[int]] = defaultdict(list)
        for uid, cid in comp.items():
            self.comp1_members[cid].append(uid)
        temp_table(
            self.conn,
            "tmp_cm1",
            "",
            as_select="""
                SELECT DISTINCT c.comp_id, m.blob_sha
                FROM pack_unit_meshes m JOIN tmp_comp1 c ON c.unit_id = m.unit_id
            """,
        )
        self._q("CREATE INDEX ON tmp_cm1 (comp_id, blob_sha)")
        self._q("CREATE INDEX ON tmp_cm1 (blob_sha)")
        temp_table(
            self.conn,
            "tmp_dc",
            "",
            as_select="SELECT blob_sha, count(*) AS dc FROM tmp_cm1 GROUP BY blob_sha",
        )
        self._q("ALTER TABLE tmp_dc ADD PRIMARY KEY (blob_sha)")
        analyze(self.conn, "tmp_cm1", "tmp_dc")
        self.counts["commons_blobs"] = int(
            self._q("SELECT count(*) FROM tmp_dc WHERE dc >= :k", k=k).scalar_one()
        )
        self.cstats = {
            int(r[0]): {
                "meshes": int(r[1]),
                "bytes": int(r[2]),
                "tri": int(r[3]),
                "nc": int(r[4]),
                "nc_bytes": int(r[5]),
            }
            for r in self._q(
                """
                SELECT cm.comp_id, count(*), sum(b.size), sum(coalesce(b.stl_triangles, 0)),
                       count(*) FILTER (WHERE d.dc < :k),
                       coalesce(sum(b.size) FILTER (WHERE d.dc < :k), 0)
                FROM tmp_cm1 cm
                JOIN tmp_dc d ON d.blob_sha = cm.blob_sha
                JOIN blobs b ON b.sha256 = cm.blob_sha
                GROUP BY cm.comp_id
                """,
                k=k,
            )
        }
        rows = self._q(
            """
            SELECT a.comp_id, b.comp_id, count(*), sum(bl.size)
            FROM tmp_cm1 a
            JOIN tmp_dc d ON d.blob_sha = a.blob_sha AND d.dc BETWEEN 2 AND :km1
            JOIN tmp_cm1 b ON b.blob_sha = a.blob_sha AND b.comp_id > a.comp_id
            JOIN blobs bl ON bl.sha256 = a.blob_sha
            GROUP BY a.comp_id, b.comp_id
            """,
            km1=k - 1,
        ).all()
        self.counts["overlap_pairs"] = len(rows)
        pairs: list[dict] = []
        for ca, cb, shared, shared_bytes in rows:
            ca, cb = int(ca), int(cb)
            sa, sb = self.cstats[ca], self.cstats[cb]
            smaller = min(sa["nc"], sb["nc"])
            ratio = int(shared) / smaller if smaller else 0.0
            p = {
                "a": ca,
                "b": cb,
                "shared": int(shared),
                "shared_bytes": int(shared_bytes or 0),
                "ratio": round(ratio, 4),
            }
            if ratio < self.s.band_low:
                self.counts["band_below"] += 1
                self.decisions.append(
                    Decision(
                        "separate",
                        ca,
                        cb,
                        f"overlap {ratio:.3f} below band {self.s.band_low}",
                        {"shared": p["shared"], "ratio": p["ratio"]},
                    )
                )
            elif ratio > self.s.band_high:
                self.counts["band_above"] += 1
                if self.uf.union(ca, cb):
                    self.decisions.append(
                        Decision(
                            "same_pack",
                            ca,
                            cb,
                            f"overlap {ratio:.3f} above band {self.s.band_high}",
                            {"shared": p["shared"], "ratio": p["ratio"]},
                        )
                    )
            else:
                pairs.append(p)
        pairs.sort(key=lambda p: (-p["shared_bytes"], p["a"], p["b"]))
        self.counts["band_llm_pairs"] = len(pairs)
        return pairs

    # ------------------------------------------------------------------------------ evidence
    def _side(self, comp_id: int) -> dict:
        members = sorted(
            (self.units[u] for u in self.comp1_members[comp_id]),
            key=lambda u: (-u.mesh_bytes, u.key),
        )
        cap = self.s.evidence_paths
        paths = [("archive: " if u.kind == "archive" else "folder: ") + u.path for u in members]
        st = self.cstats[comp_id]
        return {
            "paths": paths[:cap],
            "more_paths": max(0, len(paths) - cap),
            "units": len(members),
            "meshes": st["meshes"],
            "mesh_bytes": st["bytes"],
            "triangles": st["tri"],
        }

    def _names(self, shas: list[str]) -> dict[str, str]:
        if not shas:
            return {}
        rows = self._q(
            """
            SELECT DISTINCT ON (blob_sha) blob_sha, member_chain[cardinality(member_chain)]
            FROM occurrences WHERE blob_sha = ANY(:shas) ORDER BY blob_sha, id
            """,
            shas=shas,
        )
        return {r[0]: posixpath.basename(r[1] or "") for r in rows}

    def evidence(self, pair: dict) -> tuple[dict, str]:
        ca, cb, k = pair["a"], pair["b"], self.s.commons_k
        rows = self._q(
            """
            SELECT cm.blob_sha, bool_or(cm.comp_id = :a), bool_or(cm.comp_id = :b), b.size,
                   coalesce(b.stl_triangles, 0), d.dc
            FROM tmp_cm1 cm
            JOIN blobs b ON b.sha256 = cm.blob_sha
            JOIN tmp_dc d ON d.blob_sha = cm.blob_sha
            WHERE cm.comp_id IN (:a, :b)
            GROUP BY cm.blob_sha, b.size, b.stl_triangles, d.dc
            """,
            a=ca,
            b=cb,
        ).all()
        shared, commons_shared, only_a, only_b = [], 0, [], []
        set_a, set_b = [], []
        for sha, in_a, in_b, size, tri, dc in rows:
            if in_a:
                set_a.append(sha)
            if in_b:
                set_b.append(sha)
            if in_a and in_b:
                if dc >= k:
                    commons_shared += 1
                else:
                    shared.append((sha, int(size), int(tri)))
            elif in_a:
                only_a.append((sha, int(size), int(tri)))
            else:
                only_b.append((sha, int(size), int(tri)))
        n = self.s.evidence_names
        by_size = lambda xs: sorted(xs, key=lambda t: (-t[1], t[0]))  # noqa: E731
        pick = [t[0] for xs in (shared, only_a, only_b) for t in by_size(xs)[:n]]
        names = self._names(pick)

        def name_list(xs):
            return sorted({names.get(t[0], "?") for t in by_size(xs)[:n]})

        sa, sb = self.cstats[ca], self.cstats[cb]
        shared_bytes = sum(t[1] for t in shared)
        smaller_nc = min(sa["nc"], sb["nc"]) or 1
        smaller_bytes = min(sa["nc_bytes"], sb["nc_bytes"]) or 1
        union_nc = sa["nc"] + sb["nc"] - len(shared) or 1
        side_a, side_b = self._side(ca), self._side(cb)
        side_a.update(
            unique_meshes=len(only_a),
            unique_bytes=sum(t[1] for t in only_a),
            unique_names=name_list(only_a),
        )
        side_b.update(
            unique_meshes=len(only_b),
            unique_bytes=sum(t[1] for t in only_b),
            unique_names=name_list(only_b),
        )
        evidence = {
            "commons_k": k,
            "a": side_a,
            "b": side_b,
            "shared": {
                "meshes": len(shared),
                "bytes": shared_bytes,
                "triangles": sum(t[2] for t in shared),
                "names": name_list(shared),
            },
            "commons_shared": commons_shared,
            "containment_count": round(len(shared) / smaller_nc, 4),
            "containment_bytes": round(shared_bytes / smaller_bytes, 4),
            "jaccard": round(len(shared) / union_nc, 4),
        }
        fp = fingerprint(
            {
                "evidence": evidence,
                "set_a": hashlib.sha256(",".join(sorted(set_a)).encode()).hexdigest(),
                "set_b": hashlib.sha256(",".join(sorted(set_b)).encode()).hexdigest(),
            }
        )
        return evidence, fp

    # ------------------------------------------------------------------------------ LLM tier
    def _cached(self) -> dict[str, tuple]:
        rows = self._q(
            """
            SELECT DISTINCT ON (input_fingerprint) input_fingerprint, verdict::text, confidence,
                   rationale, error, model
            FROM pack_decisions
            WHERE kind = 'llm' AND prompt_hash = :ph AND input_fingerprint IS NOT NULL
            ORDER BY input_fingerprint, id DESC
            """,
            ph=pair_judge.PROMPT_HASH,
        ).all()
        out = {}
        for fp, verdict, conf, reason, error, model in rows:
            if error and error.startswith(RETRYABLE_ERROR_PREFIXES):
                continue
            out[fp] = (verdict, float(conf or 0), reason or "", error, model)
        return out

    def _llm_tier(self, pairs: list[dict], llm_limit: int | None) -> None:
        cache = self._cached()
        todo: list[tuple[dict, dict, str]] = []
        resolved: list[tuple[dict, pair_judge.Verdict]] = []
        for p in pairs:
            if not self.uf.can_union(p["a"], p["b"]):
                self.counts["llm_skipped_human_separate"] += 1
                continue
            if self.uf.find(p["a"]) == self.uf.find(p["b"]):
                self.counts["llm_skipped_already_joined"] += 1
                continue
            evidence, fp = self.evidence(p)
            p["fingerprint"] = fp
            hit = cache.get(fp)
            if hit is not None:
                self.counts["llm_cached"] += 1
                resolved.append((p, pair_judge.Verdict(hit[0], hit[1], hit[2], hit[3])))
            else:
                todo.append((p, evidence, fp))
        self.counts["llm_needed"] = len(todo)
        if self.endpoint is None or self.dry_run:
            self.counts["llm_deferred"] += len(todo)
            todo = []
        elif llm_limit is not None and len(todo) > llm_limit:
            self.counts["llm_deferred"] += len(todo) - llm_limit
            todo = todo[:llm_limit]

        endpoint = self.endpoint
        done = 0
        for (p, evidence, fp), verdict in map_concurrent(
            lambda item: pair_judge.judge(endpoint, item[1]), todo, self.s.llm_concurrency
        ):
            self._insert_llm(p, evidence, fp, verdict)
            resolved.append((p, verdict))
            self.counts["llm_called"] += 1
            done += 1
            if done % 10 == 0:
                self._commit()
                self.log(f"packs: llm {done}/{len(todo)}")
        self._commit()

        resolved.sort(key=lambda pv: (-pv[0]["shared_bytes"], pv[0]["a"], pv[0]["b"]))
        for p, v in resolved:
            self.counts[f"llm_{v.verdict}"] += 1
            if v.verdict == "same_pack" and v.confidence >= self.s.min_confidence:
                if not self.uf.can_union(p["a"], p["b"]):
                    self._flag(p, "human_separate_blocks_llm")
                elif not self.uf.union(p["a"], p["b"], max_size=self.s.max_llm_units):
                    self.counts["llm_chain_guard"] += 1
                    self._flag(p, "chain_guard")
                else:
                    self.counts["llm_joined"] += 1
            elif v.verdict == "same_pack" or v.verdict == "unsure":
                self.counts["llm_needs_review"] += 1
                self._flag(p, "pair_unsure")

    def _flag(self, pair: dict, reason: str) -> None:
        for comp in (pair["a"], pair["b"]):
            for uid in self.comp1_members.get(comp, [comp]):
                self.review[uid].add(reason)

    def _insert_llm(self, p: dict, evidence: dict, fp: str, v: pair_judge.Verdict) -> None:
        ua, ub = self.units[p["a"]], self.units[p["b"]]
        needs_review = (
            v.verdict == "unsure" or v.error is not None or v.confidence < self.s.min_confidence
        )
        self._q(
            """
            INSERT INTO pack_decisions (kind, container_a, container_b, unit_a, unit_b, key_a,
                key_b, verdict, confidence, rationale, model, input_fingerprint, prompt_hash,
                needs_review, error, evidence)
            VALUES ('llm', :ca, :cb, :ua, :ub, :ka, :kb, CAST(:verdict AS pack_verdict), :conf,
                :reason, :model, :fp, :ph, :nr, :err, CAST(:ev AS jsonb))
            """,
            ca=ua.root_container_id,
            cb=ub.root_container_id,
            ua=ua.id,
            ub=ub.id,
            ka=ua.key,
            kb=ub.key,
            verdict=v.verdict,
            conf=round(v.confidence, 4),
            reason=v.reason,
            model=self.endpoint.model if self.endpoint else None,
            fp=fp,
            ph=pair_judge.PROMPT_HASH,
            nr=needs_review,
            err=v.error,
            ev=json.dumps({**evidence, "ratio": p["ratio"]}, ensure_ascii=False),
        )

    # ------------------------------------------------------------------------------ write
    def _write(self) -> None:
        comps = self.uf.components()
        existing = {
            int(r[0]): int(r[1])
            for r in self._q("SELECT id, pack_id FROM pack_units WHERE pack_id IS NOT NULL")
        }
        taken: set[int] = set()
        assign: dict[int, int | None] = {}
        order = sorted(comps, key=lambda c: (-len(comps[c]), c))
        for c in order:
            votes = Counter(existing[u] for u in comps[c] if u in existing)
            choice = None
            for pid, _n in sorted(votes.items(), key=lambda kv: (-kv[1], kv[0])):
                if pid not in taken:
                    choice = pid
                    break
            if choice is not None:
                taken.add(choice)
            assign[c] = choice
        need = [c for c in order if assign[c] is None]
        if need:
            new_ids = [
                int(r[0])
                for r in self._q(
                    """
                    INSERT INTO packs (status) SELECT 'resolved' FROM generate_series(1, :n)
                    RETURNING id
                    """,
                    n=len(need),
                )
            ]
            for c, pid in zip(need, sorted(new_ids), strict=True):
                assign[c] = pid
        self.counts["packs_reused"] = len(taken)
        self.counts["packs_created"] = len(need)
        self.counts["packs"] = len(comps)

        rows = []
        reasons_by_pack: dict[int, set[str]] = defaultdict(set)
        for c, members in comps.items():
            pid = assign[c]
            not_absorbed = [u for u in members if u not in self.absorbed_units] or members
            primary = min(not_absorbed, key=lambda u: (-self.units[u].mesh_count, u))
            for u in members:
                role = (
                    "primary"
                    if u == primary
                    else ("absorbed" if u in self.absorbed_units else "source")
                )
                rows.append((u, pid, role))
                reasons_by_pack[pid] |= self.review.get(u, set())
        temp_table(self.conn, "tmp_assign", "unit_id bigint PRIMARY KEY, pack_id bigint, role text")
        copy_rows(self.conn, "tmp_assign", ("unit_id", "pack_id", "role"), rows)
        self._q(
            """
            UPDATE pack_units SET pack_id = NULL, role = NULL
            WHERE pack_id IS NOT NULL AND id NOT IN (SELECT unit_id FROM tmp_assign)
            """
        )
        self._q(
            """
            UPDATE pack_units u SET pack_id = a.pack_id,
                   role = CAST(a.role AS pack_container_role), updated_at = now()
            FROM tmp_assign a WHERE u.id = a.unit_id
            """
        )
        deleted = self._q(
            """
            DELETE FROM packs
            WHERE status <> 'provisional' AND id NOT IN (SELECT DISTINCT pack_id FROM tmp_assign)
            """
        ).rowcount
        self.counts["packs_deleted"] = int(deleted or 0)

        temp_table(self.conn, "tmp_reasons", "pack_id bigint PRIMARY KEY, reasons text[]")
        copy_rows(
            self.conn,
            "tmp_reasons",
            ("pack_id", "reasons"),
            ((pid, sorted(rs)) for pid, rs in reasons_by_pack.items()),
        )
        self._q(
            """
            UPDATE packs p SET status = CASE WHEN p.status = 'materialized'
                                             THEN p.status ELSE 'resolved' END,
                   unit_count = s.units, mesh_count = coalesce(m.n, 0),
                   mesh_bytes = coalesce(m.bytes, 0),
                   review_reasons = ARRAY(
                       SELECT DISTINCT x FROM unnest(
                           coalesce(r.reasons, '{}') ||
                           ARRAY(SELECT y FROM unnest(p.review_reasons) y
                                 WHERE y LIKE 'classify_%')) x ORDER BY x),
                   updated_at = now()
            FROM (SELECT pack_id, count(*) AS units FROM tmp_assign GROUP BY pack_id) s
            LEFT JOIN (
                SELECT x.pack_id, count(*) AS n, sum(b.size) AS bytes
                FROM (SELECT DISTINCT a.pack_id, m.blob_sha
                      FROM tmp_assign a JOIN pack_unit_meshes m ON m.unit_id = a.unit_id) x
                JOIN blobs b ON b.sha256 = x.blob_sha
                GROUP BY x.pack_id
            ) m ON m.pack_id = s.pack_id
            LEFT JOIN tmp_reasons r ON r.pack_id = s.pack_id
            WHERE p.id = s.pack_id
            """
        )
        self._q("UPDATE packs SET needs_review = cardinality(review_reasons) > 0")
        self.counts["packs_needs_review"] = int(
            self._q("SELECT count(*) FROM packs WHERE needs_review").scalar_one()
        )

        # pack_containers means "this container's whole subtree belongs to the pack" (the SPEC-012
        # planner reads it that way). A loose_batch holds up to 500 files in path order, so it is
        # attached only when every one of its files belongs to this one pack; otherwise exact loose
        # membership lives in pack_units / pack_unit_sources only.
        self._q("DELETE FROM pack_containers WHERE pack_id IN (SELECT pack_id FROM tmp_assign)")
        temp_table(
            self.conn,
            "tmp_batch_cover",
            "",
            as_select="""
                SELECT cf.container_id, count(*) AS files, count(a.pack_id) AS covered,
                       count(DISTINCT a.pack_id) AS packs, min(a.pack_id) AS pack_id,
                       min(CASE a.role WHEN 'primary' THEN 0 WHEN 'source' THEN 1 ELSE 2 END)
                           AS role_rank
                FROM container_files cf
                JOIN containers c ON c.id = cf.container_id AND c.kind = 'loose_batch'
                LEFT JOIN pack_unit_sources s ON s.source_file_id = cf.source_file_id
                LEFT JOIN tmp_assign a ON a.unit_id = s.unit_id
                GROUP BY cf.container_id
                HAVING count(a.pack_id) > 0
            """,
        )
        self._q(
            """
            INSERT INTO pack_containers (pack_id, container_id, role)
            SELECT a.pack_id, u.root_container_id, CAST(a.role AS pack_container_role)
            FROM tmp_assign a JOIN pack_units u ON u.id = a.unit_id
            WHERE u.root_container_id IS NOT NULL
            UNION ALL
            SELECT pack_id, container_id,
                   CAST((ARRAY['primary', 'source', 'absorbed'])[role_rank + 1]
                        AS pack_container_role)
            FROM tmp_batch_cover WHERE packs = 1 AND covered = files
            """
        )
        self.counts["loose_batches_whole"] = int(
            self._q(
                "SELECT count(*) FROM tmp_batch_cover WHERE packs = 1 AND covered = files"
            ).scalar_one()
        )
        self.counts["loose_batches_split"] = int(
            self._q(
                "SELECT count(*) FROM tmp_batch_cover WHERE NOT (packs = 1 AND covered = files)"
            ).scalar_one()
        )
        self._write_deterministic()

    def _write_deterministic(self) -> None:
        self._q("DELETE FROM pack_decisions WHERE kind = 'deterministic'")
        rows = []
        for d in self.decisions:
            ua, ub = self.units[d.a], self.units[d.b]
            rows.append(
                (
                    "deterministic",
                    ua.root_container_id,
                    ub.root_container_id,
                    ua.id,
                    ub.id,
                    ua.key,
                    ub.key,
                    d.verdict,
                    1,
                    d.rationale,
                    json.dumps(d.evidence),
                )
            )
        copy_rows(
            self.conn,
            "pack_decisions",
            (
                "kind",
                "container_a",
                "container_b",
                "unit_a",
                "unit_b",
                "key_a",
                "key_b",
                "verdict",
                "confidence",
                "rationale",
                "evidence",
            ),
            rows,
        )
