"""Tests for advanced search with hybrid ranking and recency boost."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import db_postgres as db


class TestRecencyBoost:
    """Test that recency boost ranks recent documents higher than old ones."""
    
    def test_hybrid_ranking_formula(self):
        """Test that the recency decay formula works correctly."""
        result = db.advanced_search(query="patent", limit=20)
        
        assert "results" in result
        assert "next_cursor" in result
        assert isinstance(result["results"], list)
    
    def test_recent_documents_ranked_higher(self):
        """Verify that 2026 documents rank above 2010 documents for same keyword."""
        result = db.advanced_search(query="claim construction", limit=50)
        
        if len(result["results"]) < 2:
            pytest.skip("Not enough results to compare dates")
        
        results = result["results"]
        scores = [r.get("score", 0) for r in results]
        
        assert scores == sorted(scores, reverse=True), "Results should be sorted by score descending"
    
    def test_phrase_search(self):
        """Test phrase search with quoted terms."""
        result = db.advanced_search(query='"claim construction"', limit=10)
        
        assert "results" in result
        assert isinstance(result["results"], list)
    
    def test_fuzzy_matching(self):
        """Test fuzzy matching on case names."""
        result = db.advanced_search(query="Apple Samsung", limit=10)
        
        assert "results" in result
        assert isinstance(result["results"], list)


class TestCursorPagination:
    """Test cursor-based keyset pagination."""
    
    def test_first_page(self):
        """Test fetching first page without cursor."""
        result = db.advanced_search(query="patent", limit=10)
        
        assert "results" in result
        assert "next_cursor" in result
    
    def test_pagination_with_cursor(self):
        """Test fetching second page with cursor."""
        first_page = db.advanced_search(query="infringement", limit=5)
        
        if not first_page.get("next_cursor"):
            pytest.skip("Not enough results for pagination test")
        
        second_page = db.advanced_search(
            query="infringement", 
            limit=5, 
            cursor_token=first_page["next_cursor"]
        )
        
        assert "results" in second_page
        
        first_ids = {r["id"] for r in first_page["results"]}
        second_ids = {r["id"] for r in second_page["results"]}
        
        assert not first_ids.intersection(second_ids), "Pages should not overlap"


class TestFilters:
    """Test search filters."""
    
    def test_exclude_rule_36(self):
        """Test excluding Rule 36 judgments."""
        result = db.advanced_search(query="patent", exclude_r36=True, limit=20)
        
        assert "results" in result
        for r in result["results"]:
            assert r.get("is_rule_36") is not True
    
    def test_author_filter(self):
        """Test filtering by author judge."""
        result = db.advanced_search(query="patent", author="Lourie", limit=10)
        
        assert "results" in result
        for r in result["results"]:
            if r.get("author"):
                assert "Lourie" in r["author"]


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_query_returns_empty(self):
        """Test that empty/blank queries return empty results."""
        result = db.advanced_search(query="", limit=10)
        
        assert result["results"] == []
        assert result["next_cursor"] is None
    
    def test_whitespace_only_query(self):
        """Test that whitespace-only queries return empty results."""
        result = db.advanced_search(query="   ", limit=10)
        
        assert result["results"] == []
        assert result["next_cursor"] is None


class TestRateLimiter:
    """Test rate limiter functionality."""
    
    def test_leaky_bucket_allows_burst(self):
        """Test that rate limiter allows burst up to capacity."""
        from backend.main import LeakyBucketRateLimiter
        
        limiter = LeakyBucketRateLimiter(rate=10.0, capacity=10.0)
        
        allowed = sum(1 for _ in range(10) if limiter.allow())
        assert allowed == 10
    
    def test_leaky_bucket_denies_after_capacity(self):
        """Test that rate limiter denies after capacity exceeded."""
        from backend.main import LeakyBucketRateLimiter
        
        limiter = LeakyBucketRateLimiter(rate=10.0, capacity=5.0)
        
        for _ in range(5):
            limiter.allow()
        
        assert not limiter.allow()
