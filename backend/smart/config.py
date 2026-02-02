"""
Phase 1 Smartness Configuration

All feature flags default to OFF for safety.
"""

import os

SMART_EMBED_RECALL_ENABLED = os.environ.get("SMART_EMBED_RECALL_ENABLED", "false").lower() == "true"
SMART_QUERY_DECOMPOSE_ENABLED = os.environ.get("SMART_QUERY_DECOMPOSE_ENABLED", "false").lower() == "true"

# Eval-only flag: bypass strong baseline gating to force Phase 1 to run
EVAL_FORCE_PHASE1 = os.environ.get("EVAL_FORCE_PHASE1", "false").lower() == "true"

PHASE1_BUDGET_MS = int(os.environ.get("PHASE1_BUDGET_MS", "500"))
MAX_AUGMENT_CANDIDATES = int(os.environ.get("MAX_AUGMENT_CANDIDATES", "1"))
MIN_FTS_RESULTS = int(os.environ.get("MIN_FTS_RESULTS", "8"))
MIN_TOP_SCORE = float(os.environ.get("MIN_TOP_SCORE", "0.15"))
MAX_SUBQUERIES = int(os.environ.get("MAX_SUBQUERIES", "2"))
MAX_EMBED_CANDIDATES = int(os.environ.get("MAX_EMBED_CANDIDATES", "30"))

STRONG_BASELINE_MIN_SOURCES = int(os.environ.get("STRONG_BASELINE_MIN_SOURCES", "8"))
STRONG_BASELINE_MIN_SCORE = float(os.environ.get("STRONG_BASELINE_MIN_SCORE", "0.3"))

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))
