#!/bin/bash
# Smoke test for Phase 1 evaluation and regression analysis
# Usage: ./scripts/smoke_eval.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "============================================================"
echo "Phase 1 Eval Smoke Test"
echo "============================================================"

# Test 1: Verify Phase 1 is OFF by default
echo ""
echo "[1/4] Verifying Phase 1 is OFF by default..."
python -c "
import os
# Ensure no env vars set
for key in ['PHASE1_ENABLED', 'SMART_QUERY_DECOMPOSE_ENABLED', 'SMART_EMBED_RECALL_ENABLED', 'EVAL_FORCE_PHASE1', 'PHASE1_EVAL_MODE']:
    os.environ.pop(key, None)

from importlib import reload
import backend.smart.config
reload(backend.smart.config)
from backend.smart import config as cfg

assert cfg.PHASE1_ENABLED == False, f'PHASE1_ENABLED should be False, got {cfg.PHASE1_ENABLED}'
assert cfg.SMART_QUERY_DECOMPOSE_ENABLED == False, f'SMART_QUERY_DECOMPOSE_ENABLED should be False'
assert cfg.SMART_EMBED_RECALL_ENABLED == False, f'SMART_EMBED_RECALL_ENABLED should be False'
assert cfg.EVAL_FORCE_PHASE1 == False, f'EVAL_FORCE_PHASE1 should be False without PHASE1_EVAL_MODE'
print('  ✓ All Phase 1 flags are OFF by default')
"

# Test 2: Regression script with positional args
echo ""
echo "[2/4] Testing regression script with positional args..."
LATEST_REPORT=$(ls -t reports/phase1_eval_*.json 2>/dev/null | head -1)
if [ -n "$LATEST_REPORT" ]; then
    python scripts/print_phase1_regressions.py "$LATEST_REPORT" --top 2 > /tmp/smoke_out.txt 2>&1
    if [ $? -le 1 ]; then
        echo "  ✓ Positional args work (exit code $?)"
    else
        echo "  ✗ Positional args failed"
        cat /tmp/smoke_out.txt
        exit 1
    fi
else
    echo "  ⚠ No reports found, skipping positional args test"
fi

# Test 3: Regression script with --report
echo ""
echo "[3/4] Testing regression script with --report flag..."
if [ -n "$LATEST_REPORT" ]; then
    python scripts/print_phase1_regressions.py --report "$LATEST_REPORT" --top 2 > /tmp/smoke_out.txt 2>&1
    if [ $? -le 1 ]; then
        echo "  ✓ --report flag works (exit code $?)"
    else
        echo "  ✗ --report flag failed"
        cat /tmp/smoke_out.txt
        exit 1
    fi
else
    echo "  ⚠ No reports found, skipping --report test"
fi

# Test 4: Regression script --help
echo ""
echo "[4/4] Testing regression script --help..."
python scripts/print_phase1_regressions.py --help > /tmp/smoke_out.txt 2>&1
if grep -q "positional" /tmp/smoke_out.txt && grep -q "Examples:" /tmp/smoke_out.txt; then
    echo "  ✓ --help shows positional args and examples"
else
    echo "  ✗ --help missing expected content"
    cat /tmp/smoke_out.txt
    exit 1
fi

echo ""
echo "============================================================"
echo "✅ All smoke tests passed!"
echo "============================================================"
