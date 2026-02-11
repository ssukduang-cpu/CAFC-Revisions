#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:${PORT:-5000}}"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "[smoke] DATABASE_URL is required" >&2
  exit 1
fi

echo "[smoke] checking fast health route: ${BASE_URL}/healthz"
curl -fsS --max-time 3 "${BASE_URL}/healthz" >/dev/null

echo "[smoke] checking API status route: ${BASE_URL}/api/status"
curl -fsS --max-time 5 "${BASE_URL}/api/status" >/dev/null

echo "[smoke] verifying database connectivity + core schema"
python3 - <<'PY'
import os
import psycopg2

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute("select 1")
assert cur.fetchone()[0] == 1
cur.execute("select to_regclass('public.opinions')")
if not cur.fetchone()[0]:
    raise SystemExit('missing opinions table')
cur.execute("select count(*) from opinions")
print(f"[smoke] opinions_count={cur.fetchone()[0]}")
cur.execute("select count(*) from chunks")
print(f"[smoke] chunks_count={cur.fetchone()[0]}")
cur.close(); conn.close()
PY

echo "[smoke] verifying retrieval path returns quickly"
curl -fsS --max-time 8 "${BASE_URL}/api/search?q=patent&limit=1" >/dev/null

echo "[smoke] checking PDF route quick response (file or redirect): ${BASE_URL}/pdf/nonexistent.pdf"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${BASE_URL}/pdf/nonexistent.pdf" || true)
if [[ "$code" != "200" && "$code" != "302" && "$code" != "404" ]]; then
  echo "[smoke] unexpected pdf route status: ${code}" >&2
  exit 1
fi

echo "[smoke] PASS"
