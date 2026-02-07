#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.smart.query_decompose import detect_doctrine_signals, canonicalize_legal_query


def test_canonicalize_functional_and_broad_maps_to_112_terms():
    q = "How do we attack this patent if the claim sounds functional and broad?"
    cq = canonicalize_legal_query(q).lower()
    assert "112" in cq or "enablement" in cq


def test_certificate_sections_map_to_certificate_correction_doctrine():
    q = "Under 35 U.S.C. §§254–255, what is the retroactive effect of a certificate of correction?"
    doctrines, evidence = detect_doctrine_signals(q)
    assert "certificate_correction" in doctrines
    assert "certificate_correction" in evidence
