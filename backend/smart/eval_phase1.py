"""
Phase 1 Eval Harness (Hardened)

Evaluates Phase 1 Smartness improvements by comparing baseline (flags OFF)
vs augmented (flags ON) performance on a curated set of queries.

Produces trustworthy metrics by parsing query_runs/replay-packet data.

Usage:
    python -m backend.smart.eval_phase1 --baseline
    python -m backend.smart.eval_phase1 --phase1
    python -m backend.smart.eval_phase1 --compare
    python -m backend.smart.eval_phase1 --compare --queries 5

Output: JSON report with metrics comparison
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from backend.smart.parse_replay_packet import (
    extract_metrics_from_response,
    fetch_replay_packet,
    normalize_replay_packet,
    is_verified_tier
)


def load_eval_queries(query_file: str = None) -> List[Dict]:
    """Load evaluation queries from JSON file."""
    if query_file:
        queries_path = Path(query_file)
    else:
        queries_path = Path(__file__).parent / "eval_queries.json"
    
    if queries_path.exists():
        with open(queries_path) as f:
            data = json.load(f)
            return data.get("queries", [])
    else:
        logger.warning(f"Query file not found at {queries_path}, using fallback")
        return FALLBACK_QUERIES


FALLBACK_QUERIES = [
    {
        "id": "alice_101_basic",
        "query": "What is the Alice two-step test for patent eligibility under 35 USC 101?",
        "expected_doctrines": ["101"],
        "category": "alice_101"
    },
    {
        "id": "ksr_motivation",
        "query": "After KSR, what motivation is required to combine prior art references?",
        "expected_doctrines": ["103"],
        "category": "obviousness"
    },
    {
        "id": "multi_issue_101_112",
        "query": "What are the requirements for patent eligibility under Alice and written description under 112?",
        "expected_doctrines": ["101", "112"],
        "category": "multi_issue"
    }
]


def set_phase1_flags(enabled: bool, decompose_only: bool = True):
    """
    Set Phase 1 feature flags and reload modules to ensure they take effect.
    
    Args:
        enabled: Whether to enable Phase 1 features
        decompose_only: If True, only enable decomposition (not embeddings) since embeddings require build step
    """
    decompose_value = "true" if enabled else "false"
    embed_value = "true" if enabled and not decompose_only else "false"
    
    os.environ["SMART_QUERY_DECOMPOSE_ENABLED"] = decompose_value
    os.environ["SMART_EMBED_RECALL_ENABLED"] = embed_value
    
    from importlib import reload
    import backend.smart.config
    reload(backend.smart.config)
    
    import backend.smart.augmenter
    reload(backend.smart.augmenter)
    
    import backend.smart.query_decompose
    reload(backend.smart.query_decompose)
    
    from backend.smart import config as smart_config
    logger.info(f"Phase 1 flags set to: decompose={smart_config.SMART_QUERY_DECOMPOSE_ENABLED}, embed={smart_config.SMART_EMBED_RECALL_ENABLED}")
    
    return smart_config.SMART_QUERY_DECOMPOSE_ENABLED, smart_config.SMART_EMBED_RECALL_ENABLED


def verify_phase1_flags_enabled() -> bool:
    """Verify that at least one Phase 1 flag is enabled. Returns True if OK."""
    from backend.smart import config as smart_config
    return smart_config.SMART_QUERY_DECOMPOSE_ENABLED or smart_config.SMART_EMBED_RECALL_ENABLED


async def run_single_query(query_info: Dict) -> Dict[str, Any]:
    """
    Run a single query and collect comprehensive metrics.
    
    Uses both direct response parsing AND query_runs/replay-packet for reliable data.
    """
    from backend.chat import generate_chat_response
    
    query = query_info["query"]
    query_id = query_info["id"]
    run_uuid = str(uuid.uuid4())[:8]
    conversation_id = f"eval_{query_id}_{int(time.time())}_{run_uuid}"
    
    start_time = time.time()
    
    try:
        result = await generate_chat_response(
            message=query,
            conversation_id=conversation_id
        )
        
        latency_ms = int((time.time() - start_time) * 1000)
        
        response_metrics = extract_metrics_from_response(result)
        
        await asyncio.sleep(0.3)
        
        debug = result.get("debug", {})
        run_id = debug.get("run_id")
        
        replay_data = None
        if run_id:
            try:
                replay_data = await fetch_replay_packet(run_id)
            except Exception as e:
                logger.debug(f"Could not fetch replay packet: {e}")
        
        verified_citations = response_metrics["verified_citations"]
        unverified_citations = response_metrics["unverified_citations"]
        tier_counts = response_metrics.get("tier_counts", {})
        scotus_present = response_metrics["scotus_present"]
        en_banc_present = response_metrics.get("en_banc_present", False)
        
        if replay_data:
            if replay_data.get("verified_citations", 0) > 0 or replay_data.get("unverified_citations", 0) > 0:
                verified_citations = replay_data["verified_citations"]
                unverified_citations = replay_data["unverified_citations"]
                tier_counts = replay_data.get("tier_counts", tier_counts)
            
            if replay_data.get("scotus_present") not in [None, "unknown"]:
                scotus_present = replay_data["scotus_present"]
            if replay_data.get("en_banc_present") not in [None, "unknown"]:
                en_banc_present = replay_data["en_banc_present"]
        
        phase1_telemetry = (debug or {}).get("phase1_telemetry") or {}
        augmentation_used = {
            "decompose": phase1_telemetry.get("decompose_enabled", False),
            "embeddings": phase1_telemetry.get("embed_enabled", False)
        }
        triggers = phase1_telemetry.get("trigger_reasons", [])
        candidates_added = phase1_telemetry.get("total_candidates_added", 0)
        phase1_triggered = phase1_telemetry.get("triggered", False)
        phase1_latency = phase1_telemetry.get("augmentation_latency_ms", 0)
        
        decision_context = phase1_telemetry.get("decision_context") or {}
        subqueries_list = phase1_telemetry.get("subqueries_list", [])
        candidates_added_list = phase1_telemetry.get("candidates_added_list", [])
        
        answer_text = response_metrics.get("final_answer_text", "")
        answer_length = response_metrics.get("answer_length", 0)
        not_found = response_metrics.get("not_found", False)
        
        if answer_length == 0 and not not_found:
            logger.warning(f"Query {query_id}: answer_length=0 but not_found=False - flagging as suspect")
        
        retrieval_snapshot = replay_data.get("retrieval_manifest_snapshot", []) if replay_data else []
        retrieval_delta = {
            "total_sources": len(retrieval_snapshot),
            "top_5_source_ids": [s.get("page_id") or s.get("id") for s in retrieval_snapshot[:5]],
            "top_5_source_titles": [s.get("case_name", s.get("title", ""))[:60] for s in retrieval_snapshot[:5]],
        }
        
        return {
            "run_id": run_id or f"local_{conversation_id}",
            "query_id": query_id,
            "query": query,
            "conversation_id": conversation_id,
            "success": True,
            "generated_at": datetime.utcnow().isoformat(),
            
            "final_answer_text": answer_text[:500] if answer_text else None,
            "answer_length": answer_length,
            "not_found": not_found,
            
            "verified_citations": verified_citations,
            "unverified_citations": unverified_citations,
            "tier_counts": tier_counts,
            "total_sources": verified_citations + unverified_citations,
            
            "scotus_present": scotus_present,
            "en_banc_present": en_banc_present,
            
            "latency_ms": latency_ms,
            
            "augmentation_used": augmentation_used,
            "triggers": triggers,
            "candidates_added": candidates_added,
            "phase1_triggered": phase1_triggered,
            "phase1_latency_ms": phase1_latency,
            
            "debug": debug or {},
            "decision_context": decision_context,
            "subqueries_list": subqueries_list,
            "candidates_added_list": candidates_added_list,
            "retrieval_delta": retrieval_delta,
            
            "retrieval_manifest_snapshot": retrieval_snapshot,
            
            "_replay_packet_available": replay_data is not None,
            "_suspect": answer_length == 0 and not not_found
        }
        
    except Exception as e:
        logger.error(f"Query {query_id} failed: {e}")
        return {
            "run_id": f"error_{conversation_id}",
            "query_id": query_id,
            "query": query,
            "conversation_id": conversation_id,
            "success": False,
            "error": str(e),
            "latency_ms": int((time.time() - start_time) * 1000),
            "generated_at": datetime.utcnow().isoformat(),
            
            "verified_citations": "unknown",
            "unverified_citations": "unknown",
            "not_found": "unknown",
            "scotus_present": "unknown",
            "en_banc_present": "unknown",
            "answer_length": 0,
            
            "phase1_triggered": False,
            "candidates_added": 0,
            "triggers": [],
            "phase1_latency_ms": 0
        }


async def run_eval_batch(queries: List[Dict], phase1_enabled: bool) -> Dict[str, Any]:
    """Run evaluation batch with specified flag state."""
    decompose_on, embed_on = set_phase1_flags(phase1_enabled)
    
    mode = "phase1" if phase1_enabled else "baseline"
    logger.info(f"[FLAGS] Enabled for {mode.upper()} eval run: decompose={decompose_on}, embed={embed_on}")
    
    if phase1_enabled and not verify_phase1_flags_enabled():
        logger.error(f"FATAL: Phase 1 mode requested but flags are OFF! decompose={decompose_on}, embed={embed_on}")
        raise RuntimeError("Phase 1 evaluation requested but SMART_QUERY_DECOMPOSE_ENABLED is not true. "
                          "Set environment variable or check flag configuration.")
    
    logger.info(f"Running {len(queries)} queries in {mode} mode (decompose={decompose_on}, embed={embed_on})...")
    
    results = []
    for i, query in enumerate(queries):
        logger.info(f"[{i+1}/{len(queries)}] Running: {query['id']}")
        result = await run_single_query(query)
        results.append(result)
        await asyncio.sleep(0.5)
    
    successful = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    suspect = [r for r in successful if r.get("_suspect")]
    
    def safe_avg(key: str) -> float:
        """Average only numeric values present (excludes missing/unknown)."""
        vals = [r.get(key, 0) for r in successful if isinstance(r.get(key), (int, float))]
        return sum(vals) / len(vals) if vals else 0
    
    def safe_avg_with_default(key: str, default: float = 0) -> float:
        """Average treating missing values as default (0). Used for Phase 1 telemetry."""
        vals = []
        for r in successful:
            v = r.get(key)
            if isinstance(v, (int, float)):
                vals.append(v)
            else:
                vals.append(default)
        return sum(vals) / len(vals) if vals else 0
    
    def safe_rate(key: str, value: bool) -> float:
        vals = [r for r in successful if r.get(key) == value]
        return len(vals) / len(successful) if successful else 0
    
    summary = {
        "mode": mode,
        "timestamp": datetime.utcnow().isoformat(),
        "total_queries": len(queries),
        "successful": len(successful),
        "failed": len(failed),
        "suspect": len(suspect),
        
        "avg_latency_ms": safe_avg("latency_ms"),
        "not_found_rate": safe_rate("not_found", True),
        "avg_verified_citations": safe_avg("verified_citations"),
        "avg_unverified_citations": safe_avg("unverified_citations"),
        "scotus_coverage": safe_rate("scotus_present", True),
        "en_banc_coverage": safe_rate("en_banc_present", True),
        
        "phase1_trigger_rate": safe_rate("phase1_triggered", True),
        "avg_candidates_added": safe_avg_with_default("candidates_added", 0),
        "avg_phase1_latency_ms": safe_avg_with_default("phase1_latency_ms", 0),
        
        "avg_answer_length": safe_avg("answer_length"),
        
        "results": results
    }
    
    return summary


def compare_results(baseline: Dict, phase1: Dict) -> Dict[str, Any]:
    """Compare baseline vs phase1 results with detailed deltas."""
    
    def delta(key: str):
        b = baseline.get(key, 0)
        p = phase1.get(key, 0)
        if isinstance(b, str) or isinstance(p, str):
            return "unknown"
        return p - b
    
    comparison = {
        "baseline": {
            "total_queries": baseline["total_queries"],
            "successful": baseline["successful"],
            "avg_latency_ms": baseline["avg_latency_ms"],
            "not_found_rate": baseline["not_found_rate"],
            "avg_verified_citations": baseline["avg_verified_citations"],
            "scotus_coverage": baseline["scotus_coverage"]
        },
        "phase1": {
            "total_queries": phase1["total_queries"],
            "successful": phase1["successful"],
            "avg_latency_ms": phase1["avg_latency_ms"],
            "not_found_rate": phase1["not_found_rate"],
            "avg_verified_citations": phase1["avg_verified_citations"],
            "scotus_coverage": phase1["scotus_coverage"],
            "phase1_trigger_rate": phase1.get("phase1_trigger_rate", 0),
            "avg_candidates_added": phase1.get("avg_candidates_added", 0)
        },
        "deltas": {
            "latency_delta_ms": delta("avg_latency_ms"),
            "not_found_delta": delta("not_found_rate"),
            "verified_citations_delta": delta("avg_verified_citations"),
            "scotus_coverage_delta": delta("scotus_coverage")
        },
        "improvements": {
            "reduced_not_found": phase1["not_found_rate"] < baseline["not_found_rate"],
            "more_verified_citations": phase1["avg_verified_citations"] > baseline["avg_verified_citations"],
            "better_scotus_coverage": phase1["scotus_coverage"] >= baseline["scotus_coverage"]
        }
    }
    
    return comparison


def generate_summary_text(results: Dict) -> str:
    """Generate human-readable summary text."""
    lines = [
        "=" * 60,
        "PHASE 1 EVALUATION SUMMARY",
        "=" * 60,
        f"Generated: {results.get('timestamp', datetime.utcnow().isoformat())}",
        f"Queries evaluated: {results.get('queries', 'unknown')}",
        ""
    ]
    
    if "baseline" in results:
        b = results["baseline"]
        lines.extend([
            "BASELINE (Phase 1 OFF):",
            f"  Latency: {b.get('avg_latency_ms', 0):.0f}ms",
            f"  NOT FOUND rate: {b.get('not_found_rate', 0):.1%}",
            f"  Verified citations: {b.get('avg_verified_citations', 0):.1f}",
            f"  SCOTUS coverage: {b.get('scotus_coverage', 0):.1%}",
            ""
        ])
    
    if "phase1" in results:
        p = results["phase1"]
        lines.extend([
            "PHASE 1 (Augmented):",
            f"  Latency: {p.get('avg_latency_ms', 0):.0f}ms",
            f"  NOT FOUND rate: {p.get('not_found_rate', 0):.1%}",
            f"  Verified citations: {p.get('avg_verified_citations', 0):.1f}",
            f"  SCOTUS coverage: {p.get('scotus_coverage', 0):.1%}",
            f"  Trigger rate: {p.get('phase1_trigger_rate', 0):.1%}",
            f"  Avg candidates added: {p.get('avg_candidates_added', 0):.1f}",
            ""
        ])
    
    if "comparison" in results:
        d = results["comparison"].get("deltas", {})
        lines.extend([
            "DELTAS (Phase 1 - Baseline):",
            f"  Latency: {d.get('latency_delta_ms', 0):+.0f}ms",
            f"  NOT FOUND: {d.get('not_found_delta', 0):+.1%}",
            f"  Verified citations: {d.get('verified_citations_delta', 0):+.1f}",
            f"  SCOTUS coverage: {d.get('scotus_coverage_delta', 0):+.1%}",
            ""
        ])
    
    lines.append("=" * 60)
    
    return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser(description="Phase 1 Evaluation Harness (Hardened)")
    parser.add_argument("--baseline", action="store_true", help="Run baseline evaluation (flags OFF)")
    parser.add_argument("--phase1", action="store_true", help="Run Phase 1 evaluation (flags ON)")
    parser.add_argument("--compare", action="store_true", help="Run both and compare")
    parser.add_argument("--output", default=None, help="Output file path (auto-generated if not specified)")
    parser.add_argument("--queries", type=int, default=None, help="Limit number of queries")
    parser.add_argument("--query_file", default=None, help="Path to queries JSON file (default: eval_queries.json)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    all_queries = load_eval_queries(args.query_file)
    queries = all_queries[:args.queries] if args.queries else all_queries
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    if not args.output:
        json_output = f"reports/phase1_eval_{timestamp}.json"
        txt_output = f"reports/phase1_eval_summary_{timestamp}.txt"
    else:
        json_output = args.output
        txt_output = args.output.replace(".json", "_summary.txt")
    
    os.makedirs("reports", exist_ok=True)
    
    print("\n" + "=" * 60)
    print("PHASE 1 EVALUATION HARNESS (HARDENED)")
    print("=" * 60)
    print(f"Queries: {len(queries)}")
    print(f"JSON output: {json_output}")
    print(f"Summary output: {txt_output}")
    print("")
    
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "queries": len(queries),
        "harness_version": "2.0"
    }
    
    if args.baseline or args.compare:
        print("Running BASELINE evaluation...")
        results["baseline"] = await run_eval_batch(queries, phase1_enabled=False)
        print(f"  Avg latency: {results['baseline']['avg_latency_ms']:.0f}ms")
        print(f"  NOT FOUND rate: {results['baseline']['not_found_rate']:.1%}")
        print(f"  Avg verified citations: {results['baseline']['avg_verified_citations']:.1f}")
        print(f"  SCOTUS coverage: {results['baseline']['scotus_coverage']:.1%}")
    
    if args.phase1 or args.compare:
        print("\nRunning PHASE 1 evaluation...")
        results["phase1"] = await run_eval_batch(queries, phase1_enabled=True)
        print(f"  Avg latency: {results['phase1']['avg_latency_ms']:.0f}ms")
        print(f"  NOT FOUND rate: {results['phase1']['not_found_rate']:.1%}")
        print(f"  Avg verified citations: {results['phase1']['avg_verified_citations']:.1f}")
        print(f"  SCOTUS coverage: {results['phase1']['scotus_coverage']:.1%}")
        print(f"  Trigger rate: {results['phase1']['phase1_trigger_rate']:.1%}")
    
    if args.compare and "baseline" in results and "phase1" in results:
        print("\nCOMPARISON:")
        comparison = compare_results(results["baseline"], results["phase1"])
        results["comparison"] = comparison
        
        print(f"  Latency delta: {comparison['deltas']['latency_delta_ms']:+.0f}ms")
        print(f"  NOT FOUND delta: {comparison['deltas']['not_found_delta']:+.1%}")
        print(f"  Verified citations delta: {comparison['deltas']['verified_citations_delta']:+.1f}")
        print(f"  SCOTUS coverage delta: {comparison['deltas']['scotus_coverage_delta']:+.1%}")
    
    with open(json_output, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    summary_text = generate_summary_text(results)
    with open(txt_output, "w") as f:
        f.write(summary_text)
    
    print(f"\nJSON results written to: {json_output}")
    print(f"Summary written to: {txt_output}")
    
    print("\n" + summary_text)
    
    decompose_off, embed_off = set_phase1_flags(False)
    logger.info(f"[FLAGS] Restored after eval: decompose={decompose_off}, embed={embed_off}")
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
