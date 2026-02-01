"""
Phase 1 Regression Guards

Tests to ensure Phase 1 augmentation does not degrade results when
baseline retrieval is already strong.

Run with: python -m pytest tests/test_phase1_regression_guards.py -v
"""

import pytest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.smart.augmenter import should_augment, is_strong_baseline
from backend.smart import config as smart_config


class TestStrongBaselineGuard:
    """Test that strong baselines skip augmentation."""
    
    def test_strong_baseline_by_count(self):
        """Skip augmentation when FTS returns sufficient results."""
        fts_results = [{"id": i, "score": 0.1} for i in range(10)]
        
        is_strong, evidence = is_strong_baseline(fts_results)
        
        assert is_strong is True
        assert evidence["fts_count"] == 10
        assert evidence["is_strong"] is True
    
    def test_strong_baseline_by_score(self):
        """Skip augmentation when top score is high."""
        fts_results = [{"id": 1, "score": 0.5}]
        
        is_strong, evidence = is_strong_baseline(fts_results)
        
        assert is_strong is True
        assert evidence["top_score"] == 0.5
        assert evidence["is_strong"] is True
    
    def test_weak_baseline_triggers(self):
        """Augmentation triggers for weak baseline."""
        fts_results = [{"id": i, "score": 0.05} for i in range(3)]
        
        is_strong, evidence = is_strong_baseline(fts_results)
        
        assert is_strong is False
        assert evidence["fts_count"] == 3
        assert evidence["top_score"] == 0.05
    
    def test_empty_baseline_is_weak(self):
        """Empty results are weak baseline."""
        fts_results = []
        
        is_strong, evidence = is_strong_baseline(fts_results)
        
        assert is_strong is False
        assert evidence["fts_count"] == 0


class TestShouldAugmentGuard:
    """Test should_augment returns skip_strong_baseline reason."""
    
    def test_skip_strong_baseline_in_reasons(self):
        """Strong baseline returns skip_strong_baseline reason."""
        fts_results = [{"id": i, "score": 0.2} for i in range(10)]
        query = "What is the Alice test for patent eligibility and enablement under 112?"
        
        should_trigger, reasons, context = should_augment(fts_results, query)
        
        assert should_trigger is False
        assert "skip_strong_baseline" in reasons
        assert context.get("strong_baseline_evidence", {}).get("is_strong") is True
    
    def test_weak_baseline_allows_multi_issue(self):
        """Weak baseline allows multi_issue trigger."""
        original_decompose = smart_config.SMART_QUERY_DECOMPOSE_ENABLED
        smart_config.SMART_QUERY_DECOMPOSE_ENABLED = True
        
        try:
            fts_results = [{"id": i, "score": 0.05} for i in range(3)]
            query = "What is the Alice test for patent eligibility and enablement under 112?"
            
            should_trigger, reasons, context = should_augment(fts_results, query)
            
            assert should_trigger is True
            assert "multi_issue" in reasons or "thin_results" in reasons
        finally:
            smart_config.SMART_QUERY_DECOMPOSE_ENABLED = original_decompose


class TestNoNotFoundFlip:
    """
    Regression guard: Phase 1 should not flip not_found from False to True
    when baseline has sufficient retrieval.
    
    These tests use mocked scenarios to verify the guard logic.
    """
    
    def test_strong_baseline_prevents_augmentation(self):
        """With strong baseline, augmentation is skipped entirely."""
        fts_results = [{"id": i, "score": 0.25, "title": f"Case {i}"} for i in range(12)]
        query = "Alice and Mayo eligibility test"
        
        should_trigger, reasons, context = should_augment(fts_results, query)
        
        assert should_trigger is False, "Strong baseline should prevent augmentation"
        assert "skip_strong_baseline" in reasons
    
    def test_guard_thresholds_configurable(self):
        """Verify guard uses configurable thresholds."""
        assert hasattr(smart_config, "STRONG_BASELINE_MIN_SOURCES")
        assert hasattr(smart_config, "STRONG_BASELINE_MIN_SCORE")
        
        assert smart_config.STRONG_BASELINE_MIN_SOURCES >= 1
        assert smart_config.STRONG_BASELINE_MIN_SCORE > 0


class TestCandidateLimits:
    """Test that candidate limits are conservative."""
    
    def test_max_subqueries_limited(self):
        """MAX_SUBQUERIES should be conservative."""
        assert smart_config.MAX_SUBQUERIES <= 4
    
    def test_max_candidates_limited(self):
        """MAX_AUGMENT_CANDIDATES should be conservative."""
        assert smart_config.MAX_AUGMENT_CANDIDATES <= 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
