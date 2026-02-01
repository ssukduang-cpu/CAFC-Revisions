#!/bin/bash
# Phase 1 Smartness Evaluation Script
# Runs baseline and augmented comparisons and writes reports

set -e

echo "=============================================="
echo "PHASE 1 SMARTNESS EVALUATION"
echo "=============================================="

cd "$(dirname "$0")/.."

mkdir -p reports

echo ""
echo "Step 1: Verify fail-soft checks..."
if [ -x ./scripts/phase1_failsoft_checks.sh ]; then
    ./scripts/phase1_failsoft_checks.sh || {
        echo "[WARN] Fail-soft checks did not pass"
    }
else
    echo "[SKIP] Fail-soft check script not found"
fi

echo ""
echo "Step 2: Run unit tests for parse_replay_packet..."
python -m pytest tests/test_parse_replay_packet.py -v --tb=short 2>/dev/null || {
    echo "[WARN] Some unit tests failed, continuing..."
}

echo ""
echo "Step 3: Run Phase 1 comparison evaluation..."
QUERY_LIMIT=${QUERY_LIMIT:-5}
echo "Using query limit: $QUERY_LIMIT (set QUERY_LIMIT env var to change)"

python -m backend.smart.eval_phase1 --compare --queries "$QUERY_LIMIT"

echo ""
echo "=============================================="
echo "EVALUATION COMPLETE"
echo "=============================================="
echo ""
echo "Reports generated in: reports/"
ls -la reports/*.json reports/*.txt 2>/dev/null || echo "No reports found"
echo ""

LATEST_JSON=$(ls -t reports/phase1_eval_*.json 2>/dev/null | head -1)
if [ -n "$LATEST_JSON" ]; then
    echo "Latest JSON report: $LATEST_JSON"
fi

LATEST_TXT=$(ls -t reports/phase1_eval_summary_*.txt 2>/dev/null | head -1)
if [ -n "$LATEST_TXT" ]; then
    echo "Latest summary: $LATEST_TXT"
    echo ""
    cat "$LATEST_TXT"
fi

exit 0
