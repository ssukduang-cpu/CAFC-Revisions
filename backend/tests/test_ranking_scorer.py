#!/usr/bin/env python3
"""Unit tests for precedence-aware ranking scorer.

Tests:
1. Composite score arithmetic
2. Application signal components
3. Synthetic regression: "applies" outranks "mentions"
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ranking_scorer import (
    compute_authority_boost,
    compute_recency_factor,
    compute_gravity_factor,
    compute_holding_indicator,
    compute_analysis_depth,
    detect_framework_reference,
    compute_proximity_score,
    compute_application_signal,
    compute_composite_score,
    generate_application_reason,
    get_authority_type,
    AUTHORITY_BOOST
)


class TestAuthorityBoost:
    """Test authority_boost computation."""
    
    def test_scotus_boost(self):
        page = {"origin": "SCOTUS"}
        boost = compute_authority_boost(page)
        assert boost == 1.8, f"SCOTUS should have 1.8 boost, got {boost}"
    
    def test_cafc_en_banc_boost(self):
        page = {"origin": "CAFC", "is_en_banc": True}
        boost = compute_authority_boost(page)
        assert boost == 1.6, f"CAFC en banc should have 1.6 boost, got {boost}"
    
    def test_cafc_precedential_boost(self):
        page = {"origin": "CAFC", "is_precedential": True}
        boost = compute_authority_boost(page)
        assert boost == 1.3, f"CAFC precedential should have 1.3 boost, got {boost}"
    
    def test_nonprecedential_boost(self):
        page = {"origin": "CAFC", "is_precedential": False}
        boost = compute_authority_boost(page)
        assert boost == 0.8, f"Nonprecedential should have 0.8 boost, got {boost}"


class TestRecencyFactor:
    """Test recency_factor computation."""
    
    def test_recent_case_boost(self):
        page = {"release_date": "2025-01-15"}
        factor = compute_recency_factor(page)
        assert factor == 1.10, f"Recent case (2025) should have 1.10 factor, got {factor}"
    
    def test_old_case_penalty(self):
        page = {"release_date": "1990-05-01"}
        factor = compute_recency_factor(page)
        assert factor == 0.95, f"Old case (1990) should have 0.95 factor, got {factor}"
    
    def test_missing_date_default(self):
        page = {}
        factor = compute_recency_factor(page)
        assert factor == 1.0, f"Missing date should have 1.0 factor, got {factor}"


class TestGravityFactor:
    """Test gravity_factor computation."""
    
    def test_en_banc_gravity(self):
        page = {"is_en_banc": True}
        factor = compute_gravity_factor(page)
        assert factor >= 0.95, f"En banc should have high gravity, got {factor}"
    
    def test_landmark_gravity(self):
        page = {"is_landmark": True}
        factor = compute_gravity_factor(page)
        assert factor >= 0.90, f"Landmark should have high gravity, got {factor}"
    
    def test_default_gravity(self):
        page = {}
        factor = compute_gravity_factor(page)
        assert factor == 0.85, f"Default gravity should be 0.85, got {factor}"


class TestHoldingIndicator:
    """Test holding_indicator detection."""
    
    def test_strong_holding_we_hold(self):
        text = "For the foregoing reasons, we hold that the claims are patent-eligible."
        indicator = compute_holding_indicator(text)
        assert indicator == 2, f"'we hold' should be strong (2), got {indicator}"
    
    def test_strong_holding_we_conclude(self):
        text = "Therefore, we conclude that the district court erred."
        indicator = compute_holding_indicator(text)
        assert indicator == 2, f"'Therefore, we conclude' should be strong (2), got {indicator}"
    
    def test_moderate_holding_court_finds(self):
        text = "The court finds that the evidence supports the verdict."
        indicator = compute_holding_indicator(text)
        assert indicator == 1, f"'The court finds' should be moderate (1), got {indicator}"
    
    def test_no_holding_mention_only(self):
        text = "See Alice Corp. v. CLS Bank Int'l for the applicable standard."
        indicator = compute_holding_indicator(text)
        assert indicator == 0, f"Mere mention should be 0, got {indicator}"


class TestAnalysisDepth:
    """Test analysis_depth computation."""
    
    def test_long_text_higher_depth(self):
        long_text = "This case involves a complex analysis of patent eligibility. " * 100
        short_text = "See Alice."
        long_depth = compute_analysis_depth(long_text)
        short_depth = compute_analysis_depth(short_text)
        assert long_depth > short_depth, f"Long text should have higher depth: {long_depth} vs {short_depth}"
    
    def test_reasoning_words_boost(self):
        with_reasoning = "Because the claims are directed to an abstract idea, therefore we must analyze step two."
        without_reasoning = "The claims are directed to an abstract idea."
        with_depth = compute_analysis_depth(with_reasoning)
        without_depth = compute_analysis_depth(without_reasoning)
        assert with_depth >= without_depth, f"Reasoning words should boost depth"


class TestFrameworkReference:
    """Test framework_reference detection."""
    
    def test_alice_detected(self):
        text = "Applying Alice step two, we examine whether the claims contain an inventive concept."
        ref, frameworks = detect_framework_reference(text)
        assert ref == 1, f"Alice framework should be detected, got {ref}"
        assert "Alice" in frameworks, f"Alice should be in frameworks list"
    
    def test_multiple_frameworks(self):
        text = "Under KSR and applying Mayo/Alice, the combination lacks inventive concept."
        ref, frameworks = detect_framework_reference(text)
        assert ref == 1, f"Frameworks should be detected"
        assert len(frameworks) >= 2, f"Multiple frameworks should be detected: {frameworks}"
    
    def test_no_framework(self):
        text = "The plaintiff brought suit alleging infringement."
        ref, frameworks = detect_framework_reference(text)
        assert ref == 0, f"No framework should be detected, got {ref}"
        assert len(frameworks) == 0, f"No frameworks should be in list"


class TestProximityScore:
    """Test proximity_score computation."""
    
    def test_close_proximity(self):
        text = "Applying Alice, we hold that the claims are abstract."
        score = compute_proximity_score(text)
        assert score >= 0.7, f"Close proximity should have high score, got {score}"
    
    def test_far_proximity(self):
        text = "The district court discussed the Alice framework in detail." + " " * 2000 + "We affirm."
        score = compute_proximity_score(text)
        assert score < 0.5, f"Far proximity should have lower score, got {score}"


class TestApplicationSignal:
    """Test full application_signal computation."""
    
    def test_applies_case_high_signal(self):
        text = """
        Applying the two-step Alice framework, we hold that the claims are patent-eligible.
        Under step one, we examine whether the claims are directed to an abstract idea.
        Because the claims recite a specific technological improvement, they pass step one.
        Therefore, we conclude that the claims are not abstract under Alice step one.
        """
        result = compute_application_signal(text)
        signal = result["application_signal"]
        assert signal >= 2.0, f"Application case should have high signal >= 2.0, got {signal}"
    
    def test_mentions_case_low_signal(self):
        text = "See Alice Corp. v. CLS Bank Int'l, 573 U.S. 208 (2014)."
        result = compute_application_signal(text)
        signal = result["application_signal"]
        assert signal < 1.5, f"Mention-only case should have low signal < 1.5, got {signal}"


class TestCompositeScore:
    """Test composite_score computation."""
    
    def test_scotus_boosted(self):
        cafc_page = {"origin": "CAFC", "release_date": "2020-01-01"}
        scotus_page = {"origin": "SCOTUS", "release_date": "2020-01-01"}
        text = "Some legal text here."
        
        cafc_result = compute_composite_score(0.5, cafc_page, text)
        scotus_result = compute_composite_score(0.5, scotus_page, text)
        
        assert scotus_result["composite_score"] > cafc_result["composite_score"], \
            f"SCOTUS should rank higher: {scotus_result['composite_score']} vs {cafc_result['composite_score']}"
    
    def test_explain_contains_all_factors(self):
        page = {"origin": "CAFC", "release_date": "2022-01-01"}
        result = compute_composite_score(0.5, page, "Some text.")
        
        assert "relevance_score" in result
        assert "authority_boost" in result
        assert "gravity_factor" in result
        assert "recency_factor" in result
        assert "application_signal" in result
        assert "composite_score" in result
        assert "application_breakdown" in result


class TestSyntheticRegression:
    """Synthetic regression test: 'applies' must outrank 'mentions'."""
    
    def test_applies_outranks_mentions(self):
        """
        Doc A: Deep application with holding language
        Doc B: Mention-only reference
        Query: "Alice step two inventive concept"
        
        REQUIREMENT: Doc A must rank higher than Doc B.
        """
        doc_a_text = """
        FEDERAL CIRCUIT COURT OF APPEALS
        
        Applying the Supreme Court's two-step Alice framework, we hold that
        the claims at issue are not directed to an abstract idea under step one.
        At step two, we examine whether the claims contain an inventive concept.
        Because the claims recite specific technical improvements to computer
        functionality, we conclude that they satisfy the inventive concept
        requirement. The claims are therefore patent-eligible under 35 U.S.C. § 101.
        
        For the foregoing reasons, we reverse the district court's judgment.
        """
        
        doc_b_text = """
        The plaintiff cites Alice Corp. v. CLS Bank Int'l for the proposition
        that software patents may be abstract. See also Mayo Collaborative
        Services v. Prometheus Laboratories, Inc. The defendant disagrees.
        """
        
        page_a = {"origin": "CAFC", "release_date": "2022-01-01", "is_precedential": True}
        page_b = {"origin": "CAFC", "release_date": "2022-01-01", "is_precedential": True}
        
        result_a = compute_composite_score(0.6, page_a, doc_a_text)
        result_b = compute_composite_score(0.6, page_b, doc_b_text)
        
        score_a = result_a["composite_score"]
        score_b = result_b["composite_score"]
        
        print(f"\n{'='*60}")
        print("SYNTHETIC REGRESSION TEST: applies vs mentions")
        print(f"{'='*60}")
        print(f"Doc A (applies): composite_score = {score_a:.4f}")
        print(f"  - application_signal = {result_a['application_signal']}")
        print(f"  - holding_indicator = {result_a['application_breakdown']['holding_indicator']}")
        print(f"  - frameworks = {result_a['application_breakdown']['frameworks_detected']}")
        print(f"\nDoc B (mentions): composite_score = {score_b:.4f}")
        print(f"  - application_signal = {result_b['application_signal']}")
        print(f"  - holding_indicator = {result_b['application_breakdown']['holding_indicator']}")
        print(f"  - frameworks = {result_b['application_breakdown']['frameworks_detected']}")
        print(f"\nRESULT: Doc A ({score_a:.4f}) {'>' if score_a > score_b else '<'} Doc B ({score_b:.4f})")
        print(f"{'='*60}")
        
        assert score_a > score_b, \
            f"FAILED: 'applies' doc ({score_a}) should rank higher than 'mentions' doc ({score_b})"


class TestApplicationReason:
    """Test 'Why this case?' reason generation."""
    
    def test_scotus_reason(self):
        explain = {"authority_type": "SCOTUS", "application_breakdown": {"holding_indicator": 2, "frameworks_detected": ["Alice"]}}
        page = {"case_name": "Alice Corp. v. CLS Bank"}
        reason = generate_application_reason(explain, page)
        assert "Supreme Court" in reason, f"Should mention Supreme Court: {reason}"
    
    def test_holding_reason(self):
        explain = {"authority_type": "CAFC_precedential", "application_breakdown": {"holding_indicator": 2, "frameworks_detected": []}}
        page = {}
        reason = generate_application_reason(explain, page)
        assert "holding" in reason.lower(), f"Should mention holding: {reason}"


def run_all_tests():
    """Run all tests and report results."""
    print("=" * 60)
    print("RANKING SCORER UNIT TEST SUITE")
    print("=" * 60)
    
    test_classes = [
        TestAuthorityBoost,
        TestRecencyFactor,
        TestGravityFactor,
        TestHoldingIndicator,
        TestAnalysisDepth,
        TestFrameworkReference,
        TestProximityScore,
        TestApplicationSignal,
        TestCompositeScore,
        TestSyntheticRegression,
        TestApplicationReason
    ]
    
    total_passed = 0
    total_failed = 0
    
    for test_class in test_classes:
        print(f"\n{test_class.__name__}:")
        instance = test_class()
        for method_name in dir(instance):
            if method_name.startswith("test_"):
                try:
                    getattr(instance, method_name)()
                    print(f"  ✓ {method_name}")
                    total_passed += 1
                except AssertionError as e:
                    print(f"  ✗ {method_name}: {e}")
                    total_failed += 1
                except Exception as e:
                    print(f"  ✗ {method_name}: Exception - {e}")
                    total_failed += 1
    
    print("\n" + "=" * 60)
    if total_failed == 0:
        print(f"ALL {total_passed} TESTS PASSED")
    else:
        print(f"PASSED: {total_passed}, FAILED: {total_failed}")
    print("=" * 60)
    
    return total_failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
