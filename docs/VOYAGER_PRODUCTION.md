# Voyager Production Operations Guide

This document describes the production operations for the Voyager observability layer in the CAFC Opinion Assistant.

## Overview

The Voyager layer provides non-invasive observability, audit replay, and governance capabilities without modifying core legal research logic.

## What Is Logged

### query_runs Table

Each query creates a `query_runs` record containing:

| Field | Description | Retention |
|-------|-------------|-----------|
| `run_id` | Unique identifier (UUID) | Permanent |
| `created_at` | Timestamp | Permanent |
| `conversation_id` | Session context | Permanent |
| `user_query` | Original query text | Permanent |
| `doctrine_tag` | Legal doctrine classification | Permanent |
| `corpus_version_id` | Corpus snapshot ID | Permanent |
| `retrieval_manifest` | Page IDs and scores (ordered) | Permanent |
| `context_manifest` | Page IDs and token counts | Permanent |
| `model_config` | Model, temperature, max_tokens | Permanent |
| `system_prompt_version` | Prompt version ID | Permanent |
| `final_answer` | Generated response | **Redacted after 90 days** |
| `citation_verifications` | Verification tiers and bindings | Permanent |
| `latency_ms` | Response time | Permanent |
| `failure_reason` | Error info if failed | Permanent |

### What Is NOT Logged

- Raw PDF text
- Full context passages
- Environment variables
- API keys or secrets
- HTTP headers
- Internal stack traces

## Retention Policy

| Age | Action |
|-----|--------|
| 0-90 days | Full data retained |
| 90-365 days | `final_answer` redacted to `[REDACTED]` |
| 365+ days | Row deleted entirely |

### Running Cleanup

```bash
# Preview changes (dry-run)
python -m backend.maintenance.cleanup_query_runs --dry-run

# Apply retention policy
python -m backend.maintenance.cleanup_query_runs --apply

# View statistics only
python -m backend.maintenance.cleanup_query_runs --stats
```

## Circuit Breaker

The audit logging uses a circuit breaker to prevent cascading failures:

| Parameter | Value |
|-----------|-------|
| Failure threshold | 5 consecutive failures |
| Cooldown period | 5 minutes |
| States | CLOSED → OPEN → HALF_OPEN → CLOSED |

**Behavior:**
- **CLOSED**: Normal operation, all writes attempted
- **OPEN**: Writes skipped (no DB attempt), responses unaffected
- **HALF_OPEN**: Single test write after cooldown

Circuit breaker state is process-local and does not persist across restarts.

## API Endpoints

### Public Endpoints

```bash
# Policy manifest (minimal circuit breaker exposure)
curl https://patentlawchat.com/api/policy

# Corpus version
curl https://patentlawchat.com/api/voyager/corpus-version
```

**Policy Manifest Security:**
- `/api/policy` exposes only `audit_logging.enabled` (true/false) and `audit_logging.state` (open/closed)
- No counters, timestamps, or cooldown details are exposed publicly
- Full circuit breaker details require API key authentication

### Protected Endpoints (Require API Key)

All protected endpoints require the `X-API-Key` header matching `EXTERNAL_API_KEY`.
If `EXTERNAL_API_KEY` is not set, endpoints return HTTP 503 (fail-closed).

```bash
# List recent query runs
curl -H "X-API-Key: YOUR_KEY" \
  "https://patentlawchat.com/api/voyager/query-runs?limit=50&offset=0"

# Get specific run
curl -H "X-API-Key: YOUR_KEY" \
  "https://patentlawchat.com/api/voyager/query-runs/{run_id}"

# Get replay packet (full audit record)
curl -H "X-API-Key: YOUR_KEY" \
  "https://patentlawchat.com/api/voyager/replay-packet/{run_id}"

# Get full circuit breaker details (protected)
curl -H "X-API-Key: YOUR_KEY" \
  "https://patentlawchat.com/api/voyager/circuit-breaker"

# Get retention statistics
curl -H "X-API-Key: YOUR_KEY" \
  "https://patentlawchat.com/api/voyager/retention-stats"
```

### Replay Packet Contents

The `/api/voyager/replay-packet/{run_id}` endpoint returns a complete audit record containing:

```json
{
  "run_id": "uuid",
  "created_at": "ISO timestamp",
  "conversation_id": "string|null",
  "user_query": "string",
  "doctrine_tag": "string|null",
  "corpus_version_id": "string",
  "retrieval_manifest": {"page_ids": [], "opinion_ids": [], "scores": []},
  "context_manifest": {"page_ids": [], "total_tokens": 0},
  "model_config": {"model": "gpt-4o", "temperature": 0.1, "max_tokens": 1500},
  "system_prompt_version": "v2.0-quote-first",
  "final_answer": "string|[REDACTED]",
  "citations_manifest": [{"tier": "strong", "page_id": "...", ...}],
  "latency_ms": 1234,
  "failure_reason": "string|null"
}
```

## Operational Verification

Run the one-command verification script to check all Voyager endpoints and tests:

```bash
./scripts/voyager_verify.sh
```

The script performs:
1. Checks `/api/policy` returns 200 and doesn't leak circuit breaker internals
2. Checks `/api/voyager/corpus-version` is accessible
3. Verifies `/api/voyager/query-runs` requires authentication (401/503)
4. Verifies `/api/voyager/circuit-breaker` requires authentication (401/503)
5. If `EXTERNAL_API_KEY` is set, tests protected endpoints with authentication
6. Runs golden tests in verify mode
7. Runs cleanup script --stats

Output shows clear PASS/FAIL lines and exits non-zero on any failure.

## Unit Tests (Production Hardening)

Run the voyager hardening tests:

```bash
python -m pytest backend/tests/test_voyager_hardening.py -v
```

Tests cover:
- Circuit breaker state transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
- Retention policy dry-run and apply modes
- Replay packet generation and size limits
- Create query run circuit breaker integration

## Golden Tests (Regression Verification)

```bash
# Create baseline snapshot
python -m backend.golden_tests --mode baseline

# Verify no regressions
python -m backend.golden_tests --mode verify

# Run without comparison
python -m backend.golden_tests --mode run
```

## Feature Flags

Both flags default to `false` and should remain OFF unless explicitly needed:

| Flag | Default | Purpose |
|------|---------|---------|
| `VOYAGER_EMBEDDINGS_ENABLED` | false | Enable vector embeddings (not implemented) |
| `VOYAGER_EXPORT_ENABLED` | false | Enable external export (not implemented) |

## Monitoring

### Check Audit Logging State (Public)

The audit logging state is included in the public policy manifest:

```bash
curl -s https://patentlawchat.com/api/policy | grep -o '"audit_logging"[^}]*}'
```

Returns: `"audit_logging":{"enabled":true,"state":"closed"}`

### Check Full Circuit Breaker Details (Protected)

Full circuit breaker internals require API key authentication:

```bash
curl -H "X-API-Key: YOUR_KEY" https://patentlawchat.com/api/voyager/circuit-breaker
```

### Retention Statistics

```bash
python -m backend.maintenance.cleanup_query_runs --stats
```

## Untouched Core Components

The Voyager layer does NOT modify:

- Doctrine classification
- Postgres FTS retrieval
- Precedence-aware ranking scorer
- Controlling SCOTUS injection
- Quotable passage extraction
- Context build/pruning
- LLM prompt strategy (quote-first)
- Citation verification
- Web search fallback ingestion
