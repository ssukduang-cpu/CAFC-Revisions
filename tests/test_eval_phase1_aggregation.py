"""
Unit tests for eval_phase1.py summary aggregation logic.

Verifies that trigger_rate and avg_candidates_added are computed
correctly from per-query telemetry fields.

Run with: python -m pytest tests/test_eval_phase1_aggregation.py -v
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def compute_summary_from_results(results: list) -> dict:
    """
    Replicates the summary computation logic from eval_phase1.py.
    
    This mirrors the run_eval_batch aggregation to test it in isolation.
    """
    successful = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    
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
    
    return {
        "total_queries": len(results),
        "successful": len(successful),
        "failed": len(failed),
        "avg_latency_ms": safe_avg("latency_ms"),
        "not_found_rate": safe_rate("not_found", True),
        "avg_verified_citations": safe_avg("verified_citations"),
        "phase1_trigger_rate": safe_rate("phase1_triggered", True),
        "avg_candidates_added": safe_avg_with_default("candidates_added", 0),
        "avg_phase1_latency_ms": safe_avg_with_default("phase1_latency_ms", 0),
    }


class TestSummaryAggregation:
    """Test the summary aggregation logic for Phase 1 telemetry."""
    
    def test_trigger_rate_and_avg_candidates_basic(self):
        """
        Test fixture: 5 queries, 2 triggered, candidates_added [1,0,0,2,0]
        Expected: trigger_rate = 0.4, avg_candidates_added = 0.6
        """
        results = [
            {"success": True, "phase1_triggered": True, "candidates_added": 1, "latency_ms": 1000},
            {"success": True, "phase1_triggered": False, "candidates_added": 0, "latency_ms": 1000},
            {"success": True, "phase1_triggered": False, "candidates_added": 0, "latency_ms": 1000},
            {"success": True, "phase1_triggered": True, "candidates_added": 2, "latency_ms": 1000},
            {"success": True, "phase1_triggered": False, "candidates_added": 0, "latency_ms": 1000},
        ]
        
        summary = compute_summary_from_results(results)
        
        assert summary["phase1_trigger_rate"] == 0.4, f"Expected 0.4, got {summary['phase1_trigger_rate']}"
        assert summary["avg_candidates_added"] == 0.6, f"Expected 0.6, got {summary['avg_candidates_added']}"
    
    def test_all_triggered(self):
        """All 3 queries triggered with varying candidates."""
        results = [
            {"success": True, "phase1_triggered": True, "candidates_added": 5, "latency_ms": 1000},
            {"success": True, "phase1_triggered": True, "candidates_added": 10, "latency_ms": 1000},
            {"success": True, "phase1_triggered": True, "candidates_added": 15, "latency_ms": 1000},
        ]
        
        summary = compute_summary_from_results(results)
        
        assert summary["phase1_trigger_rate"] == 1.0
        assert summary["avg_candidates_added"] == 10.0
    
    def test_none_triggered_baseline(self):
        """Baseline mode: no queries triggered."""
        results = [
            {"success": True, "phase1_triggered": False, "candidates_added": 0, "latency_ms": 1000},
            {"success": True, "phase1_triggered": False, "candidates_added": 0, "latency_ms": 1000},
            {"success": True, "phase1_triggered": False, "candidates_added": 0, "latency_ms": 1000},
        ]
        
        summary = compute_summary_from_results(results)
        
        assert summary["phase1_trigger_rate"] == 0.0
        assert summary["avg_candidates_added"] == 0.0
    
    def test_missing_telemetry_fields_fail_soft(self):
        """If telemetry fields are missing, treat as 0/false."""
        results = [
            {"success": True, "latency_ms": 1000},
            {"success": True, "latency_ms": 1000},
            {"success": True, "phase1_triggered": True, "candidates_added": 6, "latency_ms": 1000},
        ]
        
        summary = compute_summary_from_results(results)
        
        assert summary["phase1_trigger_rate"] == pytest.approx(1/3)
        assert summary["avg_candidates_added"] == 2.0
    
    def test_failed_queries_excluded(self):
        """Failed queries should not affect trigger rate computation."""
        results = [
            {"success": True, "phase1_triggered": True, "candidates_added": 5, "latency_ms": 1000},
            {"success": True, "phase1_triggered": False, "candidates_added": 0, "latency_ms": 1000},
            {"success": False, "phase1_triggered": True, "candidates_added": 100, "latency_ms": 1000},
        ]
        
        summary = compute_summary_from_results(results)
        
        assert summary["successful"] == 2
        assert summary["failed"] == 1
        assert summary["phase1_trigger_rate"] == 0.5
        assert summary["avg_candidates_added"] == 2.5
    
    def test_empty_results(self):
        """Edge case: no results."""
        results = []
        
        summary = compute_summary_from_results(results)
        
        assert summary["phase1_trigger_rate"] == 0.0
        assert summary["avg_candidates_added"] == 0.0
    
    def test_phase1_latency_aggregation(self):
        """Verify phase1_latency_ms is averaged correctly."""
        results = [
            {"success": True, "phase1_triggered": True, "candidates_added": 5, "phase1_latency_ms": 100, "latency_ms": 1000},
            {"success": True, "phase1_triggered": True, "candidates_added": 5, "phase1_latency_ms": 200, "latency_ms": 1000},
            {"success": True, "phase1_triggered": False, "candidates_added": 0, "phase1_latency_ms": 0, "latency_ms": 1000},
        ]
        
        summary = compute_summary_from_results(results)
        
        assert summary["avg_phase1_latency_ms"] == 100.0
    
    def test_verified_citations_aggregation(self):
        """Verify verified_citations is averaged correctly."""
        results = [
            {"success": True, "verified_citations": 3, "latency_ms": 1000},
            {"success": True, "verified_citations": 5, "latency_ms": 1000},
            {"success": True, "verified_citations": 7, "latency_ms": 1000},
        ]
        
        summary = compute_summary_from_results(results)
        
        assert summary["avg_verified_citations"] == 5.0


class TestTriggerRateEdgeCases:
    """Additional edge case tests for trigger rate computation."""
    
    def test_single_query_triggered(self):
        """Single query, triggered."""
        results = [{"success": True, "phase1_triggered": True, "candidates_added": 10}]
        summary = compute_summary_from_results(results)
        assert summary["phase1_trigger_rate"] == 1.0
        assert summary["avg_candidates_added"] == 10.0
    
    def test_single_query_not_triggered(self):
        """Single query, not triggered."""
        results = [{"success": True, "phase1_triggered": False, "candidates_added": 0}]
        summary = compute_summary_from_results(results)
        assert summary["phase1_trigger_rate"] == 0.0
        assert summary["avg_candidates_added"] == 0.0
    
    def test_candidates_without_trigger_flag(self):
        """Candidates added but trigger flag missing - still counts candidates."""
        results = [
            {"success": True, "candidates_added": 5},
            {"success": True, "candidates_added": 5},
        ]
        summary = compute_summary_from_results(results)
        assert summary["phase1_trigger_rate"] == 0.0
        assert summary["avg_candidates_added"] == 5.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
