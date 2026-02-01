"""
Phase 1 Smartness Module

Provides recall augmentation for the CAFC Opinion Assistant:
- Query Decomposition: Detects multi-issue queries and decomposes them
- Embeddings Fallback: Semantic recall when FTS results are thin

All functionality is:
- Additive only (does not modify core retrieval/ranking logic)
- Behind feature flags (default OFF)
- Fail-soft (errors silently skip augmentation)
- Bounded (time budgets and candidate limits)
"""

from backend.smart.config import (
    SMART_EMBED_RECALL_ENABLED,
    SMART_QUERY_DECOMPOSE_ENABLED,
    PHASE1_BUDGET_MS,
    MAX_AUGMENT_CANDIDATES,
    MIN_FTS_RESULTS,
    MIN_TOP_SCORE,
    MAX_SUBQUERIES
)
