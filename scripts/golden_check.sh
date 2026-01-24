#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
echo "BASE_URL=$BASE_URL"
echo

# show openapi paths (best-effort; not fatal)
echo "== OpenAPI paths (first 40 lines) =="
curl -fsS "${BASE_URL}/openapi.json" 2>/dev/null | python -c "import sys,json; j=json.load(sys.stdin) if not sys.stdin.isatty() else {}; print('\\n'.join(sorted(j.get('paths',{}).keys())[:40]))" || echo "<openapi.json not available or not JSON>"
echo

# perform the canonical diagnostic query and capture response
REQ='{"message":"When does reissue enlarge claim scope under 35 U.S.C. § 251? Please include a CITATION_MAP.","debug":true}'
echo "Posting diagnostic query to /api/chat ..."
curl -fsS -X POST "${BASE_URL}/api/chat" -H "Content-Type: application/json" -d "$REQ" -o /tmp/chat_resp.json || { echo "ERROR: /api/chat call failed"; exit 2; }
echo "Saved response -> /tmp/chat_resp.json"
echo

# Validate key debug fields and content with Python assertions
python - <<'PY'
import json, sys, re
r = json.load(open("/tmp/chat_resp.json"))
# Helpful quick prints for debugging
print("Top-level keys:", list(r.keys()))
dbg = r.get("debug") or {}
print("Debug keys:", list(dbg.keys()))
# Extract important checks
return_branch = r.get("return_branch")
markers_count = r.get("markers_count")
sources_count = r.get("sources_count")

# Also try to find CITATION_MAP in either debug or answer text
raw = ""
for k in ("raw_model_output","model_output"):
    raw = raw or dbg.get(k,"")
raw = raw or r.get("answer","") or r.get("message","") or ""
has_citation_map = bool(re.search(r"^CITATION_MAP:", raw, flags=re.M))
# Find simple canonical marker regex
canonical_markers = re.findall(r"^\[\d+\]\s+[0-9a-fA-F\-]{8,36}\s*\|\s*Page\s+\d+\s*\|\s*\"", raw, flags=re.M)

print("return_branch:", return_branch)
print("markers_count (envelope):", markers_count)
print("sources_count (envelope):", sources_count)
print("Has CITATION_MAP token in raw output?:", has_citation_map)
print("Canonical marker matches found in raw output:", len(canonical_markers))
print("\n--- RAW MODEL OUTPUT (first 1200 chars) ---\n" + raw[:1200] + "\n--- end ---\n")

# Assertions (fail loudly if any check fails)
errors = []
if return_branch not in ("ok", "accepted", "success"):
    errors.append(f"Unexpected return_branch: {return_branch!r} (expected 'ok' or similar)")
if not (isinstance(markers_count, int) and markers_count and markers_count > 0):
    errors.append(f"markers_count is not >0: {markers_count!r}")
if not (isinstance(sources_count, int) and sources_count and sources_count > 0):
    errors.append(f"sources_count is not >0: {sources_count!r}")
if not has_citation_map:
    errors.append("No CITATION_MAP token found in model raw output")
if len(canonical_markers) == 0:
    errors.append("No canonical citation markers detected in raw output (e.g., '[1] <opid> | Page N | \"...\"')")

if errors:
    print("DIAGNOSTIC: FAIL")
    for e in errors:
        print(" -", e)
    # also dump parser diagnostics if present
    parser_diag = dbg.get("parser_diagnostics") or dbg.get("cite_parser_debug") or None
    if parser_diag:
        print("\nParser diagnostics:", json.dumps(parser_diag)[:2000])
    sys.exit(3)

print("DIAGNOSTIC: PASS - grounding validated (return_branch ok, markers_count>0, sources_count>0, CITATION_MAP present)")
sys.exit(0)
PY

