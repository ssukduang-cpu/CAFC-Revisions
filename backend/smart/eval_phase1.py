"""
Phase 1 Eval Harness

Evaluates Phase 1 Smartness improvements by comparing baseline (flags OFF)
vs augmented (flags ON) performance on a curated set of hard queries.

Usage:
    python -m backend.smart.eval_phase1 --baseline
    python -m backend.smart.eval_phase1 --phase1
    python -m backend.smart.eval_phase1 --compare

Output: JSON report with metrics comparison
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

HARD_QUERIES = [
    {
        "id": "multi_issue_101_112",
        "query": "What are the requirements for patent eligibility under Alice and written description under 112?",
        "expected_doctrines": ["101", "112"],
        "category": "multi_issue"
    },
    {
        "id": "multi_issue_103_secondary",
        "query": "How do courts analyze obviousness and secondary considerations together in pharmaceutical patent cases?",
        "expected_doctrines": ["103"],
        "category": "multi_issue"
    },
    {
        "id": "complex_claim_construction",
        "query": "What is the role of prosecution history estoppel and specification context in claim construction?",
        "expected_doctrines": ["112", "claim_construction"],
        "category": "complex"
    },
    {
        "id": "rare_doctrine",
        "query": "What are the elements required to prove inequitable conduct before the CAFC?",
        "expected_doctrines": ["inequitable_conduct"],
        "category": "rare"
    },
    {
        "id": "damages_apportionment",
        "query": "How does the Federal Circuit apply the entire market value rule and apportionment in damages calculations?",
        "expected_doctrines": ["damages"],
        "category": "damages"
    },
    {
        "id": "alice_abstract_idea",
        "query": "What types of claims have been found to be directed to abstract ideas under Alice step one?",
        "expected_doctrines": ["101"],
        "category": "eligibility"
    },
    {
        "id": "enablement_undue_experimentation",
        "query": "What factors determine whether undue experimentation is required for enablement under Wands?",
        "expected_doctrines": ["112"],
        "category": "disclosure"
    },
    {
        "id": "doe_equivalents",
        "query": "What is the function-way-result test for doctrine of equivalents infringement?",
        "expected_doctrines": ["infringement"],
        "category": "infringement"
    },
    {
        "id": "ksr_motivation",
        "query": "After KSR, what motivation is required to combine prior art references for obviousness?",
        "expected_doctrines": ["103"],
        "category": "obviousness"
    },
    {
        "id": "markman_construction",
        "query": "What is the standard of review for Markman claim construction rulings on appeal?",
        "expected_doctrines": ["claim_construction"],
        "category": "procedure"
    }
]


def set_phase1_flags(enabled: bool):
    """Set Phase 1 feature flags and reload modules to ensure they take effect."""
    value = "true" if enabled else "false"
    os.environ["SMART_EMBED_RECALL_ENABLED"] = value
    os.environ["SMART_QUERY_DECOMPOSE_ENABLED"] = value
    
    from importlib import reload
    import backend.smart.config
    reload(backend.smart.config)
    
    import backend.smart.augmenter
    reload(backend.smart.augmenter)
    
    from backend.smart import config as smart_config
    logger.info(f"Phase 1 flags set to: {value} (verified: decompose={smart_config.SMART_QUERY_DECOMPOSE_ENABLED}, embed={smart_config.SMART_EMBED_RECALL_ENABLED})")


async def run_single_query(query_info: Dict) -> Dict[str, Any]:
    """Run a single query and collect metrics."""
    from backend.chat import generate_chat_response
    
    query = query_info["query"]
    query_id = query_info["id"]
    
    start_time = time.time()
    
    try:
        result = await generate_chat_response(
            message=query,
            conversation_id=f"eval_{query_id}_{int(time.time())}"
        )
        
        latency_ms = int((time.time() - start_time) * 1000)
        
        answer = result.get("answer", "")
        sources = result.get("sources", [])
        
        not_found = "NOT FOUND" in answer or "not found" in answer.lower()
        
        verified_citations = 0
        unverified_citations = 0
        for src in sources:
            tier = src.get("confidenceTier", "UNVERIFIED")
            if tier in ["STRONG", "MODERATE"]:
                verified_citations += 1
            else:
                unverified_citations += 1
        
        scotus_present = any("supreme" in str(s.get("caseName", "")).lower() for s in sources)
        en_banc_present = any("en banc" in str(s.get("caseName", "")).lower() for s in sources)
        
        return {
            "query_id": query_id,
            "success": True,
            "latency_ms": latency_ms,
            "not_found": not_found,
            "verified_citations": verified_citations,
            "unverified_citations": unverified_citations,
            "total_sources": len(sources),
            "scotus_present": scotus_present,
            "en_banc_present": en_banc_present,
            "answer_length": len(answer)
        }
        
    except Exception as e:
        return {
            "query_id": query_id,
            "success": False,
            "error": str(e),
            "latency_ms": int((time.time() - start_time) * 1000)
        }


async def run_eval_batch(queries: List[Dict], phase1_enabled: bool) -> Dict[str, Any]:
    """Run evaluation batch with specified flag state."""
    set_phase1_flags(phase1_enabled)
    
    mode = "phase1" if phase1_enabled else "baseline"
    logger.info(f"Running {len(queries)} queries in {mode} mode...")
    
    results = []
    for i, query in enumerate(queries):
        logger.info(f"[{i+1}/{len(queries)}] Running: {query['id']}")
        result = await run_single_query(query)
        results.append(result)
        await asyncio.sleep(0.5)
    
    successful = [r for r in results if r.get("success")]
    
    summary = {
        "mode": mode,
        "total_queries": len(queries),
        "successful": len(successful),
        "failed": len(queries) - len(successful),
        "avg_latency_ms": sum(r["latency_ms"] for r in successful) / len(successful) if successful else 0,
        "not_found_rate": sum(1 for r in successful if r.get("not_found")) / len(successful) if successful else 0,
        "avg_verified_citations": sum(r.get("verified_citations", 0) for r in successful) / len(successful) if successful else 0,
        "scotus_coverage": sum(1 for r in successful if r.get("scotus_present")) / len(successful) if successful else 0,
        "results": results
    }
    
    return summary


def compare_results(baseline: Dict, phase1: Dict) -> Dict[str, Any]:
    """Compare baseline vs phase1 results."""
    comparison = {
        "baseline": {
            "avg_latency_ms": baseline["avg_latency_ms"],
            "not_found_rate": baseline["not_found_rate"],
            "avg_verified_citations": baseline["avg_verified_citations"],
            "scotus_coverage": baseline["scotus_coverage"]
        },
        "phase1": {
            "avg_latency_ms": phase1["avg_latency_ms"],
            "not_found_rate": phase1["not_found_rate"],
            "avg_verified_citations": phase1["avg_verified_citations"],
            "scotus_coverage": phase1["scotus_coverage"]
        },
        "deltas": {
            "latency_delta_ms": phase1["avg_latency_ms"] - baseline["avg_latency_ms"],
            "not_found_delta": phase1["not_found_rate"] - baseline["not_found_rate"],
            "verified_citations_delta": phase1["avg_verified_citations"] - baseline["avg_verified_citations"],
            "scotus_coverage_delta": phase1["scotus_coverage"] - baseline["scotus_coverage"]
        },
        "improvements": {
            "reduced_not_found": phase1["not_found_rate"] < baseline["not_found_rate"],
            "more_verified_citations": phase1["avg_verified_citations"] > baseline["avg_verified_citations"],
            "better_scotus_coverage": phase1["scotus_coverage"] >= baseline["scotus_coverage"]
        }
    }
    
    return comparison


async def main():
    parser = argparse.ArgumentParser(description="Phase 1 Evaluation Harness")
    parser.add_argument("--baseline", action="store_true", help="Run baseline evaluation (flags OFF)")
    parser.add_argument("--phase1", action="store_true", help="Run Phase 1 evaluation (flags ON)")
    parser.add_argument("--compare", action="store_true", help="Run both and compare")
    parser.add_argument("--output", default="phase1_eval_results.json", help="Output file path")
    parser.add_argument("--queries", type=int, default=None, help="Limit number of queries")
    
    args = parser.parse_args()
    
    queries = HARD_QUERIES[:args.queries] if args.queries else HARD_QUERIES
    
    print("\n" + "=" * 60)
    print("PHASE 1 EVALUATION HARNESS")
    print("=" * 60)
    print(f"Queries: {len(queries)}")
    print(f"Output: {args.output}")
    print("")
    
    results = {"timestamp": datetime.utcnow().isoformat(), "queries": len(queries)}
    
    if args.baseline or args.compare:
        print("Running BASELINE evaluation...")
        results["baseline"] = await run_eval_batch(queries, phase1_enabled=False)
        print(f"  Avg latency: {results['baseline']['avg_latency_ms']:.0f}ms")
        print(f"  NOT FOUND rate: {results['baseline']['not_found_rate']:.1%}")
        print(f"  Avg verified citations: {results['baseline']['avg_verified_citations']:.1f}")
    
    if args.phase1 or args.compare:
        print("\nRunning PHASE 1 evaluation...")
        results["phase1"] = await run_eval_batch(queries, phase1_enabled=True)
        print(f"  Avg latency: {results['phase1']['avg_latency_ms']:.0f}ms")
        print(f"  NOT FOUND rate: {results['phase1']['not_found_rate']:.1%}")
        print(f"  Avg verified citations: {results['phase1']['avg_verified_citations']:.1f}")
    
    if args.compare and "baseline" in results and "phase1" in results:
        print("\nCOMPARISON:")
        comparison = compare_results(results["baseline"], results["phase1"])
        results["comparison"] = comparison
        
        print(f"  Latency delta: {comparison['deltas']['latency_delta_ms']:+.0f}ms")
        print(f"  NOT FOUND delta: {comparison['deltas']['not_found_delta']:+.1%}")
        print(f"  Verified citations delta: {comparison['deltas']['verified_citations_delta']:+.1f}")
        print(f"  SCOTUS coverage delta: {comparison['deltas']['scotus_coverage_delta']:+.1%}")
    
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\nResults written to: {args.output}")
    
    set_phase1_flags(False)
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
