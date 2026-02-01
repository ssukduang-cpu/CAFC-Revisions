#!/bin/bash
set -e

echo "=============================================="
echo "PHASE 1 FAIL-SOFT & LATENCY CHECKS"
echo "=============================================="

PASS_COUNT=0
FAIL_COUNT=0

pass() {
    echo "[PASS] $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
    echo "[FAIL] $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

echo ""
echo "--- Test 1: Flags OFF returns immediately ---"
RESULT=$(python -c "
import os
os.environ['SMART_EMBED_RECALL_ENABLED'] = 'false'
os.environ['SMART_QUERY_DECOMPOSE_ENABLED'] = 'false'

from importlib import reload
import backend.smart.config
reload(backend.smart.config)
import backend.smart.augmenter
reload(backend.smart.augmenter)

from backend.smart.augmenter import augment_retrieval
import time

start = time.time()
_, telemetry = augment_retrieval('test query', [{'id': '1', 'score': 0.05}], None)
elapsed = (time.time() - start) * 1000

print(f'triggered={telemetry[\"triggered\"]} skipped_reason={telemetry[\"skipped_reason\"]} elapsed_ms={elapsed:.1f}')
" 2>/dev/null)

if echo "$RESULT" | grep -q "triggered=False"; then
    if echo "$RESULT" | grep -q "skipped_reason=flags_off"; then
        pass "Flags OFF skips augmentation"
    else
        fail "Flags OFF but wrong skip reason: $RESULT"
    fi
else
    fail "Augmentation triggered when flags OFF: $RESULT"
fi

echo ""
echo "--- Test 2: Embeddings enabled but missing - fails soft ---"
RESULT=$(python -c "
import os
os.environ['SMART_EMBED_RECALL_ENABLED'] = 'true'
os.environ['SMART_QUERY_DECOMPOSE_ENABLED'] = 'false'

from importlib import reload
import backend.smart.config
reload(backend.smart.config)
import backend.smart.augmenter
reload(backend.smart.augmenter)

from backend.smart.augmenter import augment_retrieval

try:
    baseline = [{'id': '1', 'score': 0.05}]
    result, telemetry = augment_retrieval('test patent eligibility', baseline, None)
    print(f'success=True triggered={telemetry[\"triggered\"]} embed_added={telemetry[\"embed_candidates_added\"]}')
except Exception as e:
    print(f'success=False error={type(e).__name__}')
" 2>/dev/null)

if echo "$RESULT" | grep -q "success=True"; then
    pass "Embeddings missing - request still succeeds (fail-soft)"
else
    fail "Embeddings missing caused failure: $RESULT"
fi

echo ""
echo "--- Test 3: Time budget respected ---"
RESULT=$(python -c "
import os
os.environ['SMART_EMBED_RECALL_ENABLED'] = 'false'
os.environ['SMART_QUERY_DECOMPOSE_ENABLED'] = 'true'

from importlib import reload
import backend.smart.config
reload(backend.smart.config)
import backend.smart.augmenter
reload(backend.smart.augmenter)

from backend.smart.augmenter import augment_retrieval
import time

start = time.time()
baseline = [{'id': '1', 'score': 0.05}]
_, telemetry = augment_retrieval('What is Alice and Mayo test for 101?', baseline, None)
elapsed = (time.time() - start) * 1000
budget = 500

print(f'elapsed_ms={elapsed:.1f} budget_ms={budget} within_budget={elapsed < budget * 1.2}')
" 2>/dev/null)

if echo "$RESULT" | grep -q "within_budget=True"; then
    pass "Augmentation respects time budget (<600ms)"
else
    fail "Augmentation exceeded time budget: $RESULT"
fi

echo ""
echo "--- Test 4: No exceptions propagate from Phase 1 ---"
RESULT=$(python -c "
import os
os.environ['SMART_EMBED_RECALL_ENABLED'] = 'true'
os.environ['SMART_QUERY_DECOMPOSE_ENABLED'] = 'true'

from importlib import reload
import backend.smart.config
reload(backend.smart.config)
import backend.smart.augmenter
reload(backend.smart.augmenter)

from backend.smart.augmenter import augment_retrieval

try:
    baseline = [{'id': '1', 'score': 0.05}]
    result, telemetry = augment_retrieval('complex multi-part query about Alice eligibility and 112 disclosure', baseline, None)
    print('no_exception=True')
except Exception as e:
    print(f'no_exception=False error={type(e).__name__}: {str(e)[:100]}')
" 2>/dev/null)

if echo "$RESULT" | grep -q "no_exception=True"; then
    pass "No exceptions propagate to caller"
else
    fail "Exception propagated: $RESULT"
fi

echo ""
echo "=============================================="
echo "SUMMARY"
echo "=============================================="
echo "Passed: $PASS_COUNT"
echo "Failed: $FAIL_COUNT"

if [ $FAIL_COUNT -eq 0 ]; then
    echo ""
    echo "FAIL-SOFT VERIFICATION: PASS"
    exit 0
else
    echo ""
    echo "FAIL-SOFT VERIFICATION: FAIL"
    exit 1
fi
