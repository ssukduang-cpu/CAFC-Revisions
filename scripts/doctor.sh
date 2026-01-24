#!/bin/bash
# CAFC Opinion Assistant - System Diagnostic Script
# Run: bash scripts/doctor.sh

set -e

PASS="\033[32mPASS\033[0m"
FAIL="\033[31mFAIL\033[0m"
WARN="\033[33mWARN\033[0m"

API_BASE="${API_BASE:-http://localhost:8000}"
FRONTEND_BASE="${FRONTEND_BASE:-http://localhost:5000}"

echo "=============================================="
echo "  CAFC Opinion Assistant - System Diagnostic"
echo "=============================================="
echo "API Base: $API_BASE"
echo "Frontend Base: $FRONTEND_BASE"
echo ""

# Track results
PASSED=0
FAILED=0

pass() {
    echo -e "[$PASS] $1"
    ((PASSED++))
}

fail() {
    echo -e "[$FAIL] $1"
    ((FAILED++))
}

warn() {
    echo -e "[$WARN] $1"
}

# ============================================
# 1. SERVER REACHABILITY
# ============================================
echo "--- 1. Server Reachability ---"

# Check Python backend
if curl -s --max-time 5 "$API_BASE/api/status" | grep -q '"status":"ok"'; then
    pass "Python backend reachable at $API_BASE"
else
    fail "Python backend NOT reachable at $API_BASE"
fi

# Check frontend proxy
if curl -s --max-time 5 "$FRONTEND_BASE/api/status" | grep -q '"status":"ok"'; then
    pass "Frontend proxy routes to backend"
else
    fail "Frontend proxy NOT routing correctly"
fi

# ============================================
# 2. API ROUTE DISCOVERY
# ============================================
echo ""
echo "--- 2. API Route Discovery ---"

ROUTES=$(curl -s --max-time 10 "$API_BASE/openapi.json" 2>/dev/null)
if echo "$ROUTES" | grep -q '"/api/chat"'; then
    pass "/api/chat endpoint exists"
else
    fail "/api/chat endpoint NOT found in OpenAPI spec"
fi

if echo "$ROUTES" | grep -q '"/api/conversations"'; then
    pass "/api/conversations endpoint exists"
else
    fail "/api/conversations endpoint NOT found"
fi

if echo "$ROUTES" | grep -q '"/api/search"'; then
    pass "/api/search endpoint exists"
else
    fail "/api/search endpoint NOT found"
fi

# ============================================
# 3. DATABASE CONNECTIVITY
# ============================================
echo ""
echo "--- 3. Database Connectivity ---"

DB_CHECK=$(python3 -c "
import psycopg2, os, json
try:
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()
    results = {}
    for t in ['documents', 'document_pages', 'document_chunks', 'conversations', 'messages']:
        cur.execute(f'SELECT COUNT(*) FROM {t}')
        results[t] = cur.fetchone()[0]
    conn.close()
    print(json.dumps(results))
except Exception as e:
    print(json.dumps({'error': str(e)}))
" 2>/dev/null)

if echo "$DB_CHECK" | grep -q '"error"'; then
    fail "Database connection failed: $(echo $DB_CHECK | python3 -c 'import sys,json; print(json.load(sys.stdin).get(\"error\",\"\"))')"
else
    pass "Database connection successful"
    
    DOC_COUNT=$(echo "$DB_CHECK" | python3 -c "import sys,json; print(json.load(sys.stdin).get('documents', 0))")
    PAGE_COUNT=$(echo "$DB_CHECK" | python3 -c "import sys,json; print(json.load(sys.stdin).get('document_pages', 0))")
    CHUNK_COUNT=$(echo "$DB_CHECK" | python3 -c "import sys,json; print(json.load(sys.stdin).get('document_chunks', 0))")
    
    if [ "$DOC_COUNT" -gt 0 ]; then
        pass "Documents table: $DOC_COUNT rows"
    else
        fail "Documents table is empty"
    fi
    
    if [ "$PAGE_COUNT" -gt 0 ]; then
        pass "Document pages table: $PAGE_COUNT rows"
    else
        fail "Document pages table is empty"
    fi
    
    if [ "$CHUNK_COUNT" -gt 0 ]; then
        pass "Document chunks table: $CHUNK_COUNT rows"
    else
        warn "Document chunks table is empty (may be expected)"
    fi
fi

# ============================================
# 4. FTS SANITY CHECKS
# ============================================
echo ""
echo "--- 4. Full-Text Search Sanity ---"

# Test search 1: reissue
FTS1=$(curl -s --max-time 30 "$API_BASE/api/search?q=reissue%20251%20enlarge%20scope" 2>/dev/null)
FTS1_COUNT=$(echo "$FTS1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('results', [])))" 2>/dev/null || echo "0")
if [ "$FTS1_COUNT" -gt 0 ]; then
    pass "FTS search 'reissue 251 enlarge scope': $FTS1_COUNT results"
else
    fail "FTS search 'reissue 251 enlarge scope': no results"
fi

# Test search 2: claim construction
FTS2=$(curl -s --max-time 30 "$API_BASE/api/search?q=claim%20construction%20patent" 2>/dev/null)
FTS2_COUNT=$(echo "$FTS2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('results', [])))" 2>/dev/null || echo "0")
if [ "$FTS2_COUNT" -gt 0 ]; then
    pass "FTS search 'claim construction patent': $FTS2_COUNT results"
else
    fail "FTS search 'claim construction patent': no results"
fi

# Test search 3: waiver forfeiture (disambiguation test query)
FTS3=$(curl -s --max-time 30 "$API_BASE/api/search?q=waiver%20forfeiture%20Google" 2>/dev/null)
FTS3_COUNT=$(echo "$FTS3" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('results', [])))" 2>/dev/null || echo "0")
if [ "$FTS3_COUNT" -gt 0 ]; then
    pass "FTS search 'waiver forfeiture Google': $FTS3_COUNT results"
else
    warn "FTS search 'waiver forfeiture Google': no results (may need more ingestion)"
fi

# ============================================
# 5. RETRIEVAL PIPELINE SANITY
# ============================================
echo ""
echo "--- 5. Retrieval Pipeline ---"

# Create a test conversation and send a query
CONV_RESP=$(curl -s -X POST "$API_BASE/api/conversations" -H "Content-Type: application/json" -d '{}' 2>/dev/null)
CONV_ID=$(echo "$CONV_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id', ''))" 2>/dev/null)

if [ -n "$CONV_ID" ] && [ "$CONV_ID" != "" ]; then
    pass "Created test conversation: $CONV_ID"
    
    # Test retrieval with a simple query
    CHAT_RESP=$(curl -s --max-time 120 -X POST "$API_BASE/api/chat" \
        -H "Content-Type: application/json" \
        -d "{\"message\":\"What is claim construction?\", \"conversation_id\":\"$CONV_ID\"}" 2>/dev/null)
    
    ANSWER=$(echo "$CHAT_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('answer_markdown', '')[:100])" 2>/dev/null)
    
    if [ -n "$ANSWER" ] && [ "$ANSWER" != "" ]; then
        pass "LLM call succeeded, got response"
    else
        fail "LLM call failed or returned empty response"
    fi
    
    # Check debug fields
    PAGES_COUNT=$(echo "$CHAT_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('debug', {}).get('pages_count', -1))" 2>/dev/null)
    if [ "$PAGES_COUNT" -gt 0 ]; then
        pass "Retrieval returned $PAGES_COUNT pages"
    else
        warn "Retrieval returned 0 pages (may be expected for some queries)"
    fi
    
    RETURN_BRANCH=$(echo "$CHAT_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('debug', {}).get('return_branch', 'missing'))" 2>/dev/null)
    if [ "$RETURN_BRANCH" != "missing" ]; then
        pass "Response includes return_branch: $RETURN_BRANCH"
    else
        warn "Response missing return_branch in debug"
    fi
else
    fail "Could not create test conversation"
fi

# ============================================
# 6. DISAMBIGUATION SANITY
# ============================================
echo ""
echo "--- 6. Disambiguation Flow ---"

# Create fresh conversation for disambiguation test
DISAMB_CONV=$(curl -s -X POST "$API_BASE/api/conversations" -H "Content-Type: application/json" -d '{}' 2>/dev/null)
DISAMB_ID=$(echo "$DISAMB_CONV" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id', ''))" 2>/dev/null)

if [ -n "$DISAMB_ID" ] && [ "$DISAMB_ID" != "" ]; then
    # Step 1: Send ambiguous query
    DISAMB_Q1=$(curl -s --max-time 120 -X POST "$API_BASE/api/chat" \
        -H "Content-Type: application/json" \
        -d "{\"message\":\"What is the holding of Google?\", \"conversation_id\":\"$DISAMB_ID\"}" 2>/dev/null)
    
    IS_AMBIGUOUS=$(echo "$DISAMB_Q1" | grep -o "AMBIGUOUS QUERY" | head -1)
    
    if [ "$IS_AMBIGUOUS" = "AMBIGUOUS QUERY" ]; then
        pass "Disambiguation triggered for ambiguous query"
        
        # Check pending_disambiguation is stored
        PENDING=$(python3 -c "
import psycopg2, os, json
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute('SELECT pending_disambiguation FROM conversations WHERE id=%s', ('$DISAMB_ID',))
row = cur.fetchone()
if row and row[0]:
    print(len(row[0].get('candidates', [])))
else:
    print(0)
conn.close()
" 2>/dev/null)
        
        if [ "$PENDING" -gt 0 ]; then
            pass "Disambiguation candidates stored in DB ($PENDING options)"
        else
            fail "Disambiguation candidates NOT stored in DB"
        fi
        
        # Step 2: Send ordinal selection
        DISAMB_Q2=$(curl -s --max-time 120 -X POST "$API_BASE/api/chat" \
            -H "Content-Type: application/json" \
            -d "{\"message\":\"1\", \"conversation_id\":\"$DISAMB_ID\"}" 2>/dev/null)
        
        IS_RESOLVED=$(echo "$DISAMB_Q2" | grep -o "AMBIGUOUS QUERY" | head -1)
        NOT_INDEXED=$(echo "$DISAMB_Q2" | grep -o "not currently in our indexed" | head -1)
        
        if [ "$IS_RESOLVED" != "AMBIGUOUS QUERY" ] || [ "$NOT_INDEXED" = "not currently in our indexed" ]; then
            pass "Ordinal selection resolved (not re-triggered AMBIGUOUS QUERY)"
        else
            fail "Ordinal selection re-triggered AMBIGUOUS QUERY"
        fi
    else
        warn "Query did not trigger AMBIGUOUS QUERY (may be expected if only one Google case)"
    fi
else
    fail "Could not create disambiguation test conversation"
fi

# ============================================
# 7. RESPONSE SCHEMA CONSISTENCY
# ============================================
echo ""
echo "--- 7. Response Schema ---"

SCHEMA_TEST=$(curl -s --max-time 120 -X POST "$API_BASE/api/chat" \
    -H "Content-Type: application/json" \
    -d "{\"message\":\"What is patent infringement?\", \"conversation_id\":\"$CONV_ID\"}" 2>/dev/null)

HAS_ANSWER=$(echo "$SCHEMA_TEST" | python3 -c "import sys,json; d=json.load(sys.stdin); print('yes' if 'answer_markdown' in d else 'no')" 2>/dev/null)
HAS_SOURCES=$(echo "$SCHEMA_TEST" | python3 -c "import sys,json; d=json.load(sys.stdin); print('yes' if 'sources' in d else 'no')" 2>/dev/null)
HAS_DEBUG=$(echo "$SCHEMA_TEST" | python3 -c "import sys,json; d=json.load(sys.stdin); print('yes' if 'debug' in d else 'no')" 2>/dev/null)

if [ "$HAS_ANSWER" = "yes" ]; then
    pass "Response has answer_markdown field"
else
    fail "Response missing answer_markdown field"
fi

if [ "$HAS_SOURCES" = "yes" ]; then
    pass "Response has sources field"
else
    fail "Response missing sources field"
fi

if [ "$HAS_DEBUG" = "yes" ]; then
    pass "Response has debug field"
else
    fail "Response missing debug field"
fi

# Check debug subfields
MARKERS_COUNT=$(echo "$SCHEMA_TEST" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('debug', {}).get('markers_count', 'missing'))" 2>/dev/null)
SOURCES_COUNT=$(echo "$SCHEMA_TEST" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('debug', {}).get('sources_count', 'missing'))" 2>/dev/null)

if [ "$MARKERS_COUNT" != "missing" ]; then
    pass "Debug includes markers_count: $MARKERS_COUNT"
else
    warn "Debug missing markers_count"
fi

if [ "$SOURCES_COUNT" != "missing" ]; then
    pass "Debug includes sources_count: $SOURCES_COUNT"
else
    warn "Debug missing sources_count"
fi

# ============================================
# 8. CITATION PARSING & VERIFICATION
# ============================================
echo ""
echo "--- 8. Citation Parsing & Verification ---"

# Check if response has sources with quotes
SOURCES_LEN=$(echo "$SCHEMA_TEST" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('sources', [])))" 2>/dev/null)

if [ "$SOURCES_LEN" -gt 0 ]; then
    pass "Response includes $SOURCES_LEN source citations"
    
    # Verify quote structure
    FIRST_SOURCE=$(echo "$SCHEMA_TEST" | python3 -c "
import sys,json
d = json.load(sys.stdin)
sources = d.get('sources', [])
if sources:
    s = sources[0]
    fields = []
    if 'quote' in s: fields.append('quote')
    if 'case_name' in s: fields.append('case_name')
    if 'page_number' in s: fields.append('page_number')
    print(','.join(fields))
else:
    print('')
" 2>/dev/null)
    
    if echo "$FIRST_SOURCE" | grep -q "quote"; then
        pass "Sources include quote field"
    else
        warn "Sources may be missing quote field"
    fi
    
    if echo "$FIRST_SOURCE" | grep -q "case_name"; then
        pass "Sources include case_name field"
    else
        warn "Sources may be missing case_name field"
    fi
else
    warn "Response has no sources (may be expected for some queries)"
fi

# ============================================
# SUMMARY
# ============================================
echo ""
echo "=============================================="
echo "  DIAGNOSTIC SUMMARY"
echo "=============================================="
echo -e "Passed: \033[32m$PASSED\033[0m"
echo -e "Failed: \033[31m$FAILED\033[0m"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo -e "\033[32mAll checks passed!\033[0m"
    exit 0
else
    echo -e "\033[31mSome checks failed. Review output above.\033[0m"
    exit 1
fi
