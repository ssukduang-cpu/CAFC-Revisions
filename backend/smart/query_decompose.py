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
from typing import List, Tuple, Optional

from backend.smart.config import MAX_SUBQUERIES, PHASE1_BUDGET_MS

logger = logging.getLogger(__name__)

DOCTRINE_SIGNALS = {
    "101": ["101", "alice", "mayo", "abstract idea", "patent eligible", "eligibility", "judicial exception"],
    "102": ["102", "anticipation", "anticipate", "prior art", "novelty"],
    "103": ["103", "obviousness", "obvious", "secondary considerations", "teaching away", "ksr", "motivation to combine"],
    "112": ["112", "enablement", "written description", "indefiniteness", "claim construction", "means plus function"],
    "claim_construction": ["claim construction", "markman", "phillips", "extrinsic", "intrinsic", "specification", "prosecution history"],
    "infringement": ["infringement", "infringe", "doctrine of equivalents", "literal infringement", "contributory", "inducement"],
    "damages": ["damages", "reasonable royalty", "lost profits", "georgia-pacific", "apportionment", "entire market value"],
    "inequitable_conduct": ["inequitable conduct", "unenforceability", "materiality", "intent to deceive"],
    "obviousness_type_double_patenting": ["double patenting", "terminal disclaimer", "otdp"],
}

CONJUNCTION_PATTERNS = [
    r'\band\b',
    r'\bas well as\b',
    r'\bplus\b',
    r'\balong with\b',
    r'\bin addition to\b',
    r'\btogether with\b',
    r'\bcombined with\b',
]


def detect_doctrine_signals(query: str) -> List[str]:
    """Detect which doctrine areas are mentioned in the query."""
    query_lower = query.lower()
    detected = []
    
    for doctrine, signals in DOCTRINE_SIGNALS.items():
        for signal in signals:
            if signal in query_lower:
                if doctrine not in detected:
                    detected.append(doctrine)
                break
    
    return detected


def has_conjunction_pattern(query: str) -> bool:
    """Check if query has conjunction patterns suggesting multiple issues."""
    query_lower = query.lower()
    for pattern in CONJUNCTION_PATTERNS:
        if re.search(pattern, query_lower):
            return True
    return False


def should_decompose(query: str) -> bool:
    """
    Determine if a query should be decomposed.
    
    Returns True if:
    - Multiple doctrine signals detected (e.g., "Alice" + "enablement")
    - Conjunction patterns with distinct legal terms
    """
    doctrines = detect_doctrine_signals(query)
    
    if len(doctrines) >= 2:
        return True
    
    if has_conjunction_pattern(query) and len(doctrines) >= 1:
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
        doctrines = detect_doctrine_signals(query)
        
        if len(doctrines) < 2:
            return []
        
        subqueries = []
        query_lower = query.lower()
        
        for doctrine in doctrines[:max_subqueries]:
            signals = DOCTRINE_SIGNALS.get(doctrine, [])
            
            matched_signals = [s for s in signals if s in query_lower]
            
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


def get_decomposition_info(query: str) -> dict:
    """Get diagnostic info about query decomposition for telemetry."""
    return {
        "doctrines_detected": detect_doctrine_signals(query),
        "has_conjunction": has_conjunction_pattern(query),
        "should_decompose": should_decompose(query),
        "word_count": len(query.split())
    }
