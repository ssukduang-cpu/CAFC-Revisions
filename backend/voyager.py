"""
Voyager AI Integration Module

Provides observability, governance, and replay capabilities for the CAFC Opinion Assistant.
This module is purely ADDITIVE and does NOT modify core retrieval, ranking, or generation logic.

Components:
- Corpus Versioning: Deterministic snapshot IDs for reproducibility
- Audit Replay Logging: Full query provenance capture
- Policy Manifest: Machine-readable governance metadata
"""

import os
import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from functools import lru_cache

from backend import db_postgres as db

logger = logging.getLogger(__name__)

VOYAGER_EMBEDDINGS_ENABLED = os.environ.get("VOYAGER_EMBEDDINGS_ENABLED", "false").lower() == "true"
VOYAGER_EXPORT_ENABLED = os.environ.get("VOYAGER_EXPORT_ENABLED", "false").lower() == "true"
SYSTEM_PROMPT_VERSION = "v2.0-quote-first"


@dataclass
class CorpusState:
    """Snapshot of corpus state for versioning."""
    document_count: int
    page_count: int
    latest_sync_at: Optional[str]
    latest_page_updated_at: Optional[str]
    version_id: str


@dataclass
class RetrievalManifest:
    """Manifest of retrieval results for audit."""
    page_ids: List[str]
    opinion_ids: List[str]
    scores: List[float]
    token_count: int


@dataclass
class ContextManifest:
    """Manifest of context building for audit."""
    page_ids: List[str]
    page_order: List[int]
    token_counts: List[int]
    total_tokens: int


@dataclass
class CitationVerification:
    """Single citation verification result."""
    citation_index: int
    page_id: Optional[str]
    opinion_id: Optional[str]
    confidence_tier: str
    match_type: str
    binding_tags: List[str]
    verified: bool


@dataclass
class QueryRun:
    """Complete audit record for a single query."""
    run_id: str
    created_at: str
    conversation_id: Optional[str]
    user_query: str
    doctrine_tag: Optional[str]
    corpus_version_id: str
    retrieval_manifest: Dict[str, Any]
    context_manifest: Dict[str, Any]
    model_config: Dict[str, Any]
    system_prompt_version: str
    final_answer: str
    citation_verifications: List[Dict[str, Any]]
    latency_ms: int
    failure_reason: Optional[str]


_corpus_version_cache = {}
_corpus_version_lock = threading.Lock()
_CACHE_TTL_SECONDS = 300


def compute_corpus_version_id() -> str:
    """
    Compute a deterministic corpus version ID based on current corpus state.
    
    Uses:
    - Latest sync_history completed timestamp
    - Document count
    - Page count  
    - Max document_pages updated_at
    
    Returns a stable SHA256-based short ID (first 12 chars).
    """
    global _corpus_version_cache
    
    cache_key = "corpus_version"
    now = time.time()
    
    with _corpus_version_lock:
        if cache_key in _corpus_version_cache:
            cached_value, cached_time = _corpus_version_cache[cache_key]
            if now - cached_time < _CACHE_TTL_SECONDS:
                return cached_value
    
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM documents) as doc_count,
                    (SELECT COUNT(*) FROM document_pages) as page_count,
                    (SELECT MAX(completed_at)::text FROM sync_history WHERE status = 'completed') as latest_sync,
                    (SELECT MAX(updated_at)::text FROM documents) as latest_doc
            """)
            row = cursor.fetchone()
            
            if row:
                doc_count = row.get('doc_count', 0) or 0
                page_count = row.get('page_count', 0) or 0
                latest_sync = row.get('latest_sync') or 'none'
                latest_doc = row.get('latest_doc') or 'none'
                
                version_string = f"docs:{doc_count}|pages:{page_count}|sync:{latest_sync}|doc_updated:{latest_doc}"
                version_hash = hashlib.sha256(version_string.encode()).hexdigest()[:12]
                
                with _corpus_version_lock:
                    _corpus_version_cache[cache_key] = (version_hash, now)
                
                logger.debug(f"Computed corpus version: {version_hash}")
                return version_hash
            
    except Exception as e:
        logger.error(f"Error computing corpus version: {e}")
    
    fallback = "unknown-000"
    with _corpus_version_lock:
        _corpus_version_cache[cache_key] = (fallback, now)
    return fallback


def get_corpus_state() -> CorpusState:
    """Get full corpus state including version ID."""
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM documents) as doc_count,
                    (SELECT COUNT(*) FROM document_pages) as page_count,
                    (SELECT MAX(completed_at)::text FROM sync_history WHERE status = 'completed') as latest_sync,
                    (SELECT MAX(updated_at)::text FROM documents) as latest_doc
            """)
            row = cursor.fetchone()
            
            if row:
                return CorpusState(
                    document_count=row.get('doc_count', 0) or 0,
                    page_count=row.get('page_count', 0) or 0,
                    latest_sync_at=row.get('latest_sync'),
                    latest_page_updated_at=row.get('latest_doc'),
                    version_id=compute_corpus_version_id()
                )
    except Exception as e:
        logger.error(f"Error getting corpus state: {e}")
    
    return CorpusState(
        document_count=0,
        page_count=0,
        latest_sync_at=None,
        latest_page_updated_at=None,
        version_id="unknown-000"
    )


def create_query_run(
    conversation_id: Optional[str],
    user_query: str,
    doctrine_tag: Optional[str] = None
) -> str:
    """
    Create a new query run and return its ID.
    Called at the start of query processing.
    """
    run_id = str(uuid.uuid4())
    corpus_version = compute_corpus_version_id()
    
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO query_runs (
                    id, conversation_id, user_query, doctrine_tag, 
                    corpus_version_id, created_at
                )
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, (run_id, conversation_id, user_query, doctrine_tag, corpus_version))
            conn.commit()
            logger.debug(f"Created query run: {run_id}")
    except Exception as e:
        logger.error(f"Error creating query run: {e}")
    
    return run_id


def record_retrieval_manifest(
    run_id: str,
    pages: List[Dict[str, Any]]
) -> None:
    """Record retrieval results (IDs and scores only, no text)."""
    try:
        manifest = {
            "page_ids": [str(p.get("id", "")) for p in pages[:50]],
            "opinion_ids": list(set(str(p.get("document_id") or p.get("opinion_id", "")) for p in pages[:50])),
            "scores": [float(p.get("score", 0)) for p in pages[:50]],
            "count": len(pages)
        }
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE query_runs 
                SET retrieval_manifest = %s
                WHERE id = %s
            """, (json.dumps(manifest), run_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Error recording retrieval manifest: {e}")


def record_context_manifest(
    run_id: str,
    context_pages: List[Dict[str, Any]],
    total_tokens: int
) -> None:
    """Record context building results (IDs and token counts only)."""
    try:
        manifest = {
            "page_ids": [str(p.get("id", "")) for p in context_pages],
            "page_order": list(range(len(context_pages))),
            "total_tokens": total_tokens,
            "page_count": len(context_pages)
        }
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE query_runs 
                SET context_manifest = %s
                WHERE id = %s
            """, (json.dumps(manifest), run_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Error recording context manifest: {e}")


def record_model_config(
    run_id: str,
    model_name: str,
    temperature: float,
    max_tokens: int
) -> None:
    """Record LLM configuration used for this query."""
    try:
        config = {
            "model": model_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "system_prompt_version": SYSTEM_PROMPT_VERSION
        }
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE query_runs 
                SET model_config = %s, system_prompt_version = %s
                WHERE id = %s
            """, (json.dumps(config), SYSTEM_PROMPT_VERSION, run_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Error recording model config: {e}")


def record_final_answer(
    run_id: str,
    answer: str,
    latency_ms: int,
    failure_reason: Optional[str] = None
) -> None:
    """Record final answer and latency."""
    try:
        answer_truncated = answer[:10000] if len(answer) > 10000 else answer
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE query_runs 
                SET final_answer = %s, latency_ms = %s, failure_reason = %s
                WHERE id = %s
            """, (answer_truncated, latency_ms, failure_reason, run_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Error recording final answer: {e}")


def record_citation_verifications(
    run_id: str,
    verifications: List[Dict[str, Any]]
) -> None:
    """Record citation verification results."""
    try:
        clean_verifications = []
        for v in verifications[:50]:
            clean_verifications.append({
                "citation_index": v.get("citation_index", 0),
                "page_id": str(v.get("page_id", "")) if v.get("page_id") else None,
                "opinion_id": str(v.get("opinion_id", "")) if v.get("opinion_id") else None,
                "confidence_tier": v.get("confidence_tier", "UNVERIFIED"),
                "match_type": v.get("match_type", "none"),
                "binding_tags": v.get("binding_tags", []),
                "verified": v.get("verified", False)
            })
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE query_runs 
                SET citation_verifications = %s
                WHERE id = %s
            """, (json.dumps(clean_verifications), run_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Error recording citation verifications: {e}")


def complete_query_run_async(
    run_id: str,
    pages: List[Dict[str, Any]],
    context_pages: List[Dict[str, Any]],
    total_tokens: int,
    model_name: str,
    temperature: float,
    max_tokens: int,
    answer: str,
    verifications: List[Dict[str, Any]],
    latency_ms: int,
    failure_reason: Optional[str] = None
) -> None:
    """
    Complete a query run with all data in a single non-blocking call.
    Runs in a background thread to avoid blocking the response.
    """
    def _record():
        try:
            retrieval_manifest = {
                "page_ids": [str(p.get("id", "")) for p in pages[:50]],
                "opinion_ids": list(set(str(p.get("document_id") or p.get("opinion_id", "")) for p in pages[:50])),
                "scores": [float(p.get("score", 0)) for p in pages[:50]],
                "count": len(pages)
            }
            
            context_manifest = {
                "page_ids": [str(p.get("id", "")) for p in context_pages],
                "page_order": list(range(len(context_pages))),
                "total_tokens": total_tokens,
                "page_count": len(context_pages)
            }
            
            model_config = {
                "model": model_name,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "system_prompt_version": SYSTEM_PROMPT_VERSION
            }
            
            clean_verifications = []
            for v in verifications[:50]:
                clean_verifications.append({
                    "citation_index": v.get("citation_index", 0),
                    "page_id": str(v.get("page_id", "")) if v.get("page_id") else None,
                    "opinion_id": str(v.get("opinion_id", "")) if v.get("opinion_id") else None,
                    "confidence_tier": v.get("confidence_tier", "UNVERIFIED"),
                    "match_type": v.get("match_type", "none"),
                    "binding_tags": v.get("binding_tags", []),
                    "verified": v.get("verified", False)
                })
            
            answer_truncated = answer[:10000] if len(answer) > 10000 else answer
            
            with db.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE query_runs SET
                        retrieval_manifest = %s,
                        context_manifest = %s,
                        model_config = %s,
                        system_prompt_version = %s,
                        final_answer = %s,
                        citation_verifications = %s,
                        latency_ms = %s,
                        failure_reason = %s
                    WHERE id = %s
                """, (
                    json.dumps(retrieval_manifest),
                    json.dumps(context_manifest),
                    json.dumps(model_config),
                    SYSTEM_PROMPT_VERSION,
                    answer_truncated,
                    json.dumps(clean_verifications),
                    latency_ms,
                    failure_reason,
                    run_id
                ))
                conn.commit()
                logger.debug(f"Completed query run: {run_id}")
        except Exception as e:
            logger.error(f"Error completing query run {run_id}: {e}")
    
    thread = threading.Thread(target=_record, daemon=True)
    thread.start()


def get_policy_manifest() -> Dict[str, Any]:
    """
    Get the machine-readable policy manifest for governance.
    Static configuration describing system behavior.
    """
    return {
        "version": "1.0",
        "system": "CAFC Opinion Assistant",
        "policies": {
            "quote_first": True,
            "verification_required": True,
            "verification_tiers": ["STRONG", "MODERATE", "WEAK", "UNVERIFIED"],
            "case_level_fallback_caps": "MODERATE",
            "determinism": {
                "temperature": 0.1,
                "model_pinned": True,
                "model_env_var": "CHAT_MODEL",
                "model_default": "gpt-4o",
                "corpus_version_bound": True
            },
            "web_fallback": {
                "enabled": True,
                "domains_allowlist": [
                    "courtlistener.com",
                    "scholar.google.com",
                    "law.cornell.edu",
                    "cafc.uscourts.gov",
                    "casetext.com"
                ]
            },
            "citation_confidence_scoring": {
                "binding_strict": 40,
                "binding_fuzzy": 25,
                "match_exact": 30,
                "match_partial": 15,
                "section_holding": 15,
                "section_dicta": -5,
                "recency_2020_plus": 10
            }
        },
        "corpus": asdict(get_corpus_state()),
        "features": {
            "voyager_embeddings_enabled": VOYAGER_EMBEDDINGS_ENABLED,
            "voyager_export_enabled": VOYAGER_EXPORT_ENABLED
        },
        "generated_at": datetime.utcnow().isoformat() + "Z"
    }


def get_query_run(run_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a query run by ID for replay/audit."""
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM query_runs WHERE id = %s
            """, (run_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
    except Exception as e:
        logger.error(f"Error getting query run: {e}")
    return None


def get_recent_query_runs(limit: int = 100) -> List[Dict[str, Any]]:
    """Get recent query runs for dashboard/debugging."""
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, created_at, conversation_id, doctrine_tag, 
                       corpus_version_id, latency_ms, failure_reason
                FROM query_runs 
                ORDER BY created_at DESC 
                LIMIT %s
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Error getting recent query runs: {e}")
    return []


def ensure_query_runs_table():
    """Ensure the query_runs table exists. Idempotent."""
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS query_runs (
                    id VARCHAR PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT NOW(),
                    conversation_id VARCHAR,
                    user_query TEXT,
                    doctrine_tag VARCHAR,
                    corpus_version_id VARCHAR,
                    retrieval_manifest JSONB,
                    context_manifest JSONB,
                    model_config JSONB,
                    system_prompt_version VARCHAR,
                    final_answer TEXT,
                    citation_verifications JSONB,
                    latency_ms INTEGER,
                    failure_reason TEXT
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_query_runs_created_at 
                ON query_runs(created_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_query_runs_conversation 
                ON query_runs(conversation_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_query_runs_corpus_version 
                ON query_runs(corpus_version_id)
            """)
            conn.commit()
            logger.info("query_runs table ensured")
    except Exception as e:
        logger.error(f"Error ensuring query_runs table: {e}")
