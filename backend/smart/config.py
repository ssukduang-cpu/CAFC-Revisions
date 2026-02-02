"""
Phase 1 Smartness Configuration

All feature flags default to OFF for safety.

PRODUCTION DEFAULTS:
- PHASE1_ENABLED=false (umbrella flag - must be true for any Phase1 to run)
- SMART_EMBED_RECALL_ENABLED=false
- SMART_QUERY_DECOMPOSE_ENABLED=false
- EVAL_FORCE_PHASE1=false (eval-only, never enable in production)
"""

import os
import logging

logger = logging.getLogger(__name__)

# Umbrella flag - MUST be true for any Phase1 augmentation to run
PHASE1_ENABLED = os.environ.get("PHASE1_ENABLED", "false").lower() == "true"

# Individual feature flags (only apply if PHASE1_ENABLED is true)
SMART_EMBED_RECALL_ENABLED = PHASE1_ENABLED and os.environ.get("SMART_EMBED_RECALL_ENABLED", "false").lower() == "true"
SMART_QUERY_DECOMPOSE_ENABLED = PHASE1_ENABLED and os.environ.get("SMART_QUERY_DECOMPOSE_ENABLED", "false").lower() == "true"

# Eval-only flag: bypass strong baseline gating to force Phase 1 to run
# WARNING: Never enable in production - only for eval harness
_EVAL_MODE = os.environ.get("PHASE1_EVAL_MODE", "false").lower() == "true"
EVAL_FORCE_PHASE1 = _EVAL_MODE and os.environ.get("EVAL_FORCE_PHASE1", "false").lower() == "true"

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

# Log effective flags at module load (once)
_flags_logged = False

def log_effective_flags():
    """Log effective Phase1 flags. Call once at startup."""
    global _flags_logged
    if _flags_logged:
        return
    _flags_logged = True
    
    logger.info(
        f"[Phase1 Config] PHASE1_ENABLED={PHASE1_ENABLED}, "
        f"decompose={SMART_QUERY_DECOMPOSE_ENABLED}, embed={SMART_EMBED_RECALL_ENABLED}, "
        f"eval_force={EVAL_FORCE_PHASE1}"
    )
