"""
Unit tests for parse_replay_packet helper.

Run with: python -m pytest tests/test_parse_replay_packet.py -v
"""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.smart.parse_replay_packet import (
    is_verified_tier,
    parse_citations_manifest,
    parse_retrieval_manifest,
    parse_model_config,
    normalize_replay_packet,
    extract_metrics_from_response,
    VERIFICATION_TIERS,
    VERIFIED_TIERS
)


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "smart", "fixtures")


def load_fixture(name: str) -> dict:
    """Load a fixture file."""
    path = os.path.join(FIXTURES_DIR, name)
    with open(path) as f:
        return json.load(f)


class TestIsVerifiedTier:
    def test_strong_is_verified(self):
        assert is_verified_tier("STRONG") is True
        
    def test_moderate_is_verified(self):
        assert is_verified_tier("MODERATE") is True
        
    def test_weak_is_verified(self):
        assert is_verified_tier("WEAK") is True
        
    def test_unverified_is_not_verified(self):
        assert is_verified_tier("UNVERIFIED") is False
        
    def test_case_insensitive(self):
        assert is_verified_tier("strong") is True
        assert is_verified_tier("Strong") is True


class TestParseCitationsManifest:
    def test_none_manifest(self):
        result = parse_citations_manifest(None)
        assert result["verified_citations"] == 0
        assert result["unverified_citations"] == 0
        assert result["status"] == "no_manifest"
        
    def test_empty_manifest(self):
        result = parse_citations_manifest([])
        assert result["verified_citations"] == 0
        assert result["unverified_citations"] == 0
        assert result["status"] == "no_manifest"
        
    def test_mixed_tiers(self):
        manifest = [
            {"tier": "STRONG", "page_id": "1"},
            {"tier": "MODERATE", "page_id": "2"},
            {"tier": "UNVERIFIED", "page_id": "3"},
            {"tier": "WEAK", "page_id": "4"}
        ]
        result = parse_citations_manifest(manifest)
        assert result["verified_citations"] == 3
        assert result["unverified_citations"] == 1
        assert result["tier_counts"]["STRONG"] == 1
        assert result["tier_counts"]["MODERATE"] == 1
        assert result["tier_counts"]["WEAK"] == 1
        assert result["tier_counts"]["UNVERIFIED"] == 1
        
    def test_unknown_tier_defaults_to_unverified(self):
        manifest = [{"tier": "UNKNOWN", "page_id": "1"}]
        result = parse_citations_manifest(manifest)
        assert result["unverified_citations"] == 1
        assert result["verified_citations"] == 0


class TestParseRetrievalManifest:
    def test_none_manifest(self):
        result = parse_retrieval_manifest(None)
        assert result["page_ids"] == []
        assert result["scotus_present"] == "unknown"
        assert result["status"] == "no_manifest"
        
    def test_truncated_manifest(self):
        manifest = {"truncated": True, "original_page_count": 100}
        result = parse_retrieval_manifest(manifest)
        assert result["page_count"] == 100
        assert result["scotus_present"] == "unknown"
        assert result["status"] == "truncated"
        
    def test_scotus_detected_by_origin(self):
        manifest = {
            "page_ids": ["1", "2"],
            "opinion_ids": ["op1"],
            "origins": ["SCOTUS", "CAFC"],
            "case_names": []
        }
        result = parse_retrieval_manifest(manifest)
        assert result["scotus_present"] is True
        
    def test_scotus_detected_by_case_name(self):
        manifest = {
            "page_ids": ["1"],
            "opinion_ids": ["op1"],
            "origins": [],
            "case_names": ["Supreme Court case"]
        }
        result = parse_retrieval_manifest(manifest)
        assert result["scotus_present"] is True
        
    def test_en_banc_detected(self):
        manifest = {
            "page_ids": ["1"],
            "opinion_ids": ["op1"],
            "origins": [],
            "case_names": ["Case v. Other (en banc)"]
        }
        result = parse_retrieval_manifest(manifest)
        assert result["en_banc_present"] is True


class TestParseModelConfig:
    def test_none_config(self):
        result = parse_model_config(None)
        assert result["augmentation_used"]["decompose"] is False
        assert result.get("triggered", False) is False
        assert result["status"] == "no_config"
        
    def test_no_phase1(self):
        result = parse_model_config({"model": "gpt-4o"})
        assert result["triggered"] is False
        assert result["status"] == "no_phase1"
        
    def test_phase1_enabled(self):
        config = {
            "phase1": {
                "triggered": True,
                "decompose_enabled": True,
                "embed_enabled": False,
                "trigger_reasons": ["thin_results", "multi_issue"],
                "total_candidates_added": 10,
                "augmentation_latency_ms": 300
            }
        }
        result = parse_model_config(config)
        assert result["triggered"] is True
        assert result["augmentation_used"]["decompose"] is True
        assert result["augmentation_used"]["embeddings"] is False
        assert result["triggers"] == ["thin_results", "multi_issue"]
        assert result["candidates_added"] == 10


class TestNormalizeReplayPacket:
    def test_sample_packet(self):
        packet = load_fixture("sample_replay_packet.json")
        result = normalize_replay_packet(packet)
        
        assert result["run_id"] == "test-run-001"
        assert result["answer_length"] > 0
        assert result["not_found"] is False
        assert result["verified_citations"] == 2
        assert result["unverified_citations"] == 1
        assert result["scotus_present"] is True
        assert result["phase1_triggered"] is True
        
    def test_truncated_packet(self):
        packet = load_fixture("sample_replay_packet_truncated.json")
        result = normalize_replay_packet(packet)
        
        assert result["answer_length"] == -1
        assert result["answer_status"] == "truncated"
        assert result["scotus_present"] == "unknown"
        
    def test_not_found_packet(self):
        packet = load_fixture("sample_replay_packet_not_found.json")
        result = normalize_replay_packet(packet)
        
        assert result["not_found"] is True
        assert result["verified_citations"] == 0
        assert result["phase1_triggered"] is False


class TestExtractMetricsFromResponse:
    def test_with_sources(self):
        response = {
            "answer": "The test answer with citations.",
            "sources": [
                {"caseName": "Alice v. CLS", "confidenceTier": "STRONG", "origin": "SCOTUS"},
                {"caseName": "Enfish v. Microsoft", "confidenceTier": "MODERATE"},
                {"caseName": "Other Case", "confidenceTier": "UNVERIFIED"}
            ]
        }
        result = extract_metrics_from_response(response)
        
        assert result["verified_citations"] == 2
        assert result["unverified_citations"] == 1
        assert result["scotus_present"] is True
        assert result["not_found"] is False
        assert result["answer_length"] > 0
        
    def test_not_found_response(self):
        response = {
            "answer": "NOT FOUND IN PROVIDED OPINIONS.",
            "sources": []
        }
        result = extract_metrics_from_response(response)
        
        assert result["not_found"] is True
        assert result["total_sources"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
