# Phase 1 Evaluation Guide

This document describes how to run Phase 1 evaluation and interpret results.

## Overview

Phase 1 is an experimental query augmentation module that aims to improve retrieval recall for complex queries. It includes:

- **Query Decomposition**: Breaks multi-doctrine queries into subqueries
- **Embeddings Fallback**: Semantic search when FTS results are thin

**Production Status**: Phase 1 query decomposition is **ON by default** and can be disabled with `PHASE1_ENABLED=false` if needed.

## Configuration Flags

| Flag | Default | Description |
|------|---------|-------------|
| `PHASE1_ENABLED` | `true` | Umbrella flag - must be `true` for any Phase 1 to run |
| `SMART_QUERY_DECOMPOSE_ENABLED` | `true` | Enable query decomposition |
| `SMART_EMBED_RECALL_ENABLED` | `false` | Enable embeddings fallback |
| `EVAL_FORCE_PHASE1` | `false` | Bypass strong baseline gating (eval-only) |
| `PHASE1_EVAL_MODE` | `false` | Required for `EVAL_FORCE_PHASE1` to take effect |

## Running Evaluations

### Baseline vs Phase 1 Comparison

```bash
# Full comparison (12 queries)
PYTHONPATH=. python backend/smart/eval_phase1.py --compare --queries 12

# Quick test (3 queries)
PYTHONPATH=. python backend/smart/eval_phase1.py --compare --queries 3
```

### Baseline Only

```bash
PYTHONPATH=. python backend/smart/eval_phase1.py --baseline
```

### Phase 1 Only

```bash
PYTHONPATH=. python backend/smart/eval_phase1.py --phase1
```

## Analyzing Results

### Reports

Evaluations write two files:
- `reports/phase1_eval_YYYYMMDD_HHMMSS.json` - Full JSON with per-query data
- `reports/phase1_eval_summary_YYYYMMDD_HHMMSS.txt` - Human-readable summary

### Regression Script

```bash
# Process latest report automatically
python scripts/print_phase1_regressions.py

# Process specific reports (shell glob expansion)
python scripts/print_phase1_regressions.py reports/phase1_eval_*.json

# Process single report
python scripts/print_phase1_regressions.py --report reports/phase1_eval_20260202_034850.json

# Show more latency deltas
python scripts/print_phase1_regressions.py --top 10 reports/phase1_eval_*.json
```

## Interpreting Metrics

### NOT FOUND Rate

Percentage of queries that returned "NOT FOUND IN PROVIDED OPINIONS" instead of substantive answers.

- **Goal**: Reduce NOT FOUND rate
- **Regression**: Phase 1 NOT FOUND rate > Baseline NOT FOUND rate

### Latency Deltas

Time difference (ms) between Phase 1 and baseline.

- **Positive delta**: Phase 1 is slower (expected for triggered queries)
- **Negative delta**: Phase 1 is faster (rare)

### Trigger Rate

Percentage of queries where Phase 1 augmentation actually ran.

- **0%**: All queries skipped (strong baseline detected)
- **100%**: All queries triggered augmentation

### Skip Reasons

| Reason | Meaning |
|--------|---------|
| `skip_strong_baseline` | Baseline had ≥8 sources OR top_score ≥0.3 |
| `triggers_not_met` | No trigger conditions matched |
| `flags_off` | Phase 1 disabled via config |

### SCOTUS Coverage

Percentage of queries with at least one SCOTUS case in sources.

- **Note**: May show 0.0 if corpus lacks SCOTUS cases or detection needs tuning

## Smoke Tests

Run the smoke test to verify eval infrastructure:

```bash
./scripts/smoke_eval.sh
```

This verifies:
1. Phase 1 flags are OFF by default
2. Regression script handles positional args
3. Regression script handles --report flag
4. Help text shows examples
