# forge tags — searchable tags for every pack (INIT-032/SPEC-016)

`forge classify` gives a pack a category, a name and a creator, but almost no tags (only the ~1 %
that went through the LLM). `forge tags` fills that gap so a model can be *found*: tags for the
franchise, the character, the genre, the kind of object, the scale, supports and file formats.
They are written to `packs.tags`, emitted as the Frictionless `keywords` array of each pack's
`datapackage.json`, and applied to Manyfold models as tags.

Tags are **metadata, not routing**. Nothing here chooses a specialist, an action tool or a mode
from text; the LLM only judges what a pack depicts, and code derives every fact it can
(`myaifitness-no-regex-routing` / `myaifitness-deterministic-compute`).

## Where each tag comes from

Order in the stored list is the order below (a stable set union; the first occurrence wins).

| # | Source | Tags | Module |
| --- | --- | --- | --- |
| 1 | **Code, from the catalog** | category (`dc`, `dungeons-and-dragons`; `Misc` yields none), creator (`sanix`), source (`cults3d`), file formats (`stl`, `3mf`, `obj`, `step`, `lychee`, `chitubox`, `gcode`, `blend`, `fbx`), supports (`presupported`, `unsupported`), scale (`28mm`, `scale-1-10`), part kinds (`bust`, `base`, `head`, `torso`, `arm`, `leg`, `hand`, `wing`, `tail`, `helmet`, `shield`, `cape`, `weapon`), `has-preview` | `derive.py` |
| 2 | **classify** | the keywords `forge classify` stored (spark-curate `datapackage.json` keywords plus its own ≤ 8 LLM tags); an owner's `forge classify override` tags replace them | `run.py` |
| 3 | **LLM**, one call per pack | franchise (≤ 2), characters (≤ 4), genre (≤ 3), object type (≤ 2, closed list), art style (≤ 1, closed list) — at most 12 | `judge.py` |

Then the owner's tag overrides are applied (below). Every tag from every source goes through
`normalize.py`.

### Code-derived rules (`derive.py` is the whole rulebook)

* **Evidence** is names and paths only: the pack's unit paths, every member path of its
  containers (nested archives included) and its loose-unit source files, capped at 3000 paths per
  pack (sorted, so the cut is deterministic). `__MACOSX/` and `._name` debris are ignored.
* **File formats** come from extensions: `stl`; `3mf`; `obj`; `step`/`stp`; `lys`/`lyt`/`lychee` →
  `lychee`; `ctb`/`cbddlp`/`chitubox` → `chitubox`; `gcode`/`bgcode`; `blend`; `fbx`.
* **Supports**: a path component whose words say `supported`, `presupported`, `pre supported`,
  `with supports` → `presupported`; `unsupported`, `no/non/without supports` → `unsupported`
  (both can apply). Words are split on separators and camelCase (`PreSupported`, `STLs_Supported`).
* **Scale**: a number 6–200 followed by `mm` (`28mm`, `75 mm`) in the pack name, unit path or any
  member path; and `1:N` (colon) or `1 N scale` / `scale 1 N` for N in 2–10, 12, 16, 18, 20, 24,
  32, 35, 48, 72 → `scale-1-N`.
* **Part kinds**: a directory or file name of a *mesh* file containing one of the part words
  (`bust`, `base`, `head`, `torso`, `arm`, `leg`, `hand`, `wing`, `tail`, `helmet`, `shield`,
  `cape`, `weapon`, singular or plural). Whole words only (`database` is not `base`).
* **`has-preview`**: an image member exists (or the units count images).

### The LLM call

One request per pack: the same client as `packs`/`classify` (`forge.packs.llm`), temperature 0,
`response_format: json_schema` with `strict: true`, at most 4 requests in flight. The schema is a
closed object — `franchise`, `characters`, `genre`, `object_type`, `art_style` — with item caps that
sum to 12; `object_type` and `art_style` are enums (`figure`, `bust`, `statue`, `diorama`,
`terrain`, `building`, `vehicle`, `creature`, `prop`, `weapon`, `armor`, `helmet`, `mask`,
`costume-part`, `accessory`, `base`, `tool`, `container`, `jewelry`, `toy`, `game-piece`,
`wall-art`, `other`). The prompt tells the model not to repeat what code already knows (category,
creator, source, formats, scale, supports, parts) and treats the evidence as untrusted data.

The evidence sent is `{name, category, creator, source, paths[≤8], more_paths, folders[≤20],
mesh_names[≤20]}` — names and paths only, nothing read from file bodies.

A reply that is not valid JSON, has extra/missing fields or an enum value outside the list is
`unsure`: it is cached for that evidence + prompt and the pack keeps its code-derived and classify
tags. A transport error or any HTTP error (a 404 after the served model changed, a 429) is **not**
cached and is retried on the next run.

### Normalisation (`normalize.py`, vocabulary in `vocab.json`)

lowercase ASCII kebab-case, ≤ 40 characters (cut at a word boundary), no stopwords or bare numbers
(`model`, `stl-file`, `3d-print`, `new`, `unknown`, …), a leading `the-` dropped, duplicates
removed, the last word singularised when the plural is obvious (`dragons` → `dragon`,
`bunnies` → `bunny`, `elves` → `elf`; `x-men`, `avengers`, `star-wars`, `series`, … are protected),
synonyms folded (`dnd`, `d&d`, `dungeons & dragons` → `dungeons-and-dragons`; `dc comics` → `dc`;
`sci-fi` → `science-fiction`; `40k` → `warhammer-40000`; `minis` → `miniature`). Creators, sources
and categories keep their names (no singularising). The LLM list is capped at 12; the merged list
stored on a pack at 40. Edit `vocab.json` (a package-data file), not the code, to add a synonym.

## Commands

```bash
forge tags                         # all packs; plan packs first; LLM for packs not yet cached
forge tags --dry-run               # compute, write nothing, call nothing (counts + top tags)
forge tags --no-llm                # code-derived + classify tags only
forge tags --llm-limit 300         # at most 300 LLM calls this run; the rest get code tags only
forge tags --limit 300             # at most 300 packs (packs of the active materialize plan first)
forge tags --pack 8721 --pack 8722 # these packs only
forge tags sample --n 20           # random tagged packs (JSONL)
forge tags stats --top 40          # coverage, tags-per-pack buckets, most common tags (JSON)
forge tags review --out tags.csv   # export current tags for editing
forge tags override --file tags.csv# import the edited CSV (set_tags / add_tags / remove_tags / note)
forge materialize refresh-datapackage [--pack ID]... [--limit N] [--dry-run]
```

Environment: `FORGE_DB_URL`; `FORGE_LLM_URL` (mandatory, loopback refused, no default);
`FORGE_LLM_MODEL` (optional — see *Model* below). `forge tags` takes the same curation advisory
lock as `packs resolve` and `classify` (exit 3 if one is running).

Packs are processed in waves of 100: read facts → LLM → write → commit. A killed run resumes where
it stopped (the LLM answers are already cached), and `--llm-limit` makes a first pass cheap and a
second pass complete it.

### Model

The served model changes regularly, so the model name is **not** configuration to keep in sync.
`FORGE_LLM_URL` stays mandatory; `FORGE_LLM_MODEL` is optional (or `auto`), and `GET {url}/models`
is consulted with a 5 s timeout (`forge.packs.llm.resolve_model`, shared by `packs resolve`,
`classify` and `tags`):

| `FORGE_LLM_MODEL` | `/models` says | Result |
| --- | --- | --- |
| set | lists it | use it |
| set | does not list it, exactly one model served | use the served one, log a warning with both names |
| set | does not list it, none or several served | `LlmConfigError` listing the served ids |
| unset / `auto` | exactly one served | use it |
| unset / `auto` | none or several | `LlmConfigError` listing the served ids |
| set | unreachable | use it as given (no network guess) |
| unset / `auto` | unreachable | `LlmConfigError` |

A chat reply of HTTP 404 (the server no longer knows the model) re-resolves once and retries the
call with the served model. The model is **not** part of any cache key: `classify` fingerprints
hash the units + metadata + prompt, `packs` pair fingerprints hash the evidence + prompt, and
`tag_decisions` is keyed by evidence + prompt hash, so swapping the served model never re-asks a
question that already has an answer. It is recorded in the `model` column of every decision row
(`pack_decisions`, `classify_decisions`, `tag_decisions`) — the model that actually answered, after
any re-resolution. To re-ask on purpose, change the prompt version (`PROMPT_VERSION`).

## Storage (Alembic `0006_tags`, after `0004_packs`)

* `packs.tags` — the merged list (already existed); `packs.tags_fingerprint`, `packs.tagged_at` —
  set when `forge tags` last wrote the pack. Once `tags_fingerprint` is set, `forge classify` no
  longer rewrites that pack's `tags` (it re-reads classify's decision as an input instead), so the
  pipeline order is `packs resolve` → `classify` → `tags` → `materialize` and a classify rerun never
  discards tags.
* `tag_decisions` — the LLM answer cache: `input_fingerprint` (sha256 of the evidence + prompt
  hash), `prompt_hash`, `model`, `verdict`, `tags` (normalised), `raw_tags` (as returned), `error`,
  `evidence`. Latest row per fingerprint wins.
* `tag_overrides` — the owner's edits, keyed by the pack's unit key (survives pack id changes).

A pack is rewritten only when its inputs fingerprint (code tags, classify tags, LLM tags,
overrides, rules version, prompt hash) or its list changed, so a rerun with nothing new writes
nothing.

## Owner overrides

`forge tags review --out tags.csv` writes `pack_id, unit_key, category, name, tags, set_tags,
add_tags, remove_tags, note`. Fill the `set_` / `add_` / `remove_` cells (`;`-separated) and run
`forge tags override --file tags.csv`. On every run: `set_tags` **replaces** every derived tag,
`add_tags` are appended (never singularised), `remove_tags` are dropped. Blank cells change
nothing; an existing override is kept unless the new CSV sets that column. Overrides are never
overwritten by a rerun, by `classify`, or by the model. `forge classify override` tags (the older
loop) are honoured too: they replace classify's own tags as an input.

## Getting the tags into Manyfold

`forge materialize apply` (new packs) and `forge materialize refresh-datapackage` (packs already
materialized) write `keywords` in `datapackage.json`:

```json
{ "name": "agent-carter", "title": "Agent Carter", "keywords": ["dc", "sanix", "stl", "marvel", "agent-carter", "bust"], "resources": [ … ] }
```

* A pack `forge tags` has run for gets exactly its `packs.tags` as `keywords`; an untagged pack
  keeps the earlier `[category, source, creator]`.
* `refresh-datapackage` rewrites only that one key, only when it differs, for packs of the active
  (or `--plan`) materialize plan with status `done`/`incomplete`: new temp name + `rename()` through
  the write guard, v2 only; the old inode is never opened for write; a missing, unreadable or
  symlinked `datapackage.json` is counted and skipped, never created; the plan's
  `materialize_packs.meta` is synced so a later `apply` of the same plan writes the same keywords.
  `--dry-run` reports `would_update` and writes nothing. It never touches the source tree.

**How Manyfold reads them.** In this fork a library scan / rescan does **not** read
`datapackage.json` for tags — `Scan::Model::AddNewFilesJob` ignores the file and
`Scan::Model::ParseMetadataJob` only adds tags from the folder name and the path template. The
`keywords` array is applied by the operator rake task `manyfold:apply_datapackages`
(`lib/tasks/apply_datapackages.rake`, `DataPackage::ModelDeserializer`: `keywords` → `tag_list`):

```bash
bundle exec rake manyfold:apply_datapackages LIBRARY_ID=<id> DRY_RUN=1   # preview
bundle exec rake manyfold:apply_datapackages LIBRARY_ID=<id>             # apply
```

It runs inline (no Sidekiq queue needed for the task itself). It is **additive**: the new tag list
is `existing tags ∪ keywords` (lowercased, de-duplicated), written only when the keywords add
something, so a tag a user added or edited in Manyfold is never removed and a rerun is a no-op.
Tags that `forge tags` later drops from a pack are therefore not removed from the Manyfold model
(remove those in Manyfold, or bulk-edit).

## Tests

`tests/tags/` (normalisation, derivation, LLM parsing, the DB run with a fake OpenAI-compatible
server, overrides, classify interplay), `tests/packs/test_llm_model.py` (model auto-resolve against
a fake server), `tests/materialize/test_refresh.py` (keywords, atomic rewrite, hostile paths,
hardlinked/symlinked files). `tests/materialize/test_fence.py` still fences every write primitive
to `guard.py`; `refresh.py` writes only through `WriteGuard`/`TempWriter`.
