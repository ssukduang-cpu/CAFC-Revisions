"""
Query Decomposition Module

Detects multi-issue legal queries and decomposes them into focused subqueries.
Used to augment retrieval by searching for each subquery separately.

This module is:
- Additive only (does not replace baseline retrieval)
- Fail-soft (returns empty list on any error)
- Bounded (max 4 subqueries)
"""

import re
import logging
import time
from typing import List, Tuple, Optional, Dict, Any

from backend.smart.config import MAX_SUBQUERIES, PHASE1_BUDGET_MS

logger = logging.getLogger(__name__)

DOCTRINE_SIGNALS = {
    "101": [
        "101", "§101", "§ 101", "section 101",
        "alice", "mayo", "bilski",
        "abstract idea", "abstract", 
        "patent eligible", "eligibility", "patent-eligible",
        "judicial exception", "laws of nature", "natural phenomena"
    ],
    "102": [
        "102", "§102", "§ 102", "section 102",
        "anticipation", "anticipate", "anticipated",
        "prior art", "novelty"
    ],
    "103": [
        "103", "§103", "§ 103", "section 103",
        "obviousness", "obvious", "nonobvious", "non-obvious",
        "secondary considerations", "teaching away", 
        "ksr", "graham", "motivation to combine", "combine references"
    ],
    "112": [
        "112", "§112", "§ 112", "section 112",
        "enablement", "enabled", "undue experimentation",
        "written description", "indefiniteness", "indefinite",
        "claim construction", "means plus function", "means-plus-function",
        "wands factors"
    ],
    "claim_construction": [
        "claim construction", "markman", "phillips",
        "extrinsic", "intrinsic", "specification", "prosecution history"
    ],
    "infringement": [
        "infringement", "infringe", "infringes", "infringing",
        "doctrine of equivalents", "literal infringement",
        "contributory", "inducement", "induced"
    ],
    "damages": [
        "damages", "reasonable royalty", "lost profits",
        "georgia-pacific", "apportionment", "entire market value"
    ],
    "inequitable_conduct": [
        "inequitable conduct", "unenforceability", 
        "materiality", "intent to deceive", "therasense"
    ],
    "obviousness_type_double_patenting": [
        "double patenting", "terminal disclaimer", "otdp"
    ],
    "certificate_correction": [
        "certificate of correction", "certificates of correction", "reissue",
        "retroactive effect", "252", "254", "255"
    ],
}

CONJUNCTION_PATTERNS = [
    r'\band\b',
    r'\bas well as\b',
    r'\bplus\b',
    r'\balong with\b',
    r'\bin addition to\b',
    r'\btogether with\b',
    r'\bcombined with\b',
    r'\bboth\b.*\band\b',
    r'/',
]

SECTION_PATTERN = re.compile(r'§?\s*(\d{3})', re.IGNORECASE)

def canonicalize_legal_query(query: str) -> str:
    """Expand common ambiguous legal phrasing into doctrine-oriented terms."""
    q = query
    replacements = [
        (r"\bfunctional and broad\b", "functional claiming under 112(f) written description enablement"),
        (r"\bfew examples\b", "few representative species written description enablement"),
        (r"\bcabin scope\b", "prosecution disclaimer claim construction"),
        (r"\bcorrected after issuance\b", "certificate of correction retroactive effect 252 254 255"),
    ]
    for pattern, repl in replacements:
        q = re.sub(pattern, repl, q, flags=re.IGNORECASE)
    return q


def detect_doctrine_signals(query: str) -> Tuple[List[str], Dict[str, List[str]]]:
    """
    Detect which doctrine areas are mentioned in the query.
    
    Returns:
        (list of doctrine names, dict of doctrine -> matched signals)
    """
    canonical_query = canonicalize_legal_query(query)
    query_lower = canonical_query.lower()
    detected = []
    evidence = {}
    
    for doctrine, signals in DOCTRINE_SIGNALS.items():
        matched_signals = []
        for signal in signals:
            if signal.lower() in query_lower:
                matched_signals.append(signal)
        
        if matched_signals:
            if doctrine not in detected:
                detected.append(doctrine)
            evidence[doctrine] = matched_signals
    
    section_matches = SECTION_PATTERN.findall(canonical_query)
    for section in section_matches:
        if section in ["101", "102", "103", "112", "252", "254", "255"]:
            mapped = "certificate_correction" if section in ["252", "254", "255"] else section
            if mapped not in detected:
                detected.append(mapped)
            evidence[mapped] = evidence.get(mapped, []) + [f"§{section}"]
    
    return detected, evidence


def has_conjunction_pattern(query: str) -> Tuple[bool, Optional[str]]:
    """
    Check if query has conjunction patterns suggesting multiple issues.
    
    Returns:
        (has_conjunction, matched_pattern)
    """
    query_lower = query.lower()
    for pattern in CONJUNCTION_PATTERNS:
        match = re.search(pattern, query_lower)
        if match:
            return True, pattern
    return False, None


def should_decompose(query: str) -> bool:
    """
    Determine if a query should be decomposed.
    
    Returns True if:
    - Multiple doctrine signals detected (e.g., "Alice" + "enablement")
    - Conjunction patterns with distinct legal terms
    """
    doctrines, _ = detect_doctrine_signals(query)
    
    if len(doctrines) >= 2:
        return True
    
    has_conj, _ = has_conjunction_pattern(query)
    if has_conj and len(doctrines) >= 1:
        if len(query.split()) >= 10:
            return True
    
    return False


def decompose_query(query: str, max_subqueries: int = MAX_SUBQUERIES) -> List[str]:
    """
    Decompose a multi-issue query into focused subqueries.
    
    Returns:
        List of subquery strings (max 4 by default)
    """
    try:
        doctrines, evidence = detect_doctrine_signals(query)
        
        if len(doctrines) < 2:
            return []
        
        subqueries = []
        query_lower = query.lower()
        
        for doctrine in doctrines[:max_subqueries]:
            matched_signals = evidence.get(doctrine, [])
            
            if matched_signals:
                primary_signal = matched_signals[0]
                
                case_name_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+v\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', query)
                
                if case_name_match:
                    subquery = f"{case_name_match.group(1)} {primary_signal}"
                else:
                    subquery = f"{primary_signal} CAFC Federal Circuit"
                
                subqueries.append(subquery.strip())
        
        return subqueries[:max_subqueries]
        
    except Exception as e:
        logger.warning(f"Query decomposition failed: {e}")
        return []


def get_decomposition_info(query: str) -> Dict[str, Any]:
    """Get detailed diagnostic info about query decomposition for telemetry."""
    doctrines, evidence = detect_doctrine_signals(query)
    has_conj, conj_pattern = has_conjunction_pattern(query)
    should_dec = should_decompose(query)
    subqueries = decompose_query(query) if should_dec else []
    
    return {
        "doctrines_detected": doctrines,
        "doctrine_evidence": evidence,
        "has_conjunction": has_conj,
        "conjunction_pattern": conj_pattern,
        "should_decompose": should_dec,
        "subqueries": subqueries,
        "subquery_count": len(subqueries),
        "word_count": len(query.split())
    }


def log_trigger_decision(
    query: str,
    query_id: str = None,
    fts_count: int = None,
    top_score: float = None,
    min_fts_results: int = None,
    min_top_score: float = None
) -> Dict[str, Any]:
    """
    Log structured trigger decision for debugging.
    
    Returns dict with full decision context for telemetry.
    """
    doctrines, evidence = detect_doctrine_signals(query)
    has_conj, conj_pattern = has_conjunction_pattern(query)
    should_dec = should_decompose(query)
    
    thin_retrieval = False
    low_score = False
    
    if fts_count is not None and min_fts_results is not None:
        thin_retrieval = fts_count < min_fts_results
    
    if top_score is not None and min_top_score is not None:
        low_score = top_score < min_top_score
    
    decision = {
        "query_id": query_id,
        "query_preview": query[:100] + "..." if len(query) > 100 else query,
        "doctrines_detected": doctrines,
        "doctrine_count": len(doctrines),
        "doctrine_evidence": evidence,
        "multi_issue_detected": len(doctrines) >= 2,
        "has_conjunction": has_conj,
        "conjunction_pattern": conj_pattern,
        "thin_retrieval_detected": thin_retrieval,
        "thin_retrieval_evidence": {
            "fts_count": fts_count,
            "min_fts_results": min_fts_results
        } if fts_count is not None else None,
        "low_score_detected": low_score,
        "low_score_evidence": {
            "top_score": top_score,
            "min_top_score": min_top_score
        } if top_score is not None else None,
        "should_decompose": should_dec,
        "word_count": len(query.split())
    }
    
    logger.debug(
        f"[TRIGGER DECISION] query_id={query_id}, "
        f"doctrines={doctrines}, multi_issue={len(doctrines) >= 2}, "
        f"thin={thin_retrieval}, low_score={low_score}, "
        f"should_decompose={should_dec}"
    )
    
    return decision
