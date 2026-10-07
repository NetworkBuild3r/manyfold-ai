# SPEC-005 · Frontend: Model-page delete UX for archive-adopted images

## Metadata

```yaml
spec_id: SPEC-005
initiative_id: INIT-001
title: Delete confirmation and outcome messaging for archive-adopted images
domain: frontend
status: ready
primary_prompt: .claude/agents/principal-frontend-developer/AGENT.md   # agents dir absent — described persona (disclosed)
supplement_prompts: [.claude/agents/ux-designer/AGENT.md]
model: sonnet
autonomy_level: auto_tests
gate_actions: []
reversibility_class: branch
security_review: light
estimated_effort: 2 hours
blocked_by: [SPEC-004]
blocks: None
```

---

## Description

**Context:** After SPEC-004, deleting an adopted image also modifies its source archive. That is a
surprising, irreversible side effect, and the user must see it before confirming.

**Scope (in):** The existing delete control(s) for a ModelFile on the model page and the file page (locate
the partial at execution time; it is driven by `ModelFilesController#destroy`), the confirm text, the
success flash text, and i18n keys.

**Scope (out):** New endpoints or bulk actions.

## Acceptance Criteria

- [ ] ac-1: For a file with `adopted_from_entries` in a writable archive, the confirm text names the
  archive(s), for example "This also removes shot.png from Pack.zip. This cannot be undone." — covered: no
- [ ] ac-2: For an unwritable source (per SPEC-004 ac-4), the confirm text says the image will be hidden but
  stays inside the archive. — covered: no
- [ ] ac-3: Files without adopted entries keep today's confirm text unchanged. — covered: no
- [ ] ac-4: All new strings are i18n keys in `config/locales/en.yml`. `i18n-tasks` and `erb_lint` are clean.
  — covered: no

## Deliverables

- [ ] The model-file delete partial(s) under `app/views/` (exact path located at execution)
- [ ] `config/locales/en.yml` (new keys)
- [ ] An optional helper (e.g. `ModelFilesHelper#delete_confirmation_for(file)`) if logic would otherwise
  sit in the view
- [ ] Tests: request or view spec for the three confirm variants

## Security

- **Sensitivity:** light. Archive names are escaped by the view layer and never `html_safe`d.

## Verification Strategy

- **Claim:** The user sees an accurate, localized description of what deletion will do before confirming.
- **Check + executor:**
  - mechanized: `bundle exec rspec <new view/request spec>`, `bundle exec i18n-tasks health`,
    `bundle exec erb_lint --lint-all`.
  - human: the owner clicks delete on one adopted image in dev and reads the dialog.
- **Pass condition:** The three variant specs pass and both linters are clean. The manual dialog text
  matches ac-1 for a real adopted image.

## Integration Points

- Reads SPEC-004's writability check (expose it as a method on the service or model, not duplicated in
  the view).
- **Provenance tag:** `INIT-001/SPEC-005`
