# CAFC Opinion Assistant - Debugging Guide

## Quick Start

Run the diagnostic script to check all subsystems:

```bash
bash scripts/doctor.sh
```

## Diagnostic Checks Explained

### 1. Server Reachability
- **What it tests**: Python FastAPI backend on port 8000 and frontend proxy on port 5000
- **Common failures**:
  - Backend not started: Run `npm run dev` or check workflow status
  - Port conflict: Check `lsof -i :8000` for conflicting processes
- **Files to check**: `backend/main.py`, `server/index.ts`

### 2. API Route Discovery
- **What it tests**: OpenAPI spec includes required endpoints (`/api/chat`, `/api/conversations`, `/api/search`)
- **Common failures**:
  - Route not registered: Check `backend/main.py` for missing route decorators
  - Typo in path: Compare route paths in code vs OpenAPI output
- **Debug command**: `curl http://localhost:8000/openapi.json | python3 -m json.tool`

### 3. Database Connectivity
- **What it tests**: PostgreSQL connection, table existence, row counts
- **Common failures**:
  - `DATABASE_URL` not set: Check Secrets tab in Replit
  - Tables missing: Run migrations or check `backend/db_postgres.py` init
  - Zero rows: Run ingestion pipeline
- **Debug command**: 
  ```bash
  python3 -c "import psycopg2, os; print(psycopg2.connect(os.environ['DATABASE_URL']).cursor().execute('SELECT 1').fetchone())"
  ```

### 4. Full-Text Search (FTS) Sanity
- **What it tests**: PostgreSQL tsvector/GIN index returns results for test queries
- **Common failures**:
  - No results: FTS index may not be built, or no matching documents ingested
  - Slow queries: Missing GIN index on `search_vector` column
- **Files to check**: `backend/db_postgres.py` (search_pages function)
- **Debug command**:
  ```bash
  curl "http://localhost:8000/api/search?q=claim+construction"
  ```

### 5. Retrieval Pipeline
- **What it tests**: End-to-end flow from query → retrieval → LLM → response
- **Common failures**:
  - Empty response: OpenAI API key missing or invalid
  - Timeout: Increase timeout in proxy settings (server/index.ts)
  - No pages returned: Search query too specific or no matching documents
- **Files to check**: `backend/chat.py`, `server/index.ts` (proxy timeout)

### 6. Disambiguation Flow
- **What it tests**: AMBIGUOUS QUERY detection, candidate storage, ordinal resolution
- **Common failures**:
  - No AMBIGUOUS QUERY: Only one matching case, or prompt not triggering detection
  - Re-triggered AMBIGUOUS QUERY: `pending_disambiguation` not cleared properly
  - State not persisted: Check `conversations.pending_disambiguation` column
- **Files to check**: `backend/chat.py` (disambiguation section ~line 660-750)
- **Debug query**:
  ```sql
  SELECT id, pending_disambiguation FROM conversations 
  WHERE pending_disambiguation IS NOT NULL;
  ```

### 7. Response Schema
- **What it tests**: Response includes `answer_markdown`, `sources`, `debug` fields
- **Common failures**:
  - Missing field: Check return statements in `backend/chat.py`
  - Inconsistent schema: Different return branches may have different structures
- **Required fields**:
  - `answer_markdown`: String with formatted response
  - `sources`: Array of citation objects
  - `debug`: Object with `markers_count`, `sources_count`, `return_branch`, etc.

### 8. Citation Parsing & Verification
- **What it tests**: Sources array contains properly structured citations with quotes
- **Common failures**:
  - Empty sources: LLM didn't produce citations, or parsing failed
  - Missing quote field: Source structure changed in code
- **Files to check**: `backend/chat.py` (citation parsing section)

## Environment Variables

| Variable | Description | Location |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | Secrets |
| `AI_INTEGRATIONS_OPENAI_API_KEY` | OpenAI API key (auto-managed by Replit) | Replit AI Integration |
| `AI_INTEGRATIONS_OPENAI_BASE_URL` | OpenAI proxy endpoint | Replit AI Integration |
| `COURTLISTENER_API_TOKEN` | CourtListener API token for manifest building | Secrets |

## Log Locations

- **Workflow logs**: Check Replit's workflow panel or `/tmp/logs/`
- **Python backend**: Stdout from uvicorn process
- **Frontend proxy**: Stdout from Express server

## Common Issues & Solutions

### Issue: "AMBIGUOUS QUERY" keeps repeating
**Cause**: Disambiguation state cleared too early or LLM re-detecting ambiguity
**Solution**: 
1. Check `pending_disambiguation` column is being preserved for non-indexed selections
2. Verify resolved message includes "(Specifically: [case name])"

### Issue: Empty responses from /api/chat
**Cause**: OpenAI API error or timeout
**Solution**:
1. Check API key is valid
2. Increase proxy timeout in `server/index.ts`
3. Check for rate limiting

### Issue: FTS returns no results
**Cause**: No matching documents or index not built
**Solution**:
1. Verify documents are ingested (`document_pages` has rows)
2. Check `search_vector` column is populated
3. Rebuild FTS index if needed

### Issue: Citations not appearing
**Cause**: Quote verification failed or parsing issues
**Solution**:
1. Check `debug.markers_count` in response
2. Verify `debug.sources` array in response
3. Check quote matching logic (NFKC normalization)

## Running Tests

```bash
# Run Python tests
pytest tests/ -v

# Run specific test
pytest tests/test_disambiguation.py -v

# Run with coverage
pytest tests/ --cov=backend --cov-report=html
```

## Architecture Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Frontend      │────▶│  Express Proxy  │────▶│  FastAPI Backend │
│   (React/Vite)  │     │  (port 5000)    │     │  (port 8000)     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                         │
                                                         ▼
                              ┌─────────────────────────────────────┐
                              │           PostgreSQL               │
                              │  ┌─────────┐ ┌─────────┐ ┌────────┐│
                              │  │documents│ │doc_pages│ │chunks  ││
                              │  └─────────┘ └─────────┘ └────────┘│
                              │  ┌─────────────┐ ┌─────────────┐   │
                              │  │conversations│ │  messages   │   │
                              │  └─────────────┘ └─────────────┘   │
                              └─────────────────────────────────────┘
```

## Helpful Commands

```bash
# Check server status
curl http://localhost:8000/api/status

# List API routes
curl http://localhost:8000/openapi.json | python3 -c "import sys,json; print('\n'.join(json.load(sys.stdin)['paths'].keys()))"

# Test search
curl "http://localhost:8000/api/search?q=claim+construction"

# Check ingestion status
curl http://localhost:8000/api/admin/ingest_status

# View recent conversations
curl http://localhost:8000/api/conversations

# Check database counts
python3 -c "import psycopg2,os; c=psycopg2.connect(os.environ['DATABASE_URL']).cursor(); [print(f'{t}: {c.execute(f\"SELECT COUNT(*) FROM {t}\").fetchone()[0]}') for t in ['documents','document_pages','document_chunks']]"
```
