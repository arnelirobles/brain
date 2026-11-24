#!/usr/bin/env bash
# Run every --self-test in the repository and exit nonzero if any fails.
#
# A script opts in by handling --self-test; this finds them by that string, so a
# new hook or script is covered without editing this file. Each one gets 300
# seconds. Scripts without a self-test are listed, so a new one that skipped its
# test shows up here. The plugin's JSON files are also checked for duplicate keys:
# a text merge can leave two "PostToolUse" keys, which still parses, and the
# parser silently keeps only the last. Run it from anywhere: tests/run-all.sh
set -uo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root" || exit 2

# No self-test may reach the real brain database: a hook it spawns would migrate and write to it.
scratch=$(mktemp -d "${TMPDIR:-/tmp}/brain-run-all.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
export LEAN_BRAIN_DB="$scratch/brain.db"
mkdir -p "$scratch/home"
export HOME="$scratch/home"
# The self-tests assert the strict behaviour.
export LEAN_PROFILE=strict

# A while-read loop rather than mapfile, which macOS's bash 3.2 does not have.
scripts=()
while IFS= read -r s; do
  [ "$(basename "$s")" = "run-all.sh" ] && continue
  scripts+=("$s")
done < <(grep -l -- '--self-test' tools/* hooks/*.py lib/brain/web/*.py tests/*.py tests/*.sh 2>/dev/null | sort -u)
if [ "${#scripts[@]}" -eq 0 ]; then
  echo "run-all: found no scripts with a --self-test" >&2
  exit 1
fi

# macOS has no timeout unless coreutils is installed, as gtimeout. Without either the self-tests
# still run, only without the cap. The cap is 300 seconds.
cap_for() {
  echo 300
}
limit() {
  local secs=$1; shift
  if command -v timeout >/dev/null 2>&1; then timeout "$secs" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$secs" "$@"
  else "$@"; fi
}

failed=0
skipped=0
if out=$(python3 - .claude-plugin/*.json hooks/hooks.json 2>&1 <<'PY'
import json, sys
def no_dupes(pairs):
    keys = [k for k, _ in pairs]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise ValueError("duplicate keys: " + ", ".join(dupes))
    return dict(pairs)
for path in sys.argv[1:]:
    try:
        json.load(open(path), object_pairs_hook=no_dupes)
    except ValueError as e:
        sys.exit(f"{path}: {e}")
PY
); then
  echo "ok   plugin json has no duplicate keys"
else
  echo "FAIL plugin json"
  printf '%s\n' "$out" | sed 's/^/     /'
  failed=$((failed + 1))
fi

missing=$(grep -L -- '--self-test' tools/* hooks/*.py 2>/dev/null | xargs -r -n1 basename | tr '\n' ' ')
[ -n "$missing" ] && echo "no self-test: $missing"

for script in "${scripts[@]}"; do
  case "$script" in
    *.py) runner=(python3 "$script") ;;
    *.sh) runner=(bash "$script") ;;
    *) runner=("./$script") ;;
  esac
  cap=$(cap_for "$script")
  out=$(limit "$cap" "${runner[@]}" --self-test 2>&1); rc=$?
  # timeout exits 124 when it stops the command, which otherwise shows as a blank failure.
  [ "$rc" = 124 ] && out="${out:+$out
}timed out after ${cap} s"
  if [ "$rc" = 0 ]; then
    echo "ok   $script"
  elif [ "$rc" = 77 ]; then
    # 77 is a self-test saying this machine cannot run it, such as a Linux-only script on macOS.
    echo "skip $script: $(printf '%s\n' "$out" | tail -1)"
    skipped=$((skipped + 1))
  else
    echo "FAIL $script"
    printf '%s\n' "$out" | sed 's/^/     /'
    failed=$((failed + 1))
  fi
done

echo "run-all: ${#scripts[@]} self-tests, $failed failed, $skipped skipped"
[ "$failed" -eq 0 ]
