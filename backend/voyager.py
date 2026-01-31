"""
Voyager AI Integration Module

Provides observability, governance, and replay capabilities for the CAFC Opinion Assistant.
This module is purely ADDITIVE and does NOT modify core retrieval, ranking, or generation logic.

Components:
- Corpus Versioning: Deterministic snapshot IDs for reproducibility
- Audit Replay Logging: Full query provenance capture
- Policy Manifest: Machine-readable governance metadata
- Circuit Breaker: Protects against cascading DB failures
- Retention Policy: Manages query_runs data lifecycle
"""

import os
import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from functools import lru_cache

from backend import db_postgres as db

logger = logging.getLogger(__name__)

VOYAGER_EMBEDDINGS_ENABLED = os.environ.get("VOYAGER_EMBEDDINGS_ENABLED", "false").lower() == "true"
VOYAGER_EXPORT_ENABLED = os.environ.get("VOYAGER_EXPORT_ENABLED", "false").lower() == "true"
SYSTEM_PROMPT_VERSION = "v2.0-quote-first"

RETENTION_REDACT_DAYS = 90
RETENTION_DELETE_DAYS = 365


class CircuitBreaker:
    """
    In-memory circuit breaker for query_runs writes.
    States: CLOSED (normal), OPEN (skip writes), HALF_OPEN (testing)
    """
    
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
    
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: int = 300):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.lock = threading.Lock()
    
    def can_execute(self) -> bool:
        """Check if circuit allows execution."""
        with self.lock:
            if self.state == self.CLOSED:
                return True
            elif self.state == self.OPEN:
                if time.time() - self.last_failure_time >= self.cooldown_seconds:
                    self.state = self.HALF_OPEN
                    logger.debug("Circuit breaker: OPEN -> HALF_OPEN")
                    return True
                return False
            else:
                return True
    
    def record_success(self) -> None:
        """Record successful execution."""
        with self.lock:
            self.failure_count = 0
            if self.state == self.HALF_OPEN:
                self.state = self.CLOSED
                logger.info("Circuit breaker: HALF_OPEN -> CLOSED")
    
    def record_failure(self) -> None:
        """Record failed execution."""
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.state == self.HALF_OPEN:
                self.state = self.OPEN
                logger.warning("Circuit breaker: HALF_OPEN -> OPEN (test failed)")
            elif self.failure_count >= self.failure_threshold:
                self.state = self.OPEN
                logger.warning(f"Circuit breaker: CLOSED -> OPEN (threshold {self.failure_threshold} reached)")
    
    def get_state(self) -> Dict[str, Any]:
        """Get current circuit breaker state."""
        with self.lock:
            return {
                "state": self.state,
                "failure_count": self.failure_count,
                "last_failure_time": self.last_failure_time,
                "cooldown_remaining": max(0, self.cooldown_seconds - (time.time() - self.last_failure_time)) if self.state == self.OPEN else 0
            }


_circuit_breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=300)


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
    Uses circuit breaker to protect against DB failures.
    """
    run_id = str(uuid.uuid4())
    corpus_version = compute_corpus_version_id()
    
    if not _circuit_breaker.can_execute():
        logger.debug(f"Circuit breaker OPEN - skipping query_run insert for {run_id}")
        return run_id
    
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
            _circuit_breaker.record_success()
            logger.debug(f"Created query run: {run_id}")
    except Exception as e:
        _circuit_breaker.record_failure()
        logger.debug(f"Error creating query run (circuit breaker recorded): {e}")
    
    return run_id


def record_retrieval_manifest(
    run_id: str,
    pages: List[Dict[str, Any]]
) -> None:
    """Record retrieval results (IDs and scores only, no text). Preserves order."""
    try:
        seen_opinion_ids = []
        seen_set = set()
        for p in pages[:50]:
            oid = str(p.get("document_id") or p.get("opinion_id", ""))
            if oid and oid not in seen_set:
                seen_opinion_ids.append(oid)
                seen_set.add(oid)
        
        manifest = {
            "page_ids": [str(p.get("id", "")) for p in pages[:50]],
            "opinion_ids": seen_opinion_ids,
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
        "retention": {
            "redact_after_days": RETENTION_REDACT_DAYS,
            "delete_after_days": RETENTION_DELETE_DAYS
        },
        "audit_logging": {
            "enabled": True,
            "state": get_circuit_breaker_state()["state"]
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


def get_recent_query_runs(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """Get recent query runs for dashboard/debugging with pagination."""
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, created_at, conversation_id, doctrine_tag, 
                       corpus_version_id, latency_ms, failure_reason
                FROM query_runs 
                ORDER BY created_at DESC 
                LIMIT %s OFFSET %s
            """, (limit, offset))
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


def get_circuit_breaker_state() -> Dict[str, Any]:
    """Get current circuit breaker state for monitoring."""
    return _circuit_breaker.get_state()


REPLAY_PACKET_MAX_SIZE = 1_000_000


def get_replay_packet(run_id: str) -> Optional[Dict[str, Any]]:
    """
    Generate a replay packet for a query run.
    Contains only IDs, manifests, and metadata - NO raw text or secrets.
    Enforces size limit to prevent oversized responses.
    """
    run = get_query_run(run_id)
    if not run:
        return None
    
    packet = {
        "run_id": run.get("id"),
        "created_at": run.get("created_at").isoformat() if run.get("created_at") else None,
        "conversation_id": run.get("conversation_id"),
        "user_query": run.get("user_query"),
        "doctrine_tag": run.get("doctrine_tag"),
        "corpus_version_id": run.get("corpus_version_id"),
        "retrieval_manifest": run.get("retrieval_manifest"),
        "context_manifest": run.get("context_manifest"),
        "model_config": run.get("model_config"),
        "system_prompt_version": run.get("system_prompt_version"),
        "final_answer": run.get("final_answer"),
        "citations_manifest": run.get("citation_verifications"),
        "latency_ms": run.get("latency_ms"),
        "failure_reason": run.get("failure_reason")
    }
    
    packet_json = json.dumps(packet, default=str)
    packet_size = len(packet_json.encode('utf-8'))
    
    if packet_size > REPLAY_PACKET_MAX_SIZE:
        logger.warning(f"Replay packet for {run_id} exceeds size limit ({packet_size} bytes)")
        packet["final_answer"] = "[TRUNCATED - exceeds size limit]"
        if packet.get("retrieval_manifest"):
            page_count = len(packet["retrieval_manifest"].get("page_ids", []))
            packet["retrieval_manifest"] = {"truncated": True, "original_page_count": page_count}
        if packet.get("context_manifest"):
            page_count = len(packet["context_manifest"].get("page_ids", []))
            packet["context_manifest"] = {"truncated": True, "original_page_count": page_count}
        packet["_size_limited"] = True
    
    return packet


def cleanup_query_runs(dry_run: bool = True) -> Dict[str, Any]:
    """
    Apply retention policy to query_runs:
    - Redact final_answer after RETENTION_REDACT_DAYS (90 days)
    - Delete rows after RETENTION_DELETE_DAYS (365 days)
    
    Args:
        dry_run: If True, only report counts without making changes
    
    Returns:
        Summary of actions taken or would be taken
    """
    now = datetime.utcnow()
    redact_cutoff = now - timedelta(days=RETENTION_REDACT_DAYS)
    delete_cutoff = now - timedelta(days=RETENTION_DELETE_DAYS)
    
    result = {
        "dry_run": dry_run,
        "redact_cutoff": redact_cutoff.isoformat(),
        "delete_cutoff": delete_cutoff.isoformat(),
        "to_redact": 0,
        "to_delete": 0,
        "redacted": 0,
        "deleted": 0,
        "errors": []
    }
    
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT COUNT(*) as cnt FROM query_runs 
                WHERE created_at < %s AND created_at >= %s
                AND final_answer IS NOT NULL AND final_answer != '[REDACTED]'
            """, (redact_cutoff, delete_cutoff))
            row = cursor.fetchone()
            result["to_redact"] = row.get("cnt", 0) if row else 0
            
            cursor.execute("""
                SELECT COUNT(*) as cnt FROM query_runs 
                WHERE created_at < %s
            """, (delete_cutoff,))
            row = cursor.fetchone()
            result["to_delete"] = row.get("cnt", 0) if row else 0
            
            if not dry_run:
                cursor.execute("""
                    UPDATE query_runs 
                    SET final_answer = '[REDACTED]'
                    WHERE created_at < %s AND created_at >= %s
                    AND final_answer IS NOT NULL AND final_answer != '[REDACTED]'
                """, (redact_cutoff, delete_cutoff))
                result["redacted"] = cursor.rowcount
                
                cursor.execute("""
                    DELETE FROM query_runs 
                    WHERE created_at < %s
                """, (delete_cutoff,))
                result["deleted"] = cursor.rowcount
                
                conn.commit()
                logger.info(f"Cleanup completed: redacted={result['redacted']}, deleted={result['deleted']}")
            else:
                logger.info(f"Cleanup dry-run: would redact={result['to_redact']}, would delete={result['to_delete']}")
                
    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"Cleanup error: {e}")
    
    return result


def get_retention_stats() -> Dict[str, Any]:
    """Get statistics about query_runs retention status."""
    now = datetime.utcnow()
    redact_cutoff = now - timedelta(days=RETENTION_REDACT_DAYS)
    delete_cutoff = now - timedelta(days=RETENTION_DELETE_DAYS)
    
    stats = {
        "total_runs": 0,
        "active_runs": 0,
        "redactable_runs": 0,
        "deletable_runs": 0,
        "already_redacted": 0
    }
    
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) as cnt FROM query_runs")
            stats["total_runs"] = cursor.fetchone().get("cnt", 0)
            
            cursor.execute("SELECT COUNT(*) as cnt FROM query_runs WHERE created_at >= %s", (redact_cutoff,))
            stats["active_runs"] = cursor.fetchone().get("cnt", 0)
            
            cursor.execute("""
                SELECT COUNT(*) as cnt FROM query_runs 
                WHERE created_at < %s AND created_at >= %s
                AND final_answer IS NOT NULL AND final_answer != '[REDACTED]'
            """, (redact_cutoff, delete_cutoff))
            stats["redactable_runs"] = cursor.fetchone().get("cnt", 0)
            
            cursor.execute("SELECT COUNT(*) as cnt FROM query_runs WHERE created_at < %s", (delete_cutoff,))
            stats["deletable_runs"] = cursor.fetchone().get("cnt", 0)
            
            cursor.execute("SELECT COUNT(*) as cnt FROM query_runs WHERE final_answer = '[REDACTED]'")
            stats["already_redacted"] = cursor.fetchone().get("cnt", 0)
            
    except Exception as e:
        logger.error(f"Error getting retention stats: {e}")
    
    return stats
