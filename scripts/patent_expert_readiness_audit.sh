#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="reports"
OUT_FILE="$OUT_DIR/patent_expert_readiness_${STAMP}.txt"
mkdir -p "$OUT_DIR"

run_check() {
  local title="$1"
  local cmd="$2"

  echo "============================================================" | tee -a "$OUT_FILE"
  echo "CHECK: $title" | tee -a "$OUT_FILE"
  echo "CMD:   $cmd" | tee -a "$OUT_FILE"
  echo "------------------------------------------------------------" | tee -a "$OUT_FILE"

  set +e
  bash -lc "$cmd" > /tmp/audit_step.out 2>&1
  local code=$?
  set -e

  cat /tmp/audit_step.out | tee -a "$OUT_FILE"
  echo "------------------------------------------------------------" | tee -a "$OUT_FILE"
  echo "EXIT_CODE: $code" | tee -a "$OUT_FILE"

  if [[ $code -eq 0 ]]; then
    echo "RESULT: PASS" | tee -a "$OUT_FILE"
  else
    echo "RESULT: FAIL" | tee -a "$OUT_FILE"
  fi

  echo | tee -a "$OUT_FILE"
}

{
  echo "Patent Expert Deployment Readiness Audit"
  echo "Timestamp: $(date -Iseconds)"
  echo "Repo: $ROOT_DIR"
  echo
} > "$OUT_FILE"

run_check "Merge-resolution integrity" "python scripts/verify_merge_resolutions.py"
run_check "TypeScript static check" "npm run check"
run_check "Production build" "npm run build"
run_check "Targeted reliability tests" "pytest -q backend/tests/test_query_canonicalization.py backend/tests/test_ranking_scorer.py tests/test_disambiguation.py"
run_check "Full Python test collection/run" "pytest -q"
run_check "Release gate" "bash scripts/ci_release_gate.sh"

# derive score
pass_count=$(rg -n "^RESULT: PASS$" "$OUT_FILE" | wc -l | tr -d ' ')
fail_count=$(rg -n "^RESULT: FAIL$" "$OUT_FILE" | wc -l | tr -d ' ')

grade="B-"
if [[ "$fail_count" -eq 0 ]]; then
  grade="A-"
elif [[ "$fail_count" -eq 1 ]]; then
  grade="B"
elif [[ "$fail_count" -ge 3 ]]; then
  grade="C+"
fi

{
  echo "============================================================"
  echo "SUMMARY"
  echo "PASS_COUNT: $pass_count"
  echo "FAIL_COUNT: $fail_count"
  echo "RECOMMENDED_GRADE: $grade"
  if [[ "$fail_count" -gt 0 ]]; then
    echo "DEPLOYMENT_READINESS: NO-GO (resolve failed checks)"
  else
    echo "DEPLOYMENT_READINESS: GO"
  fi
  echo "============================================================"
} | tee -a "$OUT_FILE"

echo "Audit written to: $OUT_FILE"
