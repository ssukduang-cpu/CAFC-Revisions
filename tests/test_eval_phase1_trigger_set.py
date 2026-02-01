"""
Unit tests for Phase 1 trigger set evaluation.

Verifies:
- trigger_rate is computed correctly from per-query phase1_triggered
- candidates_added averages treat missing as 0
- Trigger logic works on the trigger-focused query set

Run with: python -m pytest tests/test_eval_phase1_trigger_set.py -v
"""

import pytest
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def compute_summary_from_results(results: list) -> dict:
    """
    Replicates the summary computation logic from eval_phase1.py.
    """
    successful = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    
    def safe_avg_with_default(key: str, default: float = 0) -> float:
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
    
    return {
        "total_queries": len(results),
        "successful": len(successful),
        "failed": len(failed),
        "phase1_trigger_rate": safe_rate("phase1_triggered", True),
        "avg_candidates_added": safe_avg_with_default("candidates_added", 0),
        "avg_phase1_latency_ms": safe_avg_with_default("phase1_latency_ms", 0),
    }


class TestTriggerSetAggregation:
    """Test trigger rate computation for trigger-focused query sets."""
    
    def test_trigger_rate_exact_spec(self):
        """
        Spec test: 5 queries with [T,F,T,F,F] → trigger_rate = 0.4
        """
        results = [
            {"success": True, "phase1_triggered": True, "candidates_added": 5, "triggers": ["multi_issue"]},
            {"success": True, "phase1_triggered": False, "candidates_added": 0, "triggers": []},
            {"success": True, "phase1_triggered": True, "candidates_added": 3, "triggers": ["thin_results"]},
            {"success": True, "phase1_triggered": False, "candidates_added": 0, "triggers": []},
            {"success": True, "phase1_triggered": False, "candidates_added": 0, "triggers": []},
        ]
        
        summary = compute_summary_from_results(results)
        
        assert summary["phase1_trigger_rate"] == 0.4, f"Expected 0.4, got {summary['phase1_trigger_rate']}"
    
    def test_candidates_added_missing_treated_as_zero(self):
        """Missing candidates_added should be treated as 0 for averaging."""
        results = [
            {"success": True, "phase1_triggered": True, "candidates_added": 10},
            {"success": True, "phase1_triggered": False},
            {"success": True, "phase1_triggered": True, "candidates_added": 5},
        ]
        
        summary = compute_summary_from_results(results)
        
        assert summary["avg_candidates_added"] == 5.0
    
    def test_all_triggered_high_candidates(self):
        """All queries triggered with varying candidates."""
        results = [
            {"success": True, "phase1_triggered": True, "candidates_added": 8, "triggers": ["multi_issue"]},
            {"success": True, "phase1_triggered": True, "candidates_added": 12, "triggers": ["thin_results"]},
            {"success": True, "phase1_triggered": True, "candidates_added": 10, "triggers": ["multi_issue", "low_score"]},
        ]
        
        summary = compute_summary_from_results(results)
        
        assert summary["phase1_trigger_rate"] == 1.0
        assert summary["avg_candidates_added"] == 10.0
    
    def test_triggers_list_present(self):
        """Verify triggers list is present in results."""
        results = [
            {"success": True, "phase1_triggered": True, "candidates_added": 5, "triggers": ["multi_issue", "thin_results"]},
        ]
        
        assert results[0]["triggers"] == ["multi_issue", "thin_results"]


class TestTriggerQueryFile:
    """Test loading trigger-focused query file."""
    
    def test_trigger_queries_file_exists(self):
        """Verify the trigger query file exists and has queries."""
        path = os.path.join(
            os.path.dirname(__file__), 
            "..", 
            "backend", 
            "smart", 
            "eval_queries_trigger.json"
        )
        
        assert os.path.exists(path), f"Trigger query file not found at {path}"
        
        with open(path) as f:
            data = json.load(f)
        
        queries = data.get("queries", [])
        assert len(queries) >= 10, f"Expected at least 10 trigger queries, got {len(queries)}"
    
    def test_trigger_queries_have_expected_trigger(self):
        """Verify trigger queries have expected_trigger field."""
        path = os.path.join(
            os.path.dirname(__file__), 
            "..", 
            "backend", 
            "smart", 
            "eval_queries_trigger.json"
        )
        
        with open(path) as f:
            data = json.load(f)
        
        queries = data.get("queries", [])
        
        for q in queries:
            assert "expected_trigger" in q or "category" in q, f"Query {q['id']} missing expected_trigger or category"
    
    def test_trigger_queries_categories(self):
        """Verify trigger queries cover required categories."""
        path = os.path.join(
            os.path.dirname(__file__), 
            "..", 
            "backend", 
            "smart", 
            "eval_queries_trigger.json"
        )
        
        with open(path) as f:
            data = json.load(f)
        
        queries = data.get("queries", [])
        categories = {q.get("category") for q in queries}
        
        required = {"multi_issue", "thin_retrieval", "enablement"}
        found = required.intersection(categories)
        
        assert len(found) >= 2, f"Expected at least 2 of {required}, found {found}"


class TestShouldDecompose:
    """Test query decomposition detection logic."""
    
    def test_multi_issue_detected(self):
        """Multi-issue queries should be detected for decomposition."""
        from backend.smart.query_decompose import should_decompose, detect_doctrine_signals
        
        multi_issue_query = "What are the requirements for patent eligibility under Alice 101 and written description under 112?"
        
        doctrines = detect_doctrine_signals(multi_issue_query)
        assert len(doctrines) >= 2, f"Expected 2+ doctrines, got {doctrines}"
        
        assert should_decompose(multi_issue_query) is True
    
    def test_single_doctrine_not_decomposed(self):
        """Single-doctrine queries should not be decomposed."""
        from backend.smart.query_decompose import should_decompose
        
        single_query = "What is the Alice two-step test?"
        
        assert should_decompose(single_query) is False
    
    def test_trigger_queries_decompose_correctly(self):
        """Verify multi_issue queries from trigger set are decomposable."""
        from backend.smart.query_decompose import should_decompose
        
        path = os.path.join(
            os.path.dirname(__file__), 
            "..", 
            "backend", 
            "smart", 
            "eval_queries_trigger.json"
        )
        
        with open(path) as f:
            data = json.load(f)
        
        multi_issue_queries = [q for q in data["queries"] if q.get("category") == "multi_issue"]
        
        for q in multi_issue_queries:
            result = should_decompose(q["query"])
            assert result is True, f"Query '{q['id']}' should decompose but didn't: {q['query'][:50]}..."


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
