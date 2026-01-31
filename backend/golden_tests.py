"""
Golden Test Harness for Voyager Integration

Verifies that the Voyager observability layer has ZERO impact on answer quality.
Runs a set of canonical queries and validates that responses match expected patterns.
"""

import asyncio
import json
import logging
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from backend.chat import generate_chat_response

logger = logging.getLogger(__name__)

GOLDEN_QUERIES = [
    {
        "id": "alice_101",
        "query": "What is the Alice two-step test for patent eligibility under 35 USC 101?",
        "expected_patterns": ["abstract idea", "inventive concept", "Alice", "101"],
        "min_sources": 1
    },
    {
        "id": "ksr_obviousness",
        "query": "What is the KSR standard for obviousness under 35 USC 103?",
        "expected_patterns": ["obvious", "KSR", "103", "motivation"],
        "min_sources": 1
    },
    {
        "id": "claim_construction",
        "query": "What is the standard for claim construction under Phillips v. AWH?",
        "expected_patterns": ["claim", "construction", "Phillips", "ordinary meaning"],
        "min_sources": 1
    },
    {
        "id": "markman",
        "query": "What is a Markman hearing?",
        "expected_patterns": ["claim", "construction", "hearing"],
        "min_sources": 1
    },
    {
        "id": "willfulness",
        "query": "What is the standard for willful infringement?",
        "expected_patterns": ["willful", "infringement", "Halo"],
        "min_sources": 1
    }
]


async def run_golden_query(query_config: Dict[str, Any]) -> Dict[str, Any]:
    """Run a single golden query and validate response."""
    query_id = query_config["id"]
    query = query_config["query"]
    expected_patterns = query_config.get("expected_patterns", [])
    min_sources = query_config.get("min_sources", 0)
    
    try:
        response = await generate_chat_response(
            message=query,
            opinion_ids=None,
            conversation_id=f"golden_test_{query_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            party_only=False
        )
        
        answer = response.get("answer_markdown", "")
        sources = response.get("sources", [])
        run_id = response.get("debug", {}).get("run_id")
        
        patterns_found = []
        patterns_missing = []
        
        answer_lower = answer.lower()
        for pattern in expected_patterns:
            if pattern.lower() in answer_lower:
                patterns_found.append(pattern)
            else:
                patterns_missing.append(pattern)
        
        sources_ok = len(sources) >= min_sources
        patterns_ok = len(patterns_missing) == 0
        answer_hash = hashlib.sha256(answer.encode()).hexdigest()[:16]
        
        result = {
            "query_id": query_id,
            "query": query,
            "success": sources_ok and patterns_ok,
            "answer_hash": answer_hash,
            "answer_length": len(answer),
            "sources_count": len(sources),
            "sources_ok": sources_ok,
            "patterns_found": patterns_found,
            "patterns_missing": patterns_missing,
            "patterns_ok": patterns_ok,
            "run_id": run_id,
            "has_voyager_logging": run_id is not None
        }
        
        return result
        
    except Exception as e:
        logger.error(f"Golden test {query_id} failed: {str(e)}")
        return {
            "query_id": query_id,
            "query": query,
            "success": False,
            "error": str(e)
        }


async def run_golden_suite(queries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Run the full golden test suite."""
    queries = queries or GOLDEN_QUERIES
    results = []
    
    logger.info(f"Starting golden test suite with {len(queries)} queries")
    
    for query_config in queries:
        result = await run_golden_query(query_config)
        results.append(result)
        logger.info(f"Golden test {result['query_id']}: {'PASS' if result.get('success') else 'FAIL'}")
    
    passed = sum(1 for r in results if r.get("success"))
    failed = len(results) - passed
    
    return {
        "timestamp": datetime.now().isoformat(),
        "total_queries": len(queries),
        "passed": passed,
        "failed": failed,
        "pass_rate": f"{(passed / len(queries)) * 100:.1f}%",
        "all_passed": failed == 0,
        "results": results
    }


async def compare_baselines(baseline_file: Optional[str] = None) -> Dict[str, Any]:
    """Compare current results against stored baseline."""
    current = await run_golden_suite()
    
    if not baseline_file:
        return {
            "status": "no_baseline",
            "message": "No baseline file provided. Run with baseline_file to compare.",
            "current": current
        }
    
    try:
        with open(baseline_file, 'r') as f:
            baseline = json.load(f)
    except FileNotFoundError:
        with open(baseline_file, 'w') as f:
            json.dump(current, f, indent=2)
        return {
            "status": "baseline_created",
            "message": f"Baseline file created at {baseline_file}",
            "current": current
        }
    
    diffs = []
    for curr_result in current["results"]:
        query_id = curr_result["query_id"]
        base_result = next((r for r in baseline.get("results", []) if r["query_id"] == query_id), None)
        
        if not base_result:
            diffs.append({
                "query_id": query_id,
                "diff_type": "new_query",
                "message": "Query not in baseline"
            })
            continue
        
        if curr_result.get("answer_hash") != base_result.get("answer_hash"):
            diffs.append({
                "query_id": query_id,
                "diff_type": "answer_changed",
                "old_hash": base_result.get("answer_hash"),
                "new_hash": curr_result.get("answer_hash"),
                "old_length": base_result.get("answer_length"),
                "new_length": curr_result.get("answer_length")
            })
        
        if curr_result.get("sources_count", 0) != base_result.get("sources_count", 0):
            diffs.append({
                "query_id": query_id,
                "diff_type": "source_count_changed",
                "old_count": base_result.get("sources_count"),
                "new_count": curr_result.get("sources_count")
            })
    
    return {
        "status": "comparison_complete",
        "baseline_timestamp": baseline.get("timestamp"),
        "current_timestamp": current.get("timestamp"),
        "diffs_found": len(diffs),
        "no_regressions": len(diffs) == 0,
        "diffs": diffs,
        "current": current
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    async def main():
        print("Running Golden Test Suite...")
        results = await run_golden_suite()
        print(json.dumps(results, indent=2))
    
    asyncio.run(main())
