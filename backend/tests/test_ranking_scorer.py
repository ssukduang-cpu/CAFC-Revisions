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
    get_authority_type_with_signal,
    normalize_origin,
    normalize_origin_with_signal,
    compute_framework_boost,
    classify_doctrine_tag,
    get_controlling_framework_candidates,
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
    """Test full application_signal computation with [0.8, 1.5] cap."""
    
    def test_deep_application_capped_at_1_5(self):
        """P0 Test 1: Deep application chunk must return <= 1.5"""
        text = """
        FEDERAL CIRCUIT COURT OF APPEALS
        Applying the Supreme Court's two-step Alice framework, we hold that
        the claims at issue are not directed to an abstract idea under step one.
        At step two, we examine whether the claims contain an inventive concept.
        Because the claims recite specific technical improvements to computer
        functionality, we conclude that they satisfy the inventive concept.
        For the foregoing reasons, we reverse the district court's judgment.
        Therefore, under Alice and Mayo, we hold these claims are patent-eligible.
        """
        result = compute_application_signal(text)
        signal = result["application_signal"]
        assert signal <= 1.5, f"Deep application signal must be <= 1.5, got {signal}"
        assert signal >= 1.3, f"Deep application should have high signal >= 1.3, got {signal}"
    
    def test_mention_only_near_baseline(self):
        """P0 Test 2: Mention-only chunk returns near baseline (~1.0)"""
        text = """
        The plaintiff argues that the claims are similar to those in Alice Corp.
        v. CLS Bank Int'l, 573 U.S. 208 (2014) and Mayo Collaborative Services.
        The defendant disputes this characterization of the prior art.
        """
        result = compute_application_signal(text)
        signal = result["application_signal"]
        assert 0.9 <= signal <= 1.2, f"Mention-only should be near baseline (0.9-1.2), got {signal}"
    
    def test_no_doctrine_penalized(self):
        """P0 Test 3: No doctrine chunk returns <= 1.0 (penalized or baseline)"""
        text = "The plaintiff brought suit alleging patent infringement. The defendant filed a motion to dismiss."
        result = compute_application_signal(text)
        signal = result["application_signal"]
        assert signal <= 1.0, f"No-doctrine chunk must be <= 1.0, got {signal}"
        assert signal >= 0.8, f"No-doctrine chunk must be >= 0.8 (floor), got {signal}"
    
    def test_signal_never_exceeds_cap(self):
        """Verify no result can exceed 1.5 application_signal."""
        extreme_text = """
        We hold that Alice applies. We conclude under Mayo. Therefore we reverse.
        For the foregoing reasons, we affirm under KSR. The court finds under Teva.
        Applying Markman analysis, we hold the claims are construed narrowly.
        Because the analysis shows, therefore we determine, thus we agree.
        """ * 10  # Repeat to maximize all components
        result = compute_application_signal(extreme_text)
        signal = result["application_signal"]
        assert signal <= 1.5, f"Signal must NEVER exceed 1.5, got {signal}"


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


class TestOriginNormalization:
    """Test origin normalization (P0.3) - metadata-first with signal tracking."""
    
    def test_scotus_origin_takes_priority(self):
        """If origin=SCOTUS, court=SCOTUS regardless of case name."""
        court, signal = normalize_origin_with_signal("SCOTUS", "Random Case Name")
        assert court == "SCOTUS", f"SCOTUS origin should yield SCOTUS, got {court}"
        assert signal is None, f"No signal expected for direct origin match, got {signal}"
    
    def test_scotus_from_casename_when_origin_missing(self):
        """If origin is missing but case-name matches -> SCOTUS + signal."""
        court, signal = normalize_origin_with_signal("", "KSR International Co. v. Teleflex Inc.")
        assert court == "SCOTUS", f"KSR case name should yield SCOTUS, got {court}"
        assert signal == "court_inferred_from_name", f"Should have inference signal, got {signal}"
    
    def test_unknown_origin_unknown_casename_yields_unknown(self):
        """If origin missing and case-name not matching -> court=UNKNOWN (not CAFC)."""
        court, signal = normalize_origin_with_signal("", "Random Unknown Case v. Something")
        assert court == "UNKNOWN", f"Unknown origin + non-matching case should yield UNKNOWN, got {court}"
        assert signal is None, f"No signal expected for UNKNOWN, got {signal}"
    
    def test_courtlistener_with_scotus_casename(self):
        """If origin is courtlistener_api but case is Alice -> SCOTUS + signal."""
        court, signal = normalize_origin_with_signal("courtlistener_api", "Alice Corp. v. CLS Bank")
        assert court == "SCOTUS", f"Alice case name should yield SCOTUS, got {court}"
        assert signal == "court_inferred_from_name", f"Should have inference signal, got {signal}"
    
    def test_courtlistener_normalizes_to_cafc(self):
        """If origin is courtlistener_api and case is not SCOTUS -> CAFC (no signal)."""
        court, signal = normalize_origin_with_signal("courtlistener_api", "Some CAFC Case v. Another")
        assert court == "CAFC", f"courtlistener_api should normalize to CAFC, got {court}"
        assert signal is None, f"No signal expected for CAFC normalization, got {signal}"
    
    def test_ptab_stays_ptab(self):
        court, signal = normalize_origin_with_signal("PTAB", "Some PTAB Case")
        assert court == "PTAB", f"PTAB should stay PTAB, got {court}"
        assert signal is None, f"No signal expected for PTAB, got {signal}"
    
    def test_backward_compat_normalize_origin(self):
        """Backward-compatible wrapper returns just court label."""
        result = normalize_origin("SCOTUS", "")
        assert result == "SCOTUS"


class TestDoctrineClassification:
    """Test doctrine_tag classification for query routing."""
    
    def test_101_classification(self):
        tag = classify_doctrine_tag("How does Alice step two work for inventive concept?")
        assert tag == "101", f"Alice query should classify as 101, got {tag}"
    
    def test_103_classification(self):
        tag = classify_doctrine_tag("What is obviousness under KSR?")
        assert tag == "103", f"KSR query should classify as 103, got {tag}"
    
    def test_112_classification(self):
        tag = classify_doctrine_tag("What does Amgen require for enablement?")
        assert tag == "112", f"Amgen/enablement query should classify as 112, got {tag}"
    
    def test_claim_construction_classification(self):
        tag = classify_doctrine_tag("What are the rules for claim construction under Markman?")
        assert tag == "claim_construction", f"Markman query should classify as claim_construction, got {tag}"
    
    def test_remedies_classification(self):
        tag = classify_doctrine_tag("What are the eBay factors for injunctions?")
        assert tag == "remedies", f"eBay query should classify as remedies, got {tag}"


class TestControllingCandidates:
    """Test get_controlling_framework_candidates for candidate injection."""
    
    def test_101_candidates(self):
        candidates = get_controlling_framework_candidates("101")
        assert "Alice Corp. v. CLS Bank" in candidates, f"Should include Alice, got {candidates}"
        assert "Mayo Collaborative Services v. Prometheus" in candidates, f"Should include Mayo, got {candidates}"
    
    def test_103_candidates(self):
        candidates = get_controlling_framework_candidates("103")
        assert "KSR International Co. v. Teleflex Inc." in candidates, f"Should include KSR, got {candidates}"
    
    def test_none_doctrine_returns_empty(self):
        candidates = get_controlling_framework_candidates(None)
        assert candidates == [], f"None doctrine should return empty list, got {candidates}"


class TestFrameworkBoost:
    """Test framework_boost for controlling authorities (P1.4)."""
    
    def test_alice_gets_boost(self):
        boost = compute_framework_boost("Alice Corp. v. CLS Bank", ["Alice"])
        assert boost == 1.25, f"Alice should get 1.25 boost, got {boost}"
    
    def test_ksr_gets_boost(self):
        boost = compute_framework_boost("KSR International Co. v. Teleflex Inc.", ["KSR"])
        assert boost == 1.25, f"KSR should get 1.25 boost, got {boost}"
    
    def test_markman_gets_boost(self):
        boost = compute_framework_boost("Markman v. Westview Instruments, Inc.", [])
        assert boost == 1.25, f"Markman should get 1.25 boost, got {boost}"
    
    def test_ebay_gets_boost(self):
        boost = compute_framework_boost("eBay Inc. v. MercExchange", ["eBay"])
        assert boost == 1.25, f"eBay should get 1.25 boost, got {boost}"
    
    def test_non_controlling_no_boost(self):
        boost = compute_framework_boost("Some Random v. Case", [])
        assert boost == 1.0, f"Non-controlling case should have 1.0 boost, got {boost}"


class TestConsistency:
    """Test court/authority_type/authority_boost consistency (P0.3)."""
    
    def test_scotus_consistency(self):
        page = {"origin": "SCOTUS", "case_name": "Alice Corp. v. CLS Bank"}
        auth_type = get_authority_type(page)
        boost = compute_authority_boost(page)
        assert auth_type == "SCOTUS", f"Authority type should be SCOTUS, got {auth_type}"
        assert boost == 1.8, f"SCOTUS should have 1.8 boost, got {boost}"
    
    def test_scotus_from_casename_consistency(self):
        page = {"origin": "courtlistener_api", "case_name": "KSR International Co. v. Teleflex Inc."}
        auth_type = get_authority_type(page)
        boost = compute_authority_boost(page)
        assert auth_type == "SCOTUS", f"KSR authority type should be SCOTUS, got {auth_type}"
        assert boost == 1.8, f"KSR should have 1.8 boost, got {boost}"
    
    def test_cafc_consistency(self):
        page = {"origin": "CAFC", "is_precedential": True}
        auth_type = get_authority_type(page)
        boost = compute_authority_boost(page)
        assert auth_type == "CAFC_precedential", f"Authority type should be CAFC_precedential, got {auth_type}"
        assert boost == 1.3, f"CAFC precedential should have 1.3 boost, got {boost}"


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
        TestApplicationReason,
        TestOriginNormalization,
        TestDoctrineClassification,
        TestControllingCandidates,
        TestFrameworkBoost,
        TestConsistency
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
