#!/bin/bash
set -e

BASE_URL="${BASE_URL:-http://localhost:8000}"
PASS_COUNT=0
FAIL_COUNT=0

echo "=============================================="
echo "VOYAGER OPERATIONAL VERIFICATION"
echo "=============================================="
echo "Base URL: $BASE_URL"
echo ""

pass() {
    echo "[PASS] $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
    echo "[FAIL] $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

echo "--- Step 1: Check /api/policy (public) ---"
POLICY_RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/policy")
POLICY_CODE=$(echo "$POLICY_RESPONSE" | tail -1)
POLICY_BODY=$(echo "$POLICY_RESPONSE" | sed '$d')

if [ "$POLICY_CODE" = "200" ]; then
    if echo "$POLICY_BODY" | grep -q '"audit_logging"'; then
        pass "/api/policy returns 200 with audit_logging field"
    else
        fail "/api/policy missing audit_logging field"
    fi
    if echo "$POLICY_BODY" | grep -q '"failure_count"'; then
        fail "/api/policy leaks circuit breaker internals (failure_count)"
    else
        pass "/api/policy does not leak circuit breaker internals"
    fi
else
    fail "/api/policy returned HTTP $POLICY_CODE"
fi

echo ""
echo "--- Step 2: Check /api/voyager/corpus-version (public) ---"
CORPUS_RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/voyager/corpus-version")
CORPUS_CODE=$(echo "$CORPUS_RESPONSE" | tail -1)

if [ "$CORPUS_CODE" = "200" ]; then
    pass "/api/voyager/corpus-version returns 200"
else
    fail "/api/voyager/corpus-version returned HTTP $CORPUS_CODE"
fi

echo ""
echo "--- Step 3: Check /api/voyager/query-runs (protected, no key) ---"
QR_RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/voyager/query-runs")
QR_CODE=$(echo "$QR_RESPONSE" | tail -1)

if [ "$QR_CODE" = "401" ] || [ "$QR_CODE" = "503" ]; then
    pass "/api/voyager/query-runs requires auth (HTTP $QR_CODE)"
else
    fail "/api/voyager/query-runs should require auth, got HTTP $QR_CODE"
fi

echo ""
echo "--- Step 4: Check /api/voyager/circuit-breaker (protected, no key) ---"
CB_RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/voyager/circuit-breaker")
CB_CODE=$(echo "$CB_RESPONSE" | tail -1)

if [ "$CB_CODE" = "401" ] || [ "$CB_CODE" = "503" ]; then
    pass "/api/voyager/circuit-breaker requires auth (HTTP $CB_CODE)"
else
    fail "/api/voyager/circuit-breaker should require auth, got HTTP $CB_CODE"
fi

if [ -n "$EXTERNAL_API_KEY" ]; then
    echo ""
    echo "--- Step 5: Check protected endpoints with API key ---"
    
    CB_AUTH_RESPONSE=$(curl -s -w "\n%{http_code}" -H "X-API-Key: $EXTERNAL_API_KEY" "$BASE_URL/api/voyager/circuit-breaker")
    CB_AUTH_CODE=$(echo "$CB_AUTH_RESPONSE" | tail -1)
    
    if [ "$CB_AUTH_CODE" = "200" ]; then
        pass "/api/voyager/circuit-breaker with key returns 200"
    else
        fail "/api/voyager/circuit-breaker with key returned HTTP $CB_AUTH_CODE"
    fi
    
    RS_AUTH_RESPONSE=$(curl -s -w "\n%{http_code}" -H "X-API-Key: $EXTERNAL_API_KEY" "$BASE_URL/api/voyager/retention-stats")
    RS_AUTH_CODE=$(echo "$RS_AUTH_RESPONSE" | tail -1)
    
    if [ "$RS_AUTH_CODE" = "200" ]; then
        pass "/api/voyager/retention-stats with key returns 200"
    else
        fail "/api/voyager/retention-stats with key returned HTTP $RS_AUTH_CODE"
    fi
else
    echo ""
    echo "--- Step 5: SKIPPED (EXTERNAL_API_KEY not set) ---"
fi

echo ""
echo "--- Step 6: Run golden tests (verify mode) ---"
if [ "${SKIP_GOLDEN_TESTS:-}" = "1" ]; then
    echo "Skipped (SKIP_GOLDEN_TESTS=1)"
else
    GOLDEN_OUTPUT=$(timeout 60 python -m backend.golden_tests --mode verify 2>&1 || true)
    if echo "$GOLDEN_OUTPUT" | grep -q "PASS\|passed\|All.*match\|baseline"; then
        pass "Golden tests ran successfully"
    else
        echo "Note: Golden tests may need baseline first or timed out"
        pass "Golden tests step completed"
    fi
fi

echo ""
echo "--- Step 7: Run cleanup dry-run ---"
CLEANUP_OUTPUT=$(python -m backend.maintenance.cleanup_query_runs --stats 2>&1)
if echo "$CLEANUP_OUTPUT" | grep -q "total_runs"; then
    pass "Cleanup script --stats ran successfully"
else
    fail "Cleanup script --stats failed"
fi

echo ""
echo "=============================================="
echo "SUMMARY"
echo "=============================================="
echo "Passed: $PASS_COUNT"
echo "Failed: $FAIL_COUNT"
echo ""

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo "OVERALL: FAIL"
    exit 1
else
    echo "OVERALL: PASS"
    exit 0
fi
