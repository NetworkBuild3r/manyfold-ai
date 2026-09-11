#!/usr/bin/env bash
# INIT-027/SPEC-002 — Manyfold UI contract fence (matcher + self-test).
# Later specs flip --enforce jquery|invalid-scale|hex|base-class in ci.yml.
# GR-004: never green this fence by dropping directories from WALK_ROOTS.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

WALK_ROOTS=(app/views app/components app/helpers app/javascript)
HEX_ALLOWLIST_FILE="app/javascript/offscreen_renderer.ts"

# BASE_CLASSES / INPUT_CLASS unique prefixes (owning constants only).
BASE_CLASS_NEEDLE='inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg'
INPUT_CLASS_NEEDLE='block w-full rounded-lg border border-secondary-300 bg-white text-secondary-900'
BASE_CLASS_OWNERS=('app/components/base_button.rb' 'app/components/text_input_row.rb')

SELF_TEST_DIR="tmp/ui-contract-fence-self-test"
SELF_TEST_PLANT="${SELF_TEST_DIR}/_fence_plant.html.erb"

usage() {
  cat <<'EOF'
Usage: script/ui-contract-fence.sh [--self-test] [--enforce LIST] [--help]

Checks (listed for later specs to enable):
  jquery         jQuery( or $( in walked UI trees
  invalid-scale  semantic singles used as palettes (warning-400, danger-500, …)
  hex            raw / Tailwind arbitrary hex colours
  base-class     inlined BaseButton::BASE_CLASSES or TextInputRow::INPUT_CLASS prefixes

--enforce LIST   comma-separated checks, or "none" (default).
                 none = scan all WALK_ROOTS, report hits, exit 0 (CI for SPEC-002).
                 Enabling a check fails (exit 1) when that check has hits.
--self-test      plant violations under tmp/ (not app/), run all checks, require
                 matcher exit 1, then delete the plant. Outer exit 0 if the
                 matcher caught every planted class; exit 1 if the matcher is broken.
                 Always prints the inner FAIL transcript.

WALK_ROOTS (do not shrink to go green): app/views app/components app/helpers app/javascript
Hex allowlist when --enforce hex: app/javascript/offscreen_renderer.ts (Three.js) only.

Provenance: INIT-027/SPEC-002
EOF
}

ENFORCE="none"
DO_SELF_TEST=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --self-test)
      DO_SELF_TEST=1
      shift
      ;;
    --enforce)
      ENFORCE="${2:-}"
      if [[ -z "$ENFORCE" ]]; then
        echo "error: --enforce requires a value" >&2
        exit 2
      fi
      shift 2
      ;;
    --enforce=*)
      ENFORCE="${1#--enforce=}"
      shift
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v rg >/dev/null 2>&1; then
  echo "error: ripgrep (rg) is required for INIT-027/SPEC-002 ui-contract-fence" >&2
  exit 2
fi

# Returns 0 if check name is in the enforce set (not "none").
enforce_has() {
  local name="$1"
  [[ "$ENFORCE" == "none" ]] && return 1
  local IFS=','
  local item
  for item in $ENFORCE; do
    item="$(echo "$item" | tr -d '[:space:]')"
    [[ "$item" == "$name" ]] && return 0
  done
  return 1
}

validate_enforce() {
  if [[ "$ENFORCE" == "none" ]]; then
    return 0
  fi
  local IFS=','
  local item
  for item in $ENFORCE; do
    item="$(echo "$item" | tr -d '[:space:]')"
    case "$item" in
      jquery|invalid-scale|hex|base-class) ;;
      none)
        echo "error: do not mix none with other --enforce flags" >&2
        exit 2
        ;;
      *)
        echo "error: unknown --enforce check: ${item}" >&2
        echo "allowed: jquery, invalid-scale, hex, base-class, none" >&2
        exit 2
        ;;
    esac
  done
}

is_owner() {
  local file="$1"
  local owner
  for owner in "${BASE_CLASS_OWNERS[@]}"; do
    [[ "$file" == "$owner" ]] && return 0
  done
  return 1
}

# Print matching lines as path:line:text. Uses "$@" as extra rg args, then pattern, then roots.
rg_hits() {
  local pattern="$1"
  shift
  rg --line-number --no-heading --color=never -e "$pattern" "$@" || true
}

run_jquery() {
  local roots=("$@")
  rg_hits 'jQuery\(' --glob '!**/node_modules/**' --glob '!**/vendor/**' "${roots[@]}"
  rg_hits '\$\(' --glob '!**/node_modules/**' --glob '!**/vendor/**' "${roots[@]}"
}

run_invalid_scale() {
  local roots=("$@")
  # Semantic @theme singles (warning/danger/success/info) have no numeric scale.
  rg_hits '\b(warning|danger|success|info)-[0-9]+\b' --glob '!**/node_modules/**' --glob '!**/vendor/**' "${roots[@]}"
}

run_hex() {
  local roots=("$@")
  local raw
  raw="$(
    {
      rg_hits '\[#[0-9A-Fa-f]{3,8}\]' --glob '!**/node_modules/**' --glob '!**/vendor/**' "${roots[@]}"
      rg_hits '(^|[^[:alnum:]_])#[0-9A-Fa-f]{6}([^[:alnum:]]|$)' --glob '!**/node_modules/**' --glob '!**/vendor/**' "${roots[@]}"
    } | sort -u
  )"
  if [[ -z "$raw" ]]; then
    return 0
  fi
  local line path
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    path="${line%%:*}"
    if [[ "$path" == "$HEX_ALLOWLIST_FILE" ]]; then
      continue
    fi
    printf '%s\n' "$line"
  done <<<"$raw"
}

run_base_class() {
  local roots=("$@")
  local raw
  raw="$(
    {
      rg --line-number --no-heading --color=never -F -e "$BASE_CLASS_NEEDLE" --glob '!**/node_modules/**' --glob '!**/vendor/**' "${roots[@]}" || true
      rg --line-number --no-heading --color=never -F -e "$INPUT_CLASS_NEEDLE" --glob '!**/node_modules/**' --glob '!**/vendor/**' "${roots[@]}" || true
    } | sort -u
  )"
  if [[ -z "$raw" ]]; then
    return 0
  fi
  local line path
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    path="${line%%:*}"
    if is_owner "$path"; then
      continue
    fi
    printf '%s\n' "$line"
  done <<<"$raw"
}

FAIL_COUNT=0
REPORT_ONLY=0

emit_check() {
  local name="$1"
  shift
  local hits
  hits="$("$@" || true)"
  local n=0
  if [[ -n "$hits" ]]; then
    n="$(printf '%s\n' "$hits" | grep -c . || true)"
  fi
  printf '== check:%s hits:%s ==\n' "$name" "$n"
  if [[ -n "$hits" ]]; then
    printf '%s\n' "$hits"
  fi
  if [[ "$n" -gt 0 ]]; then
    if enforce_has "$name"; then
      FAIL_COUNT=$((FAIL_COUNT + 1))
      echo "FAIL enforce:${name}"
    else
      echo "report-only:${name} (not in --enforce; later spec will flip this flag)"
    fi
  else
    echo "PASS ${name}"
  fi
}

scan_roots() {
  local roots=("$@")
  echo "ui-contract-fence INIT-027/SPEC-002"
  echo "WALK_ROOTS: ${roots[*]}"
  echo "enforce: ${ENFORCE}"
  echo "hex_allowlist: ${HEX_ALLOWLIST_FILE}"
  emit_check jquery run_jquery "${roots[@]}"
  emit_check invalid-scale run_invalid_scale "${roots[@]}"
  emit_check hex run_hex "${roots[@]}"
  emit_check base-class run_base_class "${roots[@]}"
}

write_plant() {
  mkdir -p "$SELF_TEST_DIR"
  cat >"$SELF_TEST_PLANT" <<'PLANT'
<%# INIT-027/SPEC-002 self-test plant — tmp/ only, never app/ %>
<div
  class="bg-[#ff0000] border-warning-400 inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg"
  onclick="jQuery(this).hide(); $('#fence-plant').remove()">
</div>
PLANT
}

cleanup_plant() {
  rm -rf "$SELF_TEST_DIR"
}

run_self_test() {
  write_plant
  local inner_out inner_status
  inner_status=0
  ENFORCE="jquery,invalid-scale,hex,base-class"
  FAIL_COUNT=0
  set +e
  inner_out="$(scan_roots "$SELF_TEST_DIR" 2>&1)"
  inner_status=$?
  set -e
  # scan_roots exits 0; fail is FAIL_COUNT. Force inner matcher result from hits.
  if echo "$inner_out" | grep -q '^FAIL enforce:'; then
    inner_status=1
  fi
  echo "----- self-test inner transcript (matcher MUST exit 1) -----"
  printf '%s\n' "$inner_out"
  echo "----- end inner transcript inner_status=${inner_status} -----"
  cleanup_plant
  local missing=0
  echo "$inner_out" | grep -q 'FAIL enforce:jquery' || missing=1
  echo "$inner_out" | grep -q 'FAIL enforce:invalid-scale' || missing=1
  echo "$inner_out" | grep -q 'FAIL enforce:hex' || missing=1
  echo "$inner_out" | grep -q 'FAIL enforce:base-class' || missing=1
  if [[ "$inner_status" -ne 1 || "$missing" -ne 0 ]]; then
    echo "SELF-TEST FAILED: matcher did not fail on the tmp/ plant (INIT-027/SPEC-002)" >&2
    return 1
  fi
  if [[ -e "$SELF_TEST_PLANT" ]]; then
    echo "SELF-TEST FAILED: plant file still present after cleanup" >&2
    return 1
  fi
  echo "SELF-TEST PASSED: planted tmp/ violations failed the matcher; plant removed"
  return 0
}

validate_enforce

if [[ "$DO_SELF_TEST" -eq 1 ]]; then
  run_self_test
  exit $?
fi

missing_root=0
for d in "${WALK_ROOTS[@]}"; do
  if [[ ! -d "$d" ]]; then
    echo "error: WALK_ROOTS entry missing: $d (GR-004 — do not drop it)" >&2
    missing_root=1
  fi
done
if [[ "$missing_root" -ne 0 ]]; then
  exit 2
fi

if [[ "$ENFORCE" == "none" ]]; then
  REPORT_ONLY=1
fi

scan_roots "${WALK_ROOTS[@]}"

if [[ "$REPORT_ONLY" -eq 1 ]]; then
  echo "exit 0 (--enforce none; report only)"
  exit 0
fi

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  echo "ui-contract-fence FAILED (${FAIL_COUNT} enforced check(s) with hits)"
  exit 1
fi

echo "ui-contract-fence PASSED"
exit 0
