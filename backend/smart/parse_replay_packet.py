"""
Replay Packet Parser for Phase 1 Evaluation

Normalizes fields from query_runs/replay-packet for consistent metric extraction.
This is a TEST-ONLY helper - does not affect production behavior.
"""

import os
import logging
from typing import Dict, List, Any, Optional
import httpx

logger = logging.getLogger(__name__)

VERIFICATION_TIERS = ["STRONG", "MODERATE", "WEAK", "UNVERIFIED"]
VERIFIED_TIERS = ["STRONG", "MODERATE", "WEAK"]


def is_verified_tier(tier: str) -> bool:
    """Check if a citation tier counts as verified (not UNVERIFIED)."""
    return tier.upper() in VERIFIED_TIERS


def parse_citations_manifest(citations_manifest: Optional[List[Dict]]) -> Dict[str, Any]:
    """
    Parse citations manifest to extract verification counts.
    
    Returns:
        Dict with verified_citations, unverified_citations, tier_counts, citations_detail
    """
    if not citations_manifest:
        return {
            "verified_citations": 0,
            "unverified_citations": 0,
            "tier_counts": {t: 0 for t in VERIFICATION_TIERS},
            "citations_detail": [],
            "status": "no_manifest"
        }
    
    tier_counts = {t: 0 for t in VERIFICATION_TIERS}
    citations_detail = []
    
    for cite in citations_manifest:
        tier = cite.get("tier", cite.get("confidence_tier", "UNVERIFIED")).upper()
        if tier not in VERIFICATION_TIERS:
            tier = "UNVERIFIED"
        
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        
        citations_detail.append({
            "page_id": cite.get("page_id"),
            "opinion_id": cite.get("opinion_id"),
            "tier": tier,
            "match_type": cite.get("match_type", "unknown"),
            "binding_tags": cite.get("binding_tags", []),
            "score": cite.get("score", cite.get("confidence_score"))
        })
    
    verified = sum(tier_counts.get(t, 0) for t in VERIFIED_TIERS)
    unverified = tier_counts.get("UNVERIFIED", 0)
    
    return {
        "verified_citations": verified,
        "unverified_citations": unverified,
        "tier_counts": tier_counts,
        "citations_detail": citations_detail,
        "status": "parsed"
    }


def parse_retrieval_manifest(retrieval_manifest: Optional[Dict]) -> Dict[str, Any]:
    """
    Parse retrieval manifest to extract page IDs and detect SCOTUS/en banc.
    
    Returns:
        Dict with page_ids, opinion_ids, scotus_present, en_banc_present
    """
    if not retrieval_manifest:
        return {
            "page_ids": [],
            "opinion_ids": [],
            "page_count": 0,
            "scotus_present": "unknown",
            "en_banc_present": "unknown",
            "status": "no_manifest"
        }
    
    if retrieval_manifest.get("truncated"):
        return {
            "page_ids": [],
            "opinion_ids": [],
            "page_count": retrieval_manifest.get("original_page_count", 0),
            "scotus_present": "unknown",
            "en_banc_present": "unknown",
            "status": "truncated"
        }
    
    page_ids = retrieval_manifest.get("page_ids", [])
    opinion_ids = list(set(retrieval_manifest.get("opinion_ids", [])))
    
    origins = retrieval_manifest.get("origins", [])
    case_names = retrieval_manifest.get("case_names", [])
    
    scotus_present = False
    en_banc_present = False
    
    for origin in origins:
        if origin and "SCOTUS" in str(origin).upper():
            scotus_present = True
    
    for name in case_names:
        name_lower = str(name).lower()
        if "supreme" in name_lower or "u.s." in name_lower:
            scotus_present = True
        if "en banc" in name_lower:
            en_banc_present = True
    
    return {
        "page_ids": page_ids,
        "opinion_ids": opinion_ids,
        "page_count": len(page_ids),
        "scotus_present": scotus_present,
        "en_banc_present": en_banc_present,
        "status": "parsed"
    }


def parse_model_config(model_config: Optional[Dict]) -> Dict[str, Any]:
    """
    Parse model_config to extract Phase 1 telemetry.
    
    Returns:
        Dict with augmentation_used, triggers, candidates_added
    """
    if not model_config:
        return {
            "augmentation_used": {"decompose": False, "embeddings": False},
            "triggers": [],
            "candidates_added": 0,
            "latency_ms": 0,
            "triggered": False,
            "status": "no_config"
        }
    
    phase1 = model_config.get("phase1", {})
    
    return {
        "augmentation_used": {
            "decompose": phase1.get("decompose_enabled", False),
            "embeddings": phase1.get("embed_enabled", False)
        },
        "triggers": phase1.get("trigger_reasons", []),
        "candidates_added": phase1.get("total_candidates_added", 0),
        "latency_ms": phase1.get("augmentation_latency_ms", 0),
        "triggered": phase1.get("triggered", False),
        "status": "parsed" if phase1 else "no_phase1"
    }


def normalize_replay_packet(packet: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a replay packet into evaluation-ready format.
    
    Args:
        packet: Raw replay packet from API or query_runs
        
    Returns:
        Normalized dict with all required evaluation fields
    """
    run_id = packet.get("run_id", packet.get("id", "unknown"))
    
    final_answer = packet.get("final_answer", "")
    if final_answer == "[TRUNCATED - exceeds size limit]":
        answer_length = -1
        answer_status = "truncated"
    elif final_answer == "[REDACTED]":
        answer_length = -1
        answer_status = "redacted"
    elif final_answer:
        answer_length = len(final_answer)
        answer_status = "present"
    else:
        answer_length = 0
        answer_status = "empty"
    
    not_found = False
    if answer_status == "present":
        answer_lower = final_answer.lower()
        not_found = "not found" in answer_lower or answer_lower.startswith("not found")
    
    citations = parse_citations_manifest(packet.get("citations_manifest"))
    retrieval = parse_retrieval_manifest(packet.get("retrieval_manifest"))
    phase1 = parse_model_config(packet.get("model_config"))
    
    return {
        "run_id": run_id,
        "conversation_id": packet.get("conversation_id"),
        "user_query": packet.get("user_query"),
        "generated_at": packet.get("created_at"),
        "doctrine_tag": packet.get("doctrine_tag"),
        "corpus_version_id": packet.get("corpus_version_id"),
        
        "final_answer_text": final_answer if answer_status == "present" else None,
        "answer_length": answer_length,
        "answer_status": answer_status,
        "not_found": not_found,
        
        "verified_citations": citations["verified_citations"],
        "unverified_citations": citations["unverified_citations"],
        "tier_counts": citations["tier_counts"],
        "citations_detail": citations["citations_detail"],
        "total_sources": citations["verified_citations"] + citations["unverified_citations"],
        
        "retrieval_manifest_snapshot": retrieval["page_ids"],
        "retrieved_page_count": retrieval["page_count"],
        "scotus_present": retrieval["scotus_present"],
        "en_banc_present": retrieval["en_banc_present"],
        
        "augmentation_used": phase1["augmentation_used"],
        "triggers": phase1["triggers"],
        "candidates_added": phase1["candidates_added"],
        "phase1_triggered": phase1.get("triggered", False),
        "phase1_latency_ms": phase1["latency_ms"],
        
        "latency_ms": packet.get("latency_ms", 0),
        "failure_reason": packet.get("failure_reason"),
        
        "_size_limited": packet.get("_size_limited", False),
        "_parse_status": {
            "citations": citations["status"],
            "retrieval": retrieval["status"],
            "phase1": phase1["status"],
            "answer": answer_status
        }
    }


async def fetch_replay_packet(run_id: str, base_url: str = "http://localhost:8000") -> Optional[Dict[str, Any]]:
    """
    Fetch replay packet from API endpoint.
    
    Args:
        run_id: The query run ID
        base_url: API base URL
        
    Returns:
        Normalized replay packet or None if not found
    """
    api_key = os.environ.get("EXTERNAL_API_KEY")
    if not api_key:
        logger.warning("EXTERNAL_API_KEY not set, cannot fetch replay packet")
        return None
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{base_url}/api/voyager/replay-packet/{run_id}",
                headers={"X-API-Key": api_key},
                timeout=10.0
            )
            
            if response.status_code == 200:
                packet = response.json()
                return normalize_replay_packet(packet)
            elif response.status_code == 404:
                logger.debug(f"Replay packet not found for run_id={run_id}")
                return None
            else:
                logger.warning(f"Failed to fetch replay packet: HTTP {response.status_code}")
                return None
                
    except Exception as e:
        logger.error(f"Error fetching replay packet: {e}")
        return None


def extract_metrics_from_response(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract evaluation metrics directly from chat response.
    
    This is a fallback when replay packet is not available.
    """
    answer = response.get("answer", response.get("answer_markdown", ""))
    sources = response.get("sources", [])
    debug = response.get("debug", {})
    
    verified = 0
    unverified = 0
    tier_counts = {t: 0 for t in VERIFICATION_TIERS}
    
    for src in sources:
        tier = src.get("confidenceTier", src.get("confidence_tier", "UNVERIFIED"))
        tier = tier.upper() if tier else "UNVERIFIED"
        if tier not in VERIFICATION_TIERS:
            tier = "UNVERIFIED"
        
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        if is_verified_tier(tier):
            verified += 1
        else:
            unverified += 1
    
    scotus_present = False
    en_banc_present = False
    for src in sources:
        case_name = str(src.get("caseName", src.get("case_name", ""))).lower()
        origin = str(src.get("origin", "")).upper()
        if "supreme" in case_name or "u.s." in case_name or origin == "SCOTUS":
            scotus_present = True
        if "en banc" in case_name:
            en_banc_present = True
    
    not_found = "not found" in answer.lower() if answer else True
    
    return {
        "final_answer_text": answer,
        "answer_length": len(answer) if answer else 0,
        "not_found": not_found,
        "verified_citations": verified,
        "unverified_citations": unverified,
        "tier_counts": tier_counts,
        "total_sources": len(sources),
        "scotus_present": scotus_present,
        "en_banc_present": en_banc_present,
        "sources_raw": sources
    }
