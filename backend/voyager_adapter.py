"""
Voyager Adapter Module

Maps internal query_runs into Voyager's expected event/audit schema.
This adapter is purely additive: it consumes internal logs and exports
(or prepares) Voyager-compatible payloads.

Export is controlled by VOYAGER_EXPORT_ENABLED environment variable (default: false).
When enabled, exports are asynchronous and never block user responses.
"""

import os
import json
import logging
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

VOYAGER_EXPORT_ENABLED = os.environ.get("VOYAGER_EXPORT_ENABLED", "false").lower() == "true"
VOYAGER_ENDPOINT = os.environ.get("VOYAGER_ENDPOINT", "")


@dataclass
class VoyagerEvent:
    """Voyager-compatible audit event schema."""
    event_id: str
    event_type: str
    timestamp: str
    source_system: str
    corpus_version: str
    session_id: Optional[str]
    query: str
    response: str
    retrieval: Dict[str, Any]
    generation: Dict[str, Any]
    verification: Dict[str, Any]
    latency_ms: int
    status: str


def map_query_run_to_voyager_event(query_run: Dict[str, Any]) -> VoyagerEvent:
    """
    Map internal query_run record to Voyager event schema.
    
    This isolates any Voyager schema-specific mapping so it can be updated
    without touching the core pipeline.
    """
    retrieval_manifest = query_run.get("retrieval_manifest") or {}
    if isinstance(retrieval_manifest, str):
        retrieval_manifest = json.loads(retrieval_manifest)
    
    context_manifest = query_run.get("context_manifest") or {}
    if isinstance(context_manifest, str):
        context_manifest = json.loads(context_manifest)
    
    model_config = query_run.get("model_config") or {}
    if isinstance(model_config, str):
        model_config = json.loads(model_config)
    
    citation_verifications = query_run.get("citation_verifications") or []
    if isinstance(citation_verifications, str):
        citation_verifications = json.loads(citation_verifications)
    
    verified_count = sum(1 for v in citation_verifications if v.get("verified"))
    total_citations = len(citation_verifications)
    
    confidence_tiers = {}
    for v in citation_verifications:
        tier = v.get("confidence_tier", "UNVERIFIED")
        confidence_tiers[tier] = confidence_tiers.get(tier, 0) + 1
    
    created_at = query_run.get("created_at")
    if isinstance(created_at, datetime):
        timestamp = created_at.isoformat() + "Z"
    else:
        timestamp = str(created_at) if created_at else datetime.utcnow().isoformat() + "Z"
    
    status = "success" if not query_run.get("failure_reason") else "failed"
    
    return VoyagerEvent(
        event_id=query_run.get("id", ""),
        event_type="legal_research_query",
        timestamp=timestamp,
        source_system="cafc_opinion_assistant",
        corpus_version=query_run.get("corpus_version_id", ""),
        session_id=query_run.get("conversation_id"),
        query=query_run.get("user_query", ""),
        response=query_run.get("final_answer", "")[:5000],
        retrieval={
            "page_count": retrieval_manifest.get("count", 0),
            "page_ids": retrieval_manifest.get("page_ids", [])[:20],
            "opinion_ids": retrieval_manifest.get("opinion_ids", []),
            "top_scores": retrieval_manifest.get("scores", [])[:5]
        },
        generation={
            "model": model_config.get("model", "unknown"),
            "temperature": model_config.get("temperature", 0.1),
            "max_tokens": model_config.get("max_tokens", 0),
            "prompt_version": query_run.get("system_prompt_version", ""),
            "context_tokens": context_manifest.get("total_tokens", 0),
            "context_pages": context_manifest.get("page_count", 0)
        },
        verification={
            "total_citations": total_citations,
            "verified_citations": verified_count,
            "verification_rate": verified_count / total_citations if total_citations > 0 else 1.0,
            "confidence_distribution": confidence_tiers,
            "doctrine_tag": query_run.get("doctrine_tag")
        },
        latency_ms=query_run.get("latency_ms", 0) or 0,
        status=status
    )


def export_to_voyager_async(query_run: Dict[str, Any]) -> None:
    """
    Export query run to Voyager asynchronously.
    Never blocks user response. Failures are logged but not raised.
    """
    if not VOYAGER_EXPORT_ENABLED:
        return
    
    def _export():
        try:
            event = map_query_run_to_voyager_event(query_run)
            payload = asdict(event)
            
            if VOYAGER_ENDPOINT:
                import httpx
                try:
                    with httpx.Client(timeout=10.0) as client:
                        response = client.post(
                            VOYAGER_ENDPOINT,
                            json=payload,
                            headers={"Content-Type": "application/json"}
                        )
                        if response.status_code >= 400:
                            logger.warning(f"Voyager export failed: {response.status_code}")
                        else:
                            logger.debug(f"Voyager export success: {event.event_id}")
                except Exception as e:
                    logger.warning(f"Voyager export HTTP error: {e}")
            else:
                logger.debug(f"Voyager export prepared (no endpoint): {event.event_id}")
                
        except Exception as e:
            logger.error(f"Voyager export error: {e}")
    
    thread = threading.Thread(target=_export, daemon=True)
    thread.start()


def prepare_voyager_payload(query_run: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepare Voyager payload without sending.
    Useful for testing and validation.
    """
    event = map_query_run_to_voyager_event(query_run)
    return asdict(event)


def get_voyager_config() -> Dict[str, Any]:
    """Get current Voyager adapter configuration."""
    return {
        "export_enabled": VOYAGER_EXPORT_ENABLED,
        "endpoint_configured": bool(VOYAGER_ENDPOINT),
        "source_system": "cafc_opinion_assistant",
        "event_type": "legal_research_query"
    }
