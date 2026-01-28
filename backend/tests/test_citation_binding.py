"""
Regression Test Suite for Citation Case-Quote Binding (PR #5)

Tests the P0 case-quote binding implementation to ensure:
1. Misattribution is detected and prevented (DDR/Recognicorp-style)
2. Quotes are only verified when bound to the claimed case
3. Fuzzy fallback works but caps at MODERATE
4. Failed bindings result in UNVERIFIED, not silent substitution

Test Cases:
1. Misattribution regression - quote from Case A attributed to Case B → UNVERIFIED
2. Exact match - correct quote + correct opinion_id → STRONG/MODERATE
3. Wrong case - quote exists but in different opinion → UNVERIFIED
4. Missing quote - quote doesn't exist anywhere → UNVERIFIED
5. Fuzzy fallback - missing opinion_id, case name matches → MODERATE max with signal
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.chat import (
    build_sources_from_markers,
    verify_quote_strict,
    verify_quote_with_case_binding,
    verify_quote_with_fuzzy_fallback,
    normalize_case_name_for_binding,
    compute_citation_tier,
    detect_section_type_heuristic
)


# Test data: Two distinct cases with different content
CASE_A = {
    "opinion_id": "case-a-uuid-1234",
    "case_name": "Alice Corp. v. CLS Bank International",
    "appeal_no": "13-298",
    "release_date": "2014-06-19",
    "page_number": 5,
    "text": "We hold that the claims at issue are drawn to the abstract idea of intermediated settlement, and that merely requiring generic computer implementation fails to transform that abstract idea into a patent-eligible invention.",
    "pdf_url": "",
    "courtlistener_url": ""
}

CASE_B = {
    "opinion_id": "case-b-uuid-5678",
    "case_name": "DDR Holdings, LLC v. Hotels.com, L.P.",
    "appeal_no": "13-1505",
    "release_date": "2014-12-05",
    "page_number": 12,
    "text": "Unlike the claims in Alice, the claims here specify how interactions with the Internet are manipulated to yield a desired result—a result that overrides the routine and conventional sequence of events ordinarily triggered by the click of a hyperlink.",
    "pdf_url": "",
    "courtlistener_url": ""
}

PAGES = [CASE_A, CASE_B]


class TestCitationBinding:
    """Test suite for case-quote binding functionality."""
    
    def test_1_misattribution_regression(self):
        """
        TEST 1: Misattribution Regression (DDR/Recognicorp-style)
        
        Scenario: Quote from DDR Holdings (Case B) is attributed to Alice Corp (Case A)
        Expected: Binding must FAIL, citation marked UNVERIFIED
        
        This is the critical P0 test - prevents the misattribution bug.
        """
        # Quote is from Case B (DDR Holdings)
        quote_from_case_b = "Unlike the claims in Alice, the claims here specify how interactions with the Internet are manipulated"
        
        # But LLM attributed it to Case A (Alice Corp)
        markers = [{
            "quote": quote_from_case_b,
            "opinion_id": CASE_A["opinion_id"],  # WRONG - this is Alice's ID
            "case_name": "Alice Corp. v. CLS Bank",
            "page_number": 5,
            "position": 0,
            "citation_num": 1
        }]
        
        sources, _ = build_sources_from_markers(markers, PAGES)
        
        assert len(sources) == 1, "Should still create a source entry (marked unverified)"
        source = sources[0]
        
        # Critical assertions
        assert source["tier"] == "unverified", f"Misattributed citation must be UNVERIFIED, got: {source['tier']}"
        assert "binding_failed" in source["signals"], f"Must have 'binding_failed' signal, got: {source['signals']}"
        assert source["binding_method"] == "failed", f"Binding method must be 'failed', got: {source['binding_method']}"
        
        print("✓ TEST 1 PASSED: Misattribution detected and marked UNVERIFIED")
    
    def test_2_exact_match_correct_case(self):
        """
        TEST 2: Exact Match with Correct Case
        
        Scenario: Quote from Alice Corp correctly attributed to Alice Corp
        Expected: Binding succeeds, tier is STRONG or MODERATE
        """
        # Quote from Case A
        quote_from_case_a = "We hold that the claims at issue are drawn to the abstract idea of intermediated settlement"
        
        # Correctly attributed to Case A
        markers = [{
            "quote": quote_from_case_a,
            "opinion_id": CASE_A["opinion_id"],
            "case_name": "Alice Corp. v. CLS Bank",
            "page_number": 5,
            "position": 0,
            "citation_num": 1
        }]
        
        sources, _ = build_sources_from_markers(markers, PAGES)
        
        assert len(sources) == 1, "Should create one source"
        source = sources[0]
        
        # Critical assertions
        assert source["tier"] in ["strong", "moderate"], f"Correct binding should be STRONG or MODERATE, got: {source['tier']}"
        assert source["binding_method"] == "strict", f"Should use strict binding, got: {source['binding_method']}"
        assert "case_bound" in source["signals"], f"Must have 'case_bound' signal, got: {source['signals']}"
        assert "exact_match" in source["signals"], f"Must have 'exact_match' signal, got: {source['signals']}"
        assert source["opinion_id"] == CASE_A["opinion_id"], "Opinion ID must match claimed case"
        
        print("✓ TEST 2 PASSED: Exact match correctly bound and verified")
    
    def test_3_wrong_case_quote_exists_elsewhere(self):
        """
        TEST 3: Quote Exists in Corpus But Not in Claimed Case
        
        Scenario: Quote from DDR Holdings attributed to Alice Corp
        Expected: UNVERIFIED (same as test 1, but explicit about existence check)
        """
        # Quote from Case B (DDR Holdings)
        quote_from_case_b = "a result that overrides the routine and conventional sequence of events"
        
        # Attributed to Case A (Alice Corp) - WRONG
        markers = [{
            "quote": quote_from_case_b,
            "opinion_id": CASE_A["opinion_id"],
            "case_name": "Alice Corp. v. CLS Bank",
            "page_number": 5,
            "position": 0,
            "citation_num": 1
        }]
        
        sources, _ = build_sources_from_markers(markers, PAGES)
        
        assert len(sources) == 1, "Should create source entry (unverified)"
        source = sources[0]
        
        # Quote exists in corpus (Case B) but binding to Case A must fail
        assert source["tier"] == "unverified", f"Must be UNVERIFIED when quote is in wrong case, got: {source['tier']}"
        assert "binding_failed" in source["signals"], f"Must have 'binding_failed' signal"
        
        print("✓ TEST 3 PASSED: Quote in wrong case correctly marked UNVERIFIED")
    
    def test_4_missing_quote_not_in_corpus(self):
        """
        TEST 4: Quote Doesn't Exist Anywhere in Corpus
        
        Scenario: Fabricated/hallucinated quote attributed to Alice Corp
        Expected: UNVERIFIED
        """
        # Fabricated quote that doesn't exist
        fabricated_quote = "The court hereby declares that software patents are categorically invalid under Section 101"
        
        markers = [{
            "quote": fabricated_quote,
            "opinion_id": CASE_A["opinion_id"],
            "case_name": "Alice Corp. v. CLS Bank",
            "page_number": 5,
            "position": 0,
            "citation_num": 1
        }]
        
        sources, _ = build_sources_from_markers(markers, PAGES)
        
        assert len(sources) == 1, "Should create source entry (unverified)"
        source = sources[0]
        
        assert source["tier"] == "unverified", f"Fabricated quote must be UNVERIFIED, got: {source['tier']}"
        assert "binding_failed" in source["signals"], f"Must have 'binding_failed' signal"
        
        print("✓ TEST 4 PASSED: Non-existent quote correctly marked UNVERIFIED")
    
    def test_5_fuzzy_fallback_no_opinion_id(self):
        """
        TEST 5: Fuzzy Case-Name Binding (when opinion_id is missing)
        
        Scenario: Quote from DDR Holdings, opinion_id missing, but case name provided
        Expected: Binding via fuzzy case name, tier capped at MODERATE
        """
        quote_from_case_b = "Unlike the claims in Alice, the claims here specify how interactions with the Internet are manipulated"
        
        # No opinion_id, only case_name
        markers = [{
            "quote": quote_from_case_b,
            "opinion_id": "",  # Missing!
            "case_name": "DDR Holdings v. Hotels.com",  # Slightly different format
            "page_number": 12,
            "position": 0,
            "citation_num": 1
        }]
        
        sources, _ = build_sources_from_markers(markers, PAGES)
        
        assert len(sources) == 1, "Should create one source via fuzzy binding"
        source = sources[0]
        
        # Critical assertions for fuzzy binding
        assert source["binding_method"] == "fuzzy", f"Should use fuzzy binding, got: {source['binding_method']}"
        assert "fuzzy_case_binding" in source["signals"], f"Must have 'fuzzy_case_binding' signal, got: {source['signals']}"
        assert source["tier"] in ["moderate", "weak"], f"Fuzzy binding must cap at MODERATE, got: {source['tier']}"
        assert source["tier"] != "strong", "Fuzzy binding must NOT be STRONG"
        
        print("✓ TEST 5 PASSED: Fuzzy fallback works and caps at MODERATE")


class TestHelperFunctions:
    """Test helper functions for binding and normalization."""
    
    def test_normalize_case_name(self):
        """Test case name normalization for fuzzy matching."""
        assert normalize_case_name_for_binding("Google LLC v. Oracle America, Inc.") == "google oracle america"
        assert normalize_case_name_for_binding("Alice Corp. v. CLS Bank International") == "alice cls bank international"
        assert normalize_case_name_for_binding("DDR Holdings, LLC vs. Hotels.com, L.P.") == "ddr holdings hotels com l p"
    
    def test_verify_quote_strict(self):
        """Test strict quote verification."""
        page_text = "This is a sample opinion text with some legal analysis."
        
        # Exact match
        assert verify_quote_strict("sample opinion text with some legal", page_text) == True
        
        # Too short
        assert verify_quote_strict("short", page_text) == False
        
        # Not in text
        assert verify_quote_strict("this text is not present in the opinion at all", page_text) == False
    
    def test_compute_citation_tier_strict(self):
        """Test tier computation with strict binding."""
        signals = ["case_bound", "exact_match"]
        page = {"release_date": "2023-01-15"}
        
        tier, score = compute_citation_tier("strict", signals.copy(), page)
        
        assert tier == "strong", f"Strict binding with exact match should be STRONG, got: {tier}"
        assert score >= 70, f"Score should be >= 70, got: {score}"
    
    def test_compute_citation_tier_fuzzy_capped(self):
        """Test that fuzzy binding caps at MODERATE."""
        signals = ["fuzzy_case_binding", "exact_match", "recent"]
        page = {"release_date": "2024-06-01"}
        
        tier, score = compute_citation_tier("fuzzy", signals.copy(), page)
        
        assert tier == "moderate", f"Fuzzy binding must cap at MODERATE, got: {tier}"
        assert score <= 69, f"Score should be capped at 69 for MODERATE, got: {score}"


class TestHeuristicDetection:
    """Test holding/dicta/concurrence/dissent heuristics."""
    
    def test_detect_holding(self):
        """Test detection of holding language."""
        page_text = "For the foregoing reasons, we hold that the district court erred. We reverse the judgment."
        quote = "the district court erred"
        
        section_type, signals = detect_section_type_heuristic(page_text, quote)
        
        assert section_type == "holding", f"Should detect holding, got: {section_type}"
        assert "holding_heuristic" in signals, f"Should have holding_heuristic signal"
    
    def test_detect_dicta(self):
        """Test detection of dicta language."""
        page_text = "We note that even if the appellant had properly preserved this argument, we would reach the same conclusion."
        quote = "properly preserved this argument"
        
        section_type, signals = detect_section_type_heuristic(page_text, quote)
        
        assert section_type == "dicta", f"Should detect dicta, got: {section_type}"
        assert "dicta_heuristic" in signals, f"Should have dicta_heuristic signal"
    
    def test_detect_dissent(self):
        """Test detection of dissent language."""
        page_text = "I respectfully dissent. The majority errs in its interpretation of the statute."
        quote = "its interpretation of the statute"
        
        section_type, signals = detect_section_type_heuristic(page_text, quote)
        
        assert section_type == "dissent", f"Should detect dissent, got: {section_type}"
        assert "dissent_heuristic" in signals, f"Should have dissent_heuristic signal"
    
    def test_detect_concurrence(self):
        """Test detection of concurrence language."""
        page_text = "I concur in the result. While I agree with the majority's conclusion, I write separately to emphasize an additional point."
        quote = "the majority's conclusion"
        
        section_type, signals = detect_section_type_heuristic(page_text, quote)
        
        assert section_type == "concurrence", f"Should detect concurrence, got: {section_type}"
        assert "concurrence_heuristic" in signals, f"Should have concurrence_heuristic signal"


def run_all_tests():
    """Run all test cases and report results."""
    print("=" * 60)
    print("CITATION BINDING REGRESSION TEST SUITE")
    print("=" * 60)
    print()
    
    # Citation binding tests
    binding_tests = TestCitationBinding()
    binding_tests.test_1_misattribution_regression()
    binding_tests.test_2_exact_match_correct_case()
    binding_tests.test_3_wrong_case_quote_exists_elsewhere()
    binding_tests.test_4_missing_quote_not_in_corpus()
    binding_tests.test_5_fuzzy_fallback_no_opinion_id()
    
    print()
    
    # Helper function tests
    helper_tests = TestHelperFunctions()
    helper_tests.test_normalize_case_name()
    print("✓ TEST 6 PASSED: Case name normalization works")
    helper_tests.test_verify_quote_strict()
    print("✓ TEST 7 PASSED: Strict quote verification works")
    helper_tests.test_compute_citation_tier_strict()
    print("✓ TEST 8 PASSED: Tier computation (strict) works")
    helper_tests.test_compute_citation_tier_fuzzy_capped()
    print("✓ TEST 9 PASSED: Tier computation (fuzzy cap) works")
    
    print()
    
    # Heuristic detection tests
    heuristic_tests = TestHeuristicDetection()
    heuristic_tests.test_detect_holding()
    print("✓ TEST 10 PASSED: Holding detection works")
    heuristic_tests.test_detect_dicta()
    print("✓ TEST 11 PASSED: Dicta detection works")
    heuristic_tests.test_detect_dissent()
    print("✓ TEST 12 PASSED: Dissent detection works")
    heuristic_tests.test_detect_concurrence()
    print("✓ TEST 13 PASSED: Concurrence detection works")
    
    print()
    print("=" * 60)
    print("ALL 13 TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
