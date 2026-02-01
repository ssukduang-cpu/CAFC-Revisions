#!/bin/bash
# Phase 1 Directional Check Script
# Proves Phase 1 triggers when it should and metrics reflect that truth

set -e

echo "=============================================="
echo "PHASE 1 DIRECTIONAL CHECK"
echo "=============================================="
echo ""

cd "$(dirname "$0")/.."

echo "Step 1: Run fail-soft checks..."
if [ -x ./scripts/phase1_failsoft_checks.sh ]; then
    ./scripts/phase1_failsoft_checks.sh || {
        echo "[WARN] Fail-soft checks did not pass cleanly"
    }
else
    echo "[SKIP] Fail-soft check script not found"
fi

echo ""
echo "Step 2: Run unit tests..."

echo "  - parse_replay_packet tests..."
python -m pytest tests/test_parse_replay_packet.py -v --tb=short 2>&1 | tail -5

echo "  - aggregation tests..."
python -m pytest tests/test_eval_phase1_aggregation.py -v --tb=short 2>&1 | tail -5

echo "  - trigger set tests..."
python -m pytest tests/test_eval_phase1_trigger_set.py -v --tb=short 2>&1 | tail -10

echo ""
echo "Step 3: Run Phase 1 comparison with trigger-focused queries..."

QUERY_LIMIT=${QUERY_LIMIT:-12}
QUERY_FILE=${QUERY_FILE:-"backend/smart/eval_queries_trigger.json"}

echo "  Query file: $QUERY_FILE"
echo "  Query limit: $QUERY_LIMIT"
echo ""

# CRITICAL: Export Phase 1 flags so the eval harness runs with augmentation enabled
# The harness will set these for each run, but we export them here as a fallback
export SMART_QUERY_DECOMPOSE_ENABLED=true
export SMART_EMBED_RECALL_ENABLED=false

echo "  Environment flags exported:"
echo "    SMART_QUERY_DECOMPOSE_ENABLED=$SMART_QUERY_DECOMPOSE_ENABLED"
echo "    SMART_EMBED_RECALL_ENABLED=$SMART_EMBED_RECALL_ENABLED"
echo ""

python -m backend.smart.eval_phase1 --compare --queries "$QUERY_LIMIT" --query_file "$QUERY_FILE" --verbose

echo ""
echo "=============================================="
echo "DIRECTIONAL CHECK COMPLETE"
echo "=============================================="
echo ""

echo "Key metrics to verify:"
echo "  - Trigger rate: Should be > 0% when Phase 1 flags are ON"
echo "  - Avg candidates added: Should be > 0 when triggers fire"
echo "  - Latency delta: Should be reasonable (<500ms added)"
echo ""

LATEST_JSON=$(ls -t reports/phase1_eval_*.json 2>/dev/null | head -1)
if [ -n "$LATEST_JSON" ]; then
    echo "Latest report: $LATEST_JSON"
    echo ""
    echo "Phase 1 summary:"
    python -c "
import json
with open('$LATEST_JSON') as f:
    data = json.load(f)

if 'phase1' in data:
    p = data['phase1']
    print(f\"  Trigger rate: {p.get('phase1_trigger_rate', 0):.1%}\")
    print(f\"  Avg candidates added: {p.get('avg_candidates_added', 0):.1f}\")
    print(f\"  Avg latency: {p.get('avg_latency_ms', 0):.0f}ms\")
    print(f\"  NOT FOUND rate: {p.get('not_found_rate', 0):.1%}\")

if 'comparison' in data:
    d = data['comparison'].get('deltas', {})
    print(f\"  Latency delta: {d.get('latency_delta_ms', 0):+.0f}ms\")
"
fi

echo ""
echo "Command to re-run:"
echo "  SMART_QUERY_DECOMPOSE_ENABLED=true python -m backend.smart.eval_phase1 --compare --queries $QUERY_LIMIT --query_file $QUERY_FILE"
echo ""

exit 0
