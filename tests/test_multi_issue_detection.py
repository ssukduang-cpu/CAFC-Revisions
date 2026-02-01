"""
Unit tests for multi-issue detection robustness.

Ensures consistent detection across various query formats and phrasing.

Run with: python -m pytest tests/test_multi_issue_detection.py -v
"""

import pytest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.smart.query_decompose import (
    detect_doctrine_signals,
    should_decompose,
    decompose_query,
    get_decomposition_info,
    has_conjunction_pattern
)


class TestMultiIssueDetection:
    """Test multi-issue detection for trigger queries."""
    
    def test_multi_issue_101_112_a(self):
        """The query multi_issue_101_112_a should trigger."""
        query = "What are the requirements for patent eligibility under Alice 101 and written description under 112(a)?"
        
        doctrines, evidence = detect_doctrine_signals(query)
        
        assert "101" in doctrines, f"Should detect 101, got {doctrines}"
        assert "112" in doctrines, f"Should detect 112, got {doctrines}"
        assert len(doctrines) >= 2, f"Should detect 2+ doctrines, got {doctrines}"
        
        assert should_decompose(query) is True, "Should decompose multi-issue query"
        
        subqueries = decompose_query(query)
        assert len(subqueries) == 2, f"Expected 2 subqueries, got {len(subqueries)}: {subqueries}"
    
    def test_multi_issue_101_112_b(self):
        """The query multi_issue_101_112_b should trigger."""
        query = "When is a software claim both abstract under 101 and lacking enablement under 112?"
        
        doctrines, evidence = detect_doctrine_signals(query)
        
        assert "101" in doctrines, f"Should detect 101 from 'abstract', got {doctrines}, evidence={evidence}"
        assert "112" in doctrines, f"Should detect 112 from 'enablement', got {doctrines}, evidence={evidence}"
        assert len(doctrines) >= 2, f"Should detect 2+ doctrines, got {doctrines}"
        
        assert should_decompose(query) is True, "Should decompose multi-issue query"
        
        subqueries = decompose_query(query)
        assert len(subqueries) == 2, f"Expected 2 subqueries, got {len(subqueries)}: {subqueries}"
    
    def test_multi_issue_103_112(self):
        """Obviousness + written description should trigger."""
        query = "How does obviousness analysis differ from written description requirements for genus claims?"
        
        doctrines, evidence = detect_doctrine_signals(query)
        
        assert "103" in doctrines, f"Should detect 103, got {doctrines}"
        assert "112" in doctrines, f"Should detect 112, got {doctrines}"
        
        assert should_decompose(query) is True
        assert len(decompose_query(query)) == 2


class TestVariantFormats:
    """Test various formatting variants for multi-issue queries."""
    
    def test_section_symbols(self):
        """§101/§112 format should trigger."""
        query = "What are the differences between §101 eligibility and §112 enablement requirements?"
        
        doctrines, evidence = detect_doctrine_signals(query)
        
        assert "101" in doctrines, f"Should detect 101 from §101, got {doctrines}"
        assert "112" in doctrines, f"Should detect 112 from §112, got {doctrines}"
        assert should_decompose(query) is True
        assert len(decompose_query(query)) == 2
    
    def test_section_with_space(self):
        """§ 101 (with space) format should trigger."""
        query = "Compare § 101 abstract idea with § 112 indefiniteness analysis."
        
        doctrines, evidence = detect_doctrine_signals(query)
        
        assert "101" in doctrines, f"Should detect 101, got {doctrines}"
        assert "112" in doctrines, f"Should detect 112, got {doctrines}"
        assert should_decompose(query) is True
    
    def test_section_word(self):
        """'Section 101' format should trigger."""
        query = "How do courts analyze claims under Section 101 and Section 112?"
        
        doctrines, evidence = detect_doctrine_signals(query)
        
        assert "101" in doctrines
        assert "112" in doctrines
        assert should_decompose(query) is True
    
    def test_slash_separator(self):
        """101/112 slash format should trigger."""
        query = "What are the 101/112 requirements for biotech claims?"
        
        doctrines, evidence = detect_doctrine_signals(query)
        
        assert "101" in doctrines
        assert "112" in doctrines
        assert should_decompose(query) is True
    
    def test_term_based_detection(self):
        """Eligibility + enablement terms should trigger even without numbers."""
        query = "How do patent eligibility requirements relate to enablement requirements?"
        
        doctrines, evidence = detect_doctrine_signals(query)
        
        assert "101" in doctrines, f"Should detect 101 from 'eligibility', got {doctrines}, evidence={evidence}"
        assert "112" in doctrines, f"Should detect 112 from 'enablement', got {doctrines}, evidence={evidence}"
        assert should_decompose(query) is True
    
    def test_alice_plus_written_description(self):
        """Alice + written description terms should trigger."""
        query = "What is the relationship between Alice step two and written description requirements?"
        
        doctrines, evidence = detect_doctrine_signals(query)
        
        assert "101" in doctrines, f"Should detect 101 from 'alice', got {doctrines}"
        assert "112" in doctrines, f"Should detect 112 from 'written description', got {doctrines}"
        assert should_decompose(query) is True
        assert len(decompose_query(query)) == 2


class TestConjunctionPatterns:
    """Test various conjunction patterns."""
    
    def test_and_pattern(self):
        """'X and Y' pattern should be detected."""
        query = "eligibility and enablement requirements"
        has_conj, pattern = has_conjunction_pattern(query)
        assert has_conj is True
    
    def test_both_and_pattern(self):
        """'both X and Y' pattern should be detected."""
        query = "both abstract and lacking enablement"
        has_conj, pattern = has_conjunction_pattern(query)
        assert has_conj is True
    
    def test_slash_pattern(self):
        """'X/Y' pattern should be detected."""
        query = "101/112 analysis"
        has_conj, pattern = has_conjunction_pattern(query)
        assert has_conj is True
    
    def test_as_well_as_pattern(self):
        """'X as well as Y' pattern should be detected."""
        query = "eligibility as well as enablement"
        has_conj, pattern = has_conjunction_pattern(query)
        assert has_conj is True


class TestSingleDoctrineNoTrigger:
    """Test that single-doctrine queries don't false-trigger."""
    
    def test_single_101(self):
        """Single 101 query should not decompose."""
        query = "What is the Alice two-step test for patent eligibility?"
        
        doctrines, _ = detect_doctrine_signals(query)
        assert len(doctrines) == 1
        assert should_decompose(query) is False
    
    def test_single_103(self):
        """Single 103 query should not decompose."""
        query = "What is the KSR obviousness standard?"
        
        doctrines, _ = detect_doctrine_signals(query)
        assert len(doctrines) == 1
        assert should_decompose(query) is False
    
    def test_single_112(self):
        """Single 112 query should not decompose."""
        query = "What are the Wands factors for enablement?"
        
        doctrines, _ = detect_doctrine_signals(query)
        assert len(doctrines) == 1
        assert should_decompose(query) is False


class TestDecompositionInfo:
    """Test diagnostic info for decomposition."""
    
    def test_full_info_multi_issue(self):
        """get_decomposition_info returns complete info for multi-issue."""
        query = "What are the requirements for patent eligibility under Alice 101 and written description under 112?"
        
        info = get_decomposition_info(query)
        
        assert info["should_decompose"] is True
        assert len(info["doctrines_detected"]) >= 2
        assert "101" in info["doctrines_detected"]
        assert "112" in info["doctrines_detected"]
        assert info["subquery_count"] == 2
        assert len(info["subqueries"]) == 2
    
    def test_full_info_single_issue(self):
        """get_decomposition_info returns complete info for single-issue."""
        query = "What is the Alice test?"
        
        info = get_decomposition_info(query)
        
        assert info["should_decompose"] is False
        assert len(info["doctrines_detected"]) == 1
        assert info["subquery_count"] == 0


class TestTriggerQueryFileRobustness:
    """Test all multi_issue queries from the trigger query file."""
    
    def test_all_multi_issue_queries_trigger(self):
        """All multi_issue category queries should trigger decomposition."""
        import json
        
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
            query = q["query"]
            query_id = q["id"]
            
            doctrines, evidence = detect_doctrine_signals(query)
            should_dec = should_decompose(query)
            subqueries = decompose_query(query)
            
            assert len(doctrines) >= 2, f"Query '{query_id}' should detect 2+ doctrines, got {doctrines}. Evidence: {evidence}"
            assert should_dec is True, f"Query '{query_id}' should decompose. Doctrines: {doctrines}"
            assert len(subqueries) >= 2, f"Query '{query_id}' should generate 2+ subqueries, got {len(subqueries)}: {subqueries}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
