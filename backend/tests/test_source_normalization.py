"""
Regression Test for Source Normalization

Tests that:
1. String sources are converted to proper dict sources
2. Dict sources get required fields filled in
3. Eval completes without exceptions when encountering edge cases
4. Resulting normalized source has tier == "unverified" for strings
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from backend.chat import normalize_source


class TestNormalizeSource:
    """Test suite for source normalization."""
    
    def test_string_fallback_converted_to_dict(self):
        """Strings should be converted to unverified dict sources."""
        result = normalize_source("This is a raw string source")
        
        assert isinstance(result, dict), "String should be converted to dict"
        assert result["tier"] == "unverified", "String source must be unverified"
        assert result["binding_method"] == "none", "String source binding_method must be 'none'"
        assert result["binding_failed"] == True, "String source must have binding_failed=True"
        assert "string_fallback" in result["signals"], "Must have string_fallback signal"
        assert result["text"] == "This is a raw string source", "Original text preserved"
        
        print("✓ TEST 1 PASSED: String fallback converted to dict")
    
    def test_dict_gets_required_fields(self):
        """Dict sources should get required fields filled in if missing."""
        result = normalize_source({
            "case_name": "Test Case",
            "quote": "Some quote"
        })
        
        assert isinstance(result, dict), "Should remain a dict"
        assert result["tier"] == "unverified", "Missing tier should default to unverified"
        assert result["binding_method"] == "none", "Missing binding_method should default to 'none'"
        assert "signals" in result, "Should have signals field"
        assert "score" in result, "Should have score field"
        assert result["case_name"] == "Test Case", "Original fields preserved"
        
        print("✓ TEST 2 PASSED: Dict gets required fields")
    
    def test_dict_preserves_existing_fields(self):
        """Dict sources should preserve existing tier/binding_method if present."""
        result = normalize_source({
            "case_name": "Test Case",
            "tier": "strong",
            "binding_method": "strict",
            "signals": ["case_bound", "exact_match"]
        })
        
        assert result["tier"] == "strong", "Existing tier should be preserved"
        assert result["binding_method"] == "strict", "Existing binding_method should be preserved"
        assert result["signals"] == ["case_bound", "exact_match"], "Existing signals preserved"
        
        print("✓ TEST 3 PASSED: Dict preserves existing fields")
    
    def test_invalid_type_raises(self):
        """Invalid types (not str or dict) should raise TypeError."""
        with pytest.raises(TypeError):
            normalize_source(123)
        
        with pytest.raises(TypeError):
            normalize_source(None)
        
        with pytest.raises(TypeError):
            normalize_source(["list", "of", "strings"])
        
        print("✓ TEST 4 PASSED: Invalid types raise TypeError")
    
    def test_no_keyerror_on_get_operations(self):
        """Normalized sources should never cause KeyError on .get() operations."""
        # Simulate the eval code pattern that was crashing
        source = normalize_source("Raw string that was causing crashes")
        
        # These are the operations that were failing in eval
        tier = source.get("tier", "unknown")
        binding_method = source.get("binding_method", "unknown")
        signals = source.get("signals", [])
        score = source.get("score", 0)
        
        assert tier == "unverified"
        assert binding_method == "none"
        assert isinstance(signals, list)
        assert isinstance(score, (int, float))
        
        print("✓ TEST 5 PASSED: No KeyError on .get() operations")


if __name__ == "__main__":
    test = TestNormalizeSource()
    test.test_string_fallback_converted_to_dict()
    test.test_dict_gets_required_fields()
    test.test_dict_preserves_existing_fields()
    test.test_no_keyerror_on_get_operations()
    print("\n✅ All normalize_source tests passed!")
