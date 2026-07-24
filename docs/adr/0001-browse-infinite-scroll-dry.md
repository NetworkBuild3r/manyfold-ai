# ADR 0001: Browse infinite-scroll DRY contract

**Status:** Accepted  
**Date:** 2026-07-24  
**Provenance:** `INIT-003/SPEC-001`  
**Context skill:** `.cursor/skills/manyfold/manyfold-ui/references/infinite-scroll.md`

---

## Context

Manyfold card browse (models / creators / collections indexes, and model lists on creator and
collection **show**) must infinite-scroll the same way. A stack already exists (`BrowseGrid`,
Stimulus `infinite-scroll`, Turbo Streams, shared sentinels). Without a binding contract,
implementers paste divergent ERB shells, duplicate window prep, or mount scroll chrome on show
pages without a `format.turbo_stream` responder (live failure: HTTP **406** on
`/creators/:id?offset=…&window=after`).

## Decision

Adopt **one DRY standard** for every library card grid that infinite-scrolls:

1. **One Stimulus controller** — `infinite-scroll` only. No second infinite-scroll JS library.
2. **Client-owned fetch URLs** — build from `location.href` + `offset` / `per_page` / `window`.
   Sentinels expose flags and totals only (`has_more_*`, `total_count`, `offset`, `returned`).
3. **One server window prep** — shared offset/limit/`@browse_*` math; `.includes` / preload
   **before** materializing the window.
4. **One shared ERB grid chrome** — a single application partial wires
   `data-controller="infinite-scroll"` + grid + top/bottom `browse_scroll_sentinel` + status /
   back-to-top. Surface-specific chrome (search, chips, facets, gallery) stays **outside** that
   partial.
5. **Stream if you mount chrome** — any action that renders the infinite-scroll shell MUST
   respond to `format.turbo_stream` (or `X-Infinite-Scroll`) and continue the same sentinel IDs.
   Creator/collection **show** that `render "models/list"` MUST stream via `models/page` (or
   equivalent targeting `models-scroll-sentinel*`). Do not “disable” scroll on show.
6. **Unassigned outside the card grid** — unassigned tiles live in `.browse-unassigned-chrome`
   above `.browse-card-grid`, only on first window (`offset == 0`), never matching `cardSelector`.
7. **Cards** — prefer Phlex (`Components::*`) with a stable class matching `cardSelector`. New
   browse surfaces do not introduce ViewComponent or a second pager.

### Pagination stack (fixed)

| Concern | Choice |
|---------|--------|
| HTML first window | Kaminari `.page.per(BrowseGrid.page_size)` |
| Stream windows | `BrowseGrid` offset + `per_page` + `window` (`before` \| `after`) |
| Transport | `fetch` → `Accept: text/vnd.turbo-stream.html` → `renderStreamMessage` |

### Touch list for a **new** browse card surface

Do only this — do not paste a fourth copy of the shell:

1. **Prepare** — call the shared window prep (via `BrowseListable` / `ModelListable` or the
   unified helper SPEC-002 lands).
2. **HTML** — render the shared infinite-grid partial with locals: `sentinel_prefix`, `grid_id`,
   `card_selector`, `storage_key_prefix`, `aria_label`, `meta`, `per_page`, i18n keys; yield cards.
3. **Stream** — thin `page.turbo_stream.erb` (or reuse `models/page` when the grid is models):
   insert cards before/after sentinel; **replace both** sentinels with updated meta.
4. **Respond** — `format.html` + `format.turbo_stream` on every action that mounts the chrome
   (index **and** show if show mounts it).
5. **Specs** — request coverage for HTML first window + turbo_stream `window=after` / `before`
   (never 406).

## Consequences

- Indexes and show pages that share `models/list` behave the same under scroll.
- DRY extraction (SPEC-002) and show stream wiring (SPEC-003) implement this ADR; they do not
  renegotiate the stack.
- Deploy requires a new image when controllers gain `format.turbo_stream` (cannot hot-patch
  `respond_to`).

## Forbidden

| Do not | Why |
|--------|-----|
| Add Pagy (or any second pager) for library grids | BrowseGrid + Kaminari are the stack |
| Treat sentinel `data-next-url` / `data-prev-url` as fetch authority | Client owns URLs |
| Put unassigned (or other non-card chrome) inside `.browse-card-grid` | Breaks row-window card accounting |
| Mount `data-controller="infinite-scroll"` without a matching turbo_stream responder | Causes HTTP 406; scroll stalls |
| Turbo Frame **replace** of the whole grid as primary paging | Replaces; does not window-insert |
| New Stimulus infinite-scroll controller for the same UX | One controller; extend it |
| Bare `render "list_chips"` from embedded `models/list` | Qualify `models/…` partials |

## References

- Skill: `.cursor/skills/manyfold/manyfold-ui/references/infinite-scroll.md`
- Initiative: `INIT-003-manyfold-browse-infinite-scroll-dry`
- Live RCA: show pages 406 without `format.turbo_stream`; `/models` indexes already stream 200
