#!/usr/bin/env bash
set -euo pipefail

CMD=(pytest -q -rs backend/tests/test_ranking_scorer.py backend/tests/test_query_canonicalization.py tests/test_disambiguation.py)

echo "[release-gate] running guarded suite: ${CMD[*]}"
out="$(${CMD[@]} 2>&1)"
printf '%s\n' "$out"

if grep -q "SKIPPED \[" <<<"$out"; then
  echo "[release-gate] FAIL: ENV-PARITY-DISAMBIGUATION violated (skipped tests detected)." >&2
  exit 1
fi

echo "[release-gate] PASS: guarded suite ran with zero skipped tests."
