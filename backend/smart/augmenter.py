"""
Phase 1 Augmenter

Orchestrates query decomposition and embeddings fallback to augment retrieval.
Called after baseline FTS retrieval when triggers fire.

This module is:
- Additive only (does not replace baseline retrieval)
- Fail-soft (silently skips on any error)
- Bounded (time budget and candidate limits)
"""

import logging
import time
from typing import List, Dict, Tuple, Optional, Any

from backend.smart import config as smart_config
from backend.smart.query_decompose import (
    should_decompose, 
    decompose_query, 
    get_decomposition_info,
    log_trigger_decision,
    detect_doctrine_signals
)
from backend.smart.embeddings import semantic_recall, check_embeddings_available

logger = logging.getLogger(__name__)


def should_augment(fts_results: List[Dict], query: str, query_id: str = None) -> Tuple[bool, List[str], Dict[str, Any]]:
    """
    Determine if Phase 1 augmentation should be triggered.
    
    Returns:
        (should_trigger, list of trigger reasons, decision_context)
    """
    reasons = []
    fts_count = len(fts_results)
    top_score = 0.0
    
    if fts_count < smart_config.MIN_FTS_RESULTS:
        reasons.append("thin_results")
    
    if fts_results:
        top_score = max(r.get("score", 0) or r.get("rank", 0) for r in fts_results)
        if top_score < smart_config.MIN_TOP_SCORE:
            reasons.append("low_score")
    else:
        reasons.append("no_results")
    
    multi_issue = False
    if smart_config.SMART_QUERY_DECOMPOSE_ENABLED:
        multi_issue = should_decompose(query)
        if multi_issue:
            reasons.append("multi_issue")
    
    decision_context = log_trigger_decision(
        query=query,
        query_id=query_id,
        fts_count=fts_count,
        top_score=top_score,
        min_fts_results=smart_config.MIN_FTS_RESULTS,
        min_top_score=smart_config.MIN_TOP_SCORE
    )
    decision_context["final_decision"] = len(reasons) > 0
    decision_context["trigger_reasons"] = reasons
    
    return len(reasons) > 0, reasons, decision_context


def augment_retrieval(
    query: str,
    baseline_results: List[Dict],
    search_func: callable = None
) -> Tuple[List[Dict], Dict[str, Any]]:
    """
    Augment baseline retrieval with Phase 1 candidates.
    
    Args:
        query: Original user query
        baseline_results: Results from baseline FTS retrieval
        search_func: Function to run additional FTS searches (for decomposition)
    
    Returns:
        (augmented_results, telemetry_data)
    """
    start_time = time.time()
    
    telemetry = {
        "phase1_enabled": smart_config.SMART_EMBED_RECALL_ENABLED or smart_config.SMART_QUERY_DECOMPOSE_ENABLED,
        "decompose_enabled": smart_config.SMART_QUERY_DECOMPOSE_ENABLED,
        "embed_enabled": smart_config.SMART_EMBED_RECALL_ENABLED,
        "triggered": False,
        "trigger_reasons": [],
        "subqueries_generated": 0,
        "embed_candidates_added": 0,
        "decompose_candidates_added": 0,
        "total_candidates_added": 0,
        "augmentation_latency_ms": 0,
        "skipped_reason": None
    }
    
    if not (smart_config.SMART_EMBED_RECALL_ENABLED or smart_config.SMART_QUERY_DECOMPOSE_ENABLED):
        logger.debug(f"Phase 1 skipped: both flags are OFF (decompose={smart_config.SMART_QUERY_DECOMPOSE_ENABLED}, embed={smart_config.SMART_EMBED_RECALL_ENABLED})")
        telemetry["skipped_reason"] = "flags_off"
        return baseline_results, telemetry
    
    should_trigger, reasons, decision_context = should_augment(baseline_results, query)
    telemetry["trigger_reasons"] = reasons
    telemetry["decision_context"] = decision_context
    
    if not should_trigger:
        logger.debug(
            f"Phase 1 triggers not met: {decision_context}"
        )
        telemetry["skipped_reason"] = "triggers_not_met"
        return baseline_results, telemetry
    
    telemetry["triggered"] = True
    
    try:
        baseline_ids = {r.get("id") for r in baseline_results if r.get("id")}
        augmented = list(baseline_results)
        candidates_added = 0
        
        if smart_config.SMART_QUERY_DECOMPOSE_ENABLED and "multi_issue" in reasons and search_func:
            elapsed_ms = (time.time() - start_time) * 1000
            remaining_budget = smart_config.PHASE1_BUDGET_MS - elapsed_ms
            
            if remaining_budget > 100:
                subqueries = decompose_query(query)
                telemetry["subqueries_generated"] = len(subqueries)
                
                for subquery in subqueries:
                    if candidates_added >= smart_config.MAX_AUGMENT_CANDIDATES:
                        break
                    
                    elapsed_ms = (time.time() - start_time) * 1000
                    if elapsed_ms > smart_config.PHASE1_BUDGET_MS * 0.6:
                        break
                    
                    try:
                        sub_results = search_func(subquery, limit=10)
                        for r in sub_results:
                            if r.get("id") not in baseline_ids and candidates_added < smart_config.MAX_AUGMENT_CANDIDATES:
                                r["source"] = "decomposition"
                                augmented.append(r)
                                baseline_ids.add(r.get("id"))
                                candidates_added += 1
                                telemetry["decompose_candidates_added"] += 1
                    except Exception as e:
                        logger.debug(f"Subquery search failed: {e}")
        
        if smart_config.SMART_EMBED_RECALL_ENABLED and candidates_added < smart_config.MAX_AUGMENT_CANDIDATES:
            elapsed_ms = (time.time() - start_time) * 1000
            remaining_budget = smart_config.PHASE1_BUDGET_MS - elapsed_ms
            
            if remaining_budget > 100:
                try:
                    remaining_slots = smart_config.MAX_AUGMENT_CANDIDATES - candidates_added
                    embed_k = min(smart_config.MAX_EMBED_CANDIDATES, remaining_slots)
                    
                    embed_results = semantic_recall(
                        query, 
                        k=embed_k,
                        exclude_ids=list(baseline_ids)
                    )
                    
                    for r in embed_results:
                        if candidates_added < smart_config.MAX_AUGMENT_CANDIDATES:
                            augmented.append(r)
                            candidates_added += 1
                            telemetry["embed_candidates_added"] += 1
                            
                except Exception as e:
                    logger.debug(f"Embedding recall failed: {e}")
        
        telemetry["total_candidates_added"] = candidates_added
        telemetry["augmentation_latency_ms"] = int((time.time() - start_time) * 1000)
        
        logger.info(f"Phase 1 augmentation: +{candidates_added} candidates in {telemetry['augmentation_latency_ms']}ms (reasons: {reasons})")
        
        return augmented, telemetry
        
    except Exception as e:
        logger.warning(f"Phase 1 augmentation failed: {e}")
        telemetry["skipped_reason"] = f"error: {str(e)[:100]}"
        telemetry["augmentation_latency_ms"] = int((time.time() - start_time) * 1000)
        return baseline_results, telemetry


def get_phase1_status() -> Dict[str, Any]:
    """Get status of Phase 1 features for diagnostics."""
    embed_status = check_embeddings_available() if smart_config.SMART_EMBED_RECALL_ENABLED else {"available": False, "reason": "disabled"}
    
    return {
        "decompose_enabled": smart_config.SMART_QUERY_DECOMPOSE_ENABLED,
        "embed_enabled": smart_config.SMART_EMBED_RECALL_ENABLED,
        "budget_ms": smart_config.PHASE1_BUDGET_MS,
        "max_candidates": smart_config.MAX_AUGMENT_CANDIDATES,
        "min_fts_results": smart_config.MIN_FTS_RESULTS,
        "min_top_score": smart_config.MIN_TOP_SCORE,
        "embeddings": embed_status
    }
