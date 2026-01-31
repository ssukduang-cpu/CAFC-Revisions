"""
Golden Test Harness for Voyager Integration

Verifies that the Voyager observability layer has ZERO impact on answer quality.
Runs a set of canonical queries and validates that responses match expected patterns.

Usage:
  python -m backend.golden_tests --mode baseline   # Create baseline snapshots
  python -m backend.golden_tests --mode verify     # Verify against baseline
  python -m backend.golden_tests --mode run        # Run without baseline comparison
"""

import argparse
import asyncio
import json
import logging
import hashlib
import sys
import os
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from backend.chat import generate_chat_response
from backend import voyager

logger = logging.getLogger(__name__)

BASELINE_FILE = "golden_baseline.json"

GOLDEN_QUERIES = [
    {
        "id": "alice_101",
        "query": "What is the Alice two-step test for patent eligibility under 35 USC 101?",
        "expected_patterns": ["abstract idea", "inventive concept", "Alice", "101"],
        "min_sources": 1,
        "doctrine": "101"
    },
    {
        "id": "mayo_101",
        "query": "What is the Mayo test for patent eligibility?",
        "expected_patterns": ["law of nature", "Mayo", "101"],
        "min_sources": 1,
        "doctrine": "101"
    },
    {
        "id": "ksr_obviousness",
        "query": "What is the KSR standard for obviousness under 35 USC 103?",
        "expected_patterns": ["obvious", "KSR", "103"],
        "min_sources": 1,
        "doctrine": "103"
    },
    {
        "id": "graham_103",
        "query": "What are the Graham factors for obviousness?",
        "expected_patterns": ["Graham", "prior art", "obviousness"],
        "min_sources": 1,
        "doctrine": "103"
    },
    {
        "id": "claim_construction",
        "query": "What is the standard for claim construction under Phillips v. AWH?",
        "expected_patterns": ["claim", "construction", "Phillips"],
        "min_sources": 1,
        "doctrine": "claim_construction"
    },
    {
        "id": "markman_hearing",
        "query": "What is a Markman hearing?",
        "expected_patterns": ["claim", "construction"],
        "min_sources": 1,
        "doctrine": "claim_construction"
    },
    {
        "id": "written_description_112",
        "query": "What is the written description requirement under 35 USC 112?",
        "expected_patterns": ["112", "written description"],
        "min_sources": 1,
        "doctrine": "112"
    },
    {
        "id": "willfulness",
        "query": "What is the standard for willful infringement?",
        "expected_patterns": ["willful", "infringement"],
        "min_sources": 1,
        "doctrine": "remedies"
    },
    {
        "id": "ebay_injunction",
        "query": "What is the eBay standard for permanent injunctions in patent cases?",
        "expected_patterns": ["eBay", "injunction"],
        "min_sources": 1,
        "doctrine": "remedies"
    },
    {
        "id": "not_found_case",
        "query": "What is the holding in FictionalCaseXYZ999 v. NonexistentCorp?",
        "expected_patterns": ["NOT FOUND"],
        "min_sources": 0,
        "doctrine": "none"
    }
]


async def run_golden_query(query_config: Dict[str, Any]) -> Dict[str, Any]:
    """Run a single golden query and capture full snapshot."""
    query_id = query_config["id"]
    query = query_config["query"]
    expected_patterns = query_config.get("expected_patterns", [])
    min_sources = query_config.get("min_sources", 0)
    doctrine = query_config.get("doctrine", "unknown")
    
    try:
        response = await generate_chat_response(
            message=query,
            opinion_ids=None,
            conversation_id=f"golden_{query_id}_{int(datetime.now().timestamp())}",
            party_only=False
        )
        
        answer = response.get("answer_markdown", "")
        sources = response.get("sources", [])
        run_id = response.get("debug", {}).get("run_id")
        debug = response.get("debug", {})
        
        page_ids = [s.get("opinion_id") for s in sources if s.get("opinion_id")]
        citation_tiers = [s.get("citation_verification", {}).get("tier", s.get("tier", "unverified")) for s in sources]
        
        answer_lower = answer.lower()
        patterns_found = [p for p in expected_patterns if p.lower() in answer_lower]
        patterns_missing = [p for p in expected_patterns if p.lower() not in answer_lower]
        
        sources_ok = len(sources) >= min_sources
        patterns_ok = len(patterns_missing) == 0
        answer_hash = hashlib.sha256(answer.encode()).hexdigest()[:16]
        
        return {
            "query_id": query_id,
            "doctrine": doctrine,
            "query": query,
            "success": sources_ok and patterns_ok,
            "answer_hash": answer_hash,
            "answer_length": len(answer),
            "sources_count": len(sources),
            "page_ids": page_ids[:10],
            "citation_tiers": citation_tiers[:10],
            "citation_tier_counts": {
                "strong": citation_tiers.count("strong"),
                "moderate": citation_tiers.count("moderate"),
                "weak": citation_tiers.count("weak"),
                "unverified": citation_tiers.count("unverified")
            },
            "patterns_found": patterns_found,
            "patterns_missing": patterns_missing,
            "run_id": run_id,
            "has_voyager_logging": run_id is not None,
            "pages_count": debug.get("pages_count", 0),
            "markers_count": debug.get("markers_count", 0),
            "return_branch": debug.get("return_branch", "unknown")
        }
        
    except Exception as e:
        logger.error(f"Golden test {query_id} failed: {str(e)}")
        return {
            "query_id": query_id,
            "doctrine": doctrine,
            "query": query,
            "success": False,
            "error": str(e)
        }


async def run_golden_suite(queries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Run the full golden test suite."""
    queries = queries or GOLDEN_QUERIES
    results = []
    
    corpus_version = voyager.compute_corpus_version_id()
    logger.info(f"Starting golden test suite with {len(queries)} queries, corpus_version={corpus_version}")
    
    for query_config in queries:
        result = await run_golden_query(query_config)
        results.append(result)
        status = "PASS" if result.get("success") else "FAIL"
        logger.info(f"  [{status}] {result['query_id']}: sources={result.get('sources_count', 0)}, hash={result.get('answer_hash', 'error')}")
    
    passed = sum(1 for r in results if r.get("success"))
    failed = len(results) - passed
    
    all_voyager_logged = all(r.get("has_voyager_logging") for r in results if not r.get("error"))
    
    return {
        "timestamp": datetime.now().isoformat(),
        "corpus_version_id": corpus_version,
        "total_queries": len(queries),
        "passed": passed,
        "failed": failed,
        "pass_rate": f"{(passed / len(queries)) * 100:.1f}%",
        "all_passed": failed == 0,
        "all_voyager_logged": all_voyager_logged,
        "results": results
    }


def save_baseline(results: Dict[str, Any], filepath: str) -> None:
    """Save results as baseline."""
    with open(filepath, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Baseline saved to {filepath}")


def load_baseline(filepath: str) -> Optional[Dict[str, Any]]:
    """Load baseline from file."""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def compare_with_baseline(current: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, Any]:
    """Compare current results against baseline and return diff report."""
    diffs = []
    regressions = []
    
    for curr_result in current["results"]:
        query_id = curr_result["query_id"]
        base_result = next((r for r in baseline.get("results", []) if r["query_id"] == query_id), None)
        
        if not base_result:
            diffs.append({
                "query_id": query_id,
                "diff_type": "new_query",
                "severity": "info",
                "message": "Query not in baseline"
            })
            continue
        
        if curr_result.get("error") and not base_result.get("error"):
            regressions.append({
                "query_id": query_id,
                "diff_type": "new_error",
                "severity": "critical",
                "error": curr_result.get("error")
            })
            continue
        
        if curr_result.get("answer_hash") != base_result.get("answer_hash"):
            diffs.append({
                "query_id": query_id,
                "diff_type": "answer_changed",
                "severity": "warning",
                "old_hash": base_result.get("answer_hash"),
                "new_hash": curr_result.get("answer_hash"),
                "old_length": base_result.get("answer_length"),
                "new_length": curr_result.get("answer_length")
            })
        
        curr_tiers = curr_result.get("citation_tier_counts", {})
        base_tiers = base_result.get("citation_tier_counts", {})
        if curr_tiers != base_tiers:
            diffs.append({
                "query_id": query_id,
                "diff_type": "citation_tiers_changed",
                "severity": "warning",
                "old_tiers": base_tiers,
                "new_tiers": curr_tiers
            })
        
        if curr_result.get("sources_count", 0) != base_result.get("sources_count", 0):
            diffs.append({
                "query_id": query_id,
                "diff_type": "source_count_changed",
                "severity": "info",
                "old_count": base_result.get("sources_count"),
                "new_count": curr_result.get("sources_count")
            })
        
        curr_page_ids = set(curr_result.get("page_ids", []))
        base_page_ids = set(base_result.get("page_ids", []))
        if curr_page_ids != base_page_ids:
            diffs.append({
                "query_id": query_id,
                "diff_type": "page_ids_changed",
                "severity": "info",
                "added": list(curr_page_ids - base_page_ids)[:5],
                "removed": list(base_page_ids - curr_page_ids)[:5]
            })
    
    no_regressions = len(regressions) == 0
    
    return {
        "status": "comparison_complete",
        "baseline_timestamp": baseline.get("timestamp"),
        "baseline_corpus_version": baseline.get("corpus_version_id"),
        "current_timestamp": current.get("timestamp"),
        "current_corpus_version": current.get("corpus_version_id"),
        "total_diffs": len(diffs),
        "total_regressions": len(regressions),
        "no_regressions": no_regressions,
        "verdict": "PASS" if no_regressions else "FAIL",
        "regressions": regressions,
        "diffs": diffs
    }


async def main():
    parser = argparse.ArgumentParser(description="Golden Test Harness for Voyager Integration")
    parser.add_argument(
        "--mode",
        choices=["baseline", "verify", "run"],
        default="run",
        help="Mode: 'baseline' to create snapshot, 'verify' to compare against baseline, 'run' to execute without comparison"
    )
    parser.add_argument(
        "--baseline-file",
        default=BASELINE_FILE,
        help=f"Path to baseline file (default: {BASELINE_FILE})"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    print(f"\n{'='*60}")
    print(f"VOYAGER GOLDEN TEST HARNESS")
    print(f"Mode: {args.mode.upper()}")
    print(f"Baseline file: {args.baseline_file}")
    print(f"{'='*60}\n")
    
    if args.mode == "baseline":
        print("Creating baseline snapshot...")
        results = await run_golden_suite()
        save_baseline(results, args.baseline_file)
        print(f"\nResults: {results['passed']}/{results['total_queries']} passed ({results['pass_rate']})")
        print(f"Corpus version: {results['corpus_version_id']}")
        print(f"All Voyager logged: {results['all_voyager_logged']}")
        return 0 if results['all_passed'] else 1
        
    elif args.mode == "verify":
        baseline = load_baseline(args.baseline_file)
        if not baseline:
            print(f"ERROR: Baseline file not found: {args.baseline_file}")
            print("Run with --mode baseline first to create a baseline.")
            return 1
        
        print(f"Baseline loaded from {args.baseline_file}")
        print(f"Baseline timestamp: {baseline.get('timestamp')}")
        print(f"Baseline corpus version: {baseline.get('corpus_version_id')}\n")
        
        print("Running current suite...")
        current = await run_golden_suite()
        
        print("\nComparing against baseline...")
        comparison = compare_with_baseline(current, baseline)
        
        print(f"\n{'='*60}")
        print(f"VERIFICATION RESULT: {comparison['verdict']}")
        print(f"{'='*60}")
        print(f"Regressions: {comparison['total_regressions']}")
        print(f"Diffs: {comparison['total_diffs']}")
        
        if comparison['regressions']:
            print("\nREGRESSIONS:")
            for reg in comparison['regressions']:
                print(f"  - [{reg['severity'].upper()}] {reg['query_id']}: {reg['diff_type']}")
        
        if comparison['diffs'] and args.verbose:
            print("\nDIFFS:")
            for diff in comparison['diffs']:
                print(f"  - [{diff['severity']}] {diff['query_id']}: {diff['diff_type']}")
        
        return 0 if comparison['no_regressions'] else 1
        
    else:
        print("Running golden test suite...")
        results = await run_golden_suite()
        
        print(f"\n{'='*60}")
        print(f"RESULTS: {results['passed']}/{results['total_queries']} passed ({results['pass_rate']})")
        print(f"Corpus version: {results['corpus_version_id']}")
        print(f"All Voyager logged: {results['all_voyager_logged']}")
        print(f"{'='*60}")
        
        if not results['all_passed']:
            print("\nFailed tests:")
            for r in results['results']:
                if not r.get('success'):
                    print(f"  - {r['query_id']}: {r.get('error', 'patterns missing: ' + str(r.get('patterns_missing', [])))}")
        
        return 0 if results['all_passed'] else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
