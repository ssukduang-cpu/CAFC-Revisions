"""Precedence-aware ranking with composite scoring and 'applies vs mentions' detection.

This module implements legal authority ranking that surfaces the most authoritative
and on-point results (statute/SCOTUS/en banc/precedential CAFC) and demotes cases
that merely mention controlling authority.
"""
import re
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, date

AUTHORITY_BOOST = {
    "statute": 2.0,
    "SCOTUS": 1.8,
    "CAFC_en_banc": 1.6,
    "CAFC_precedential": 1.3,
    "PTAB_precedential": 1.1,
    "nonprecedential": 0.8,
    "unknown": 1.0
}

FRAMEWORK_TERMS = [
    # §101 eligibility
    "Alice", "Mayo", "Bilski", "Diehr", "Benson", "Flook",
    # §103 obviousness
    "KSR", "Graham", "TSM",
    # §112 disclosure
    "Nautilus", "Amgen", "Ariad", "Gentry", "Williamson",
    # Claim construction
    "Markman", "Teva", "Phillips", "Vitronics", "Innova",
    # PTAB reviewability
    "Cuozzo", "Thryv", "SAS",
    # Remedies
    "eBay", "Halo", "Octane", "Stryker",
    # DOE/estoppel
    "Festo", "Warner-Jenkinson", "Graver Tank"
]

# Framework boost mapping: query doctrine tag -> controlling frameworks to boost
DOCTRINE_FRAMEWORKS = {
    "101": ["Alice", "Mayo", "Bilski", "Diehr", "Benson", "Flook"],
    "103": ["Graham", "KSR", "TSM"],
    "112": ["Nautilus", "Amgen", "Ariad", "Williamson"],
    "claim_construction": ["Markman", "Teva", "Phillips", "Vitronics"],
    "ptab": ["Cuozzo", "Thryv", "SAS"],
    "remedies": ["eBay", "Halo", "Octane", "Stryker"],
    "doe": ["Festo", "Warner-Jenkinson", "Graver Tank"]
}

def normalize_origin(origin: str, case_name: str = "") -> str:
    """Normalize origin field to standard court labels.
    
    Maps various ingestion sources to standard court labels:
    - courtlistener_api, web_search, DCT, cafc_website -> CAFC (default)
    - SCOTUS -> SCOTUS
    - PTAB -> PTAB
    
    Also checks case_name for SCOTUS indicators.
    """
    origin_upper = origin.upper() if origin else ""
    case_lower = case_name.lower() if case_name else ""
    
    # Check case_name for SCOTUS indicators
    scotus_indicators = ["u.s.", "s.ct.", "s. ct.", "supreme court", " v. "]
    scotus_cases = ["alice corp", "mayo collaborative", "ksr international", 
                    "ebay inc", "halo electronics", "octane fitness", "teva pharm",
                    "markman v. westview", "bilski v. kappos", "cuozzo speed",
                    "thryv, inc", "sas institute", "amgen inc. v. sanofi",
                    "nautilus, inc", "festo corp", "warner-jenkinson"]
    
    for case in scotus_cases:
        if case in case_lower:
            return "SCOTUS"
    
    # Direct origin matches
    if origin_upper == "SCOTUS":
        return "SCOTUS"
    
    if origin_upper == "PTAB":
        return "PTAB"
    
    # Everything else normalizes to CAFC (including courtlistener_api, web_search, DCT)
    return "CAFC"


def get_authority_type(page: Dict) -> str:
    """Determine the authority type of a document."""
    raw_origin = page.get("origin", "")
    case_name = page.get("case_name", "")
    is_en_banc = page.get("is_en_banc", False)
    is_precedential = page.get("is_precedential", True)
    
    # Normalize origin
    origin = normalize_origin(raw_origin, case_name)
    
    if "u.s.c." in case_name.lower() or "§" in case_name:
        return "statute"
    
    if origin == "SCOTUS":
        return "SCOTUS"
    
    if origin == "PTAB":
        if is_precedential:
            return "PTAB_precedential"
        return "nonprecedential"
    
    if is_en_banc:
        return "CAFC_en_banc"
    
    if is_precedential:
        return "CAFC_precedential"
    
    return "nonprecedential"


def compute_authority_boost(page: Dict) -> float:
    """Compute authority boost based on document type."""
    authority_type = get_authority_type(page)
    return AUTHORITY_BOOST.get(authority_type, 1.0)


def compute_recency_factor(page: Dict) -> float:
    """Compute recency factor (0.95-1.10) based on release date."""
    release_date = page.get("release_date")
    if not release_date:
        return 1.0
    
    try:
        if isinstance(release_date, str):
            release_date = datetime.strptime(release_date[:10], "%Y-%m-%d").date()
        elif isinstance(release_date, datetime):
            release_date = release_date.date()
        
        current_year = datetime.now().year
        doc_year = release_date.year
        years_old = current_year - doc_year
        
        if years_old <= 2:
            return 1.10
        elif years_old <= 5:
            return 1.05
        elif years_old <= 10:
            return 1.0
        elif years_old <= 20:
            return 0.98
        else:
            return 0.95
    except (ValueError, AttributeError):
        return 1.0


def compute_gravity_factor(page: Dict) -> float:
    """Compute gravity factor (0.60-1.00) from document metadata.
    
    Higher gravity for:
    - En banc decisions
    - Cases with high citation count
    - Landmark cases
    """
    is_en_banc = page.get("is_en_banc", False)
    is_landmark = page.get("is_landmark", False)
    citation_count = page.get("citation_count", 0)
    
    base = 0.85
    
    if is_en_banc:
        base += 0.10
    
    if is_landmark:
        base += 0.05
    
    if citation_count:
        if citation_count > 100:
            base += 0.05
        elif citation_count > 50:
            base += 0.03
    
    return min(1.0, max(0.60, base))


def compute_holding_indicator(text: str) -> int:
    """Detect holding language strength (0/1/2).
    
    Returns:
        2: Strong holding language (we hold, we conclude, we reverse/affirm)
        1: Moderate holding language (the court finds, we agree, we determine)
        0: No holding language detected
    """
    text_lower = text.lower()
    
    strong_patterns = [
        r'\bwe\s+hold\b',
        r'\bwe\s+conclude\b',
        r'\bwe\s+reverse\b',
        r'\bwe\s+affirm\b',
        r'\btherefore\s*,?\s*we\b',
        r'\baccordingly\s*,?\s*we\s+(hold|conclude|reverse|affirm)\b',
        r'\bfor\s+the\s+foregoing\s+reasons\b'
    ]
    
    for pattern in strong_patterns:
        if re.search(pattern, text_lower):
            return 2
    
    moderate_patterns = [
        r'\bthe\s+court\s+finds\b',
        r'\bwe\s+agree\b',
        r'\bwe\s+determine\b',
        r'\bwe\s+find\s+that\b',
        r'\bit\s+is\s+clear\s+that\b',
        r'\bwe\s+are\s+persuaded\b'
    ]
    
    for pattern in moderate_patterns:
        if re.search(pattern, text_lower):
            return 1
    
    return 0


def compute_analysis_depth(text: str) -> float:
    """Compute analysis depth score (0-1) based on length and structure.
    
    Rewards:
    - Longer substantive text
    - Legal reasoning indicators (because, therefore, analysis shows)
    - Citation density
    """
    if not text:
        return 0.0
    
    text_len = len(text)
    base_score = min(1.0, text_len / 5000.0)
    
    reasoning_patterns = [
        r'\bbecause\b', r'\btherefore\b', r'\bthus\b', r'\bhence\b',
        r'\banalysis\b', r'\breasoning\b', r'\bunder\s+this\s+standard\b',
        r'\bapplying\s+this\s+(test|standard|framework)\b',
        r'\bfirst\b.*\bsecond\b', r'\bstep\s+one\b.*\bstep\s+two\b'
    ]
    
    structure_boost = 0.0
    for pattern in reasoning_patterns:
        if re.search(pattern, text.lower()):
            structure_boost += 0.1
    
    citation_count = len(re.findall(r'\d+\s+F\.\s*\d*d?\s+\d+|\d+\s+U\.S\.\s+\d+', text))
    citation_boost = min(0.2, citation_count * 0.02)
    
    return min(1.0, base_score + structure_boost + citation_boost)


def detect_framework_reference(text: str) -> Tuple[int, List[str]]:
    """Detect references to controlling legal frameworks.
    
    Returns:
        (1 or 0, list of detected framework names)
    """
    text_lower = text.lower()
    detected = []
    
    for term in FRAMEWORK_TERMS:
        pattern = rf'\b{term.lower()}\b'
        if re.search(pattern, text_lower):
            detected.append(term)
    
    applying_pattern = r'applying\s+(' + '|'.join([t.lower() for t in FRAMEWORK_TERMS]) + r')'
    if re.search(applying_pattern, text_lower):
        return (1, detected)
    
    under_pattern = r'under\s+(' + '|'.join([t.lower() for t in FRAMEWORK_TERMS]) + r')'
    if re.search(under_pattern, text_lower):
        return (1, detected)
    
    if detected:
        return (1, detected)
    
    return (0, [])


def compute_proximity_score(text: str) -> float:
    """Compute proximity between doctrine terms and holding/analysis terms.
    
    Higher score when framework terms appear near holding language.
    """
    if not text:
        return 0.0
    
    text_lower = text.lower()
    
    doctrine_positions = []
    for term in FRAMEWORK_TERMS:
        for match in re.finditer(rf'\b{term.lower()}\b', text_lower):
            doctrine_positions.append(match.start())
    
    if not doctrine_positions:
        return 0.0
    
    holding_patterns = [
        r'\bwe\s+hold\b', r'\bwe\s+conclude\b', r'\bapplying\b',
        r'\bthe\s+court\s+finds\b', r'\bwe\s+agree\b'
    ]
    
    holding_positions = []
    for pattern in holding_patterns:
        for match in re.finditer(pattern, text_lower):
            holding_positions.append(match.start())
    
    if not holding_positions:
        return 0.0
    
    min_distance = float('inf')
    for d_pos in doctrine_positions:
        for h_pos in holding_positions:
            distance = abs(d_pos - h_pos)
            min_distance = min(min_distance, distance)
    
    if min_distance < 100:
        return 1.0
    elif min_distance < 300:
        return 0.7
    elif min_distance < 500:
        return 0.4
    elif min_distance < 1000:
        return 0.2
    else:
        return 0.0


def compute_application_signal(text: str) -> Dict[str, Any]:
    """Compute full application signal for 'applies vs mentions' ranking.
    
    Capped to [0.8, 1.5] range:
    - 0.8: No doctrine / mention-only content (penalized)
    - 1.0: Baseline / neutral
    - 1.5: Deep application with holding language (maximum boost)
    
    Component weights (normalized to yield 0-0.5 boost):
    - holding_indicator: 0.15 per level (max 0.30 for level 2)
    - analysis_depth: 0.10 (max 0.10)
    - framework_reference: 0.05 (max 0.05)
    - proximity_score: 0.05 (max 0.05)
    Total max boost: 0.50 -> signal = 1.5
    
    Penalty for no doctrine: -0.2 -> signal = 0.8
    
    Returns dict with breakdown and final signal.
    """
    holding_indicator = compute_holding_indicator(text)
    analysis_depth = compute_analysis_depth(text)
    framework_ref, frameworks_detected = detect_framework_reference(text)
    proximity = compute_proximity_score(text)
    
    # Normalized weights to cap boost at 0.5
    boost = (0.15 * holding_indicator +      # max 0.30 (holding=2)
             0.10 * analysis_depth +          # max 0.10
             0.05 * framework_ref +           # max 0.05
             0.05 * proximity)                # max 0.05
    # Total max boost = 0.50
    
    # Base signal is 1.0, with boost capped at 0.5
    raw_signal = 1.0 + min(boost, 0.50)
    
    # Apply penalty for "mention-only" (no framework, no holding, low analysis)
    if framework_ref == 0 and holding_indicator == 0 and analysis_depth < 0.3:
        raw_signal = 0.8  # Penalize mention-only content
    
    # Final cap to [0.8, 1.5]
    application_signal = min(1.5, max(0.8, raw_signal))
    
    return {
        "holding_indicator": holding_indicator,
        "analysis_depth": round(analysis_depth, 3),
        "framework_reference": framework_ref,
        "frameworks_detected": frameworks_detected,
        "proximity_score": round(proximity, 3),
        "application_signal": round(application_signal, 3)
    }


def compute_composite_score(
    relevance_score: float,
    page: Dict,
    text: str = ""
) -> Dict[str, Any]:
    """Compute full composite score with explain breakdown.
    
    Formula:
        composite_score = relevance_score * authority_boost * gravity_factor * 
                          recency_factor * application_signal
    
    Returns dict with all factors and final composite score.
    """
    authority_boost = compute_authority_boost(page)
    gravity_factor = compute_gravity_factor(page)
    recency_factor = compute_recency_factor(page)
    
    page_text = text or page.get("text", "")
    app_signal_data = compute_application_signal(page_text)
    application_signal = app_signal_data["application_signal"]
    
    composite = (relevance_score * 
                 authority_boost * 
                 gravity_factor * 
                 recency_factor * 
                 application_signal)
    
    authority_type = get_authority_type(page)
    
    return {
        "relevance_score": round(relevance_score, 4),
        "authority_boost": authority_boost,
        "authority_type": authority_type,
        "gravity_factor": round(gravity_factor, 3),
        "recency_factor": round(recency_factor, 3),
        "application_signal": round(application_signal, 3),
        "application_breakdown": app_signal_data,
        "composite_score": round(composite, 4)
    }


def generate_application_reason(explain: Dict, page: Dict) -> str:
    """Generate 'Why this case?' one-sentence explanation.
    
    Derives from explain breakdown to show why this case ranks highly.
    """
    reasons = []
    
    authority_type = explain.get("authority_type", "unknown")
    if authority_type == "SCOTUS":
        reasons.append("Supreme Court precedent")
    elif authority_type == "CAFC_en_banc":
        reasons.append("En banc Federal Circuit decision")
    elif authority_type == "statute":
        reasons.append("Statutory authority")
    
    app_breakdown = explain.get("application_breakdown", {})
    holding = app_breakdown.get("holding_indicator", 0)
    frameworks = app_breakdown.get("frameworks_detected", [])
    
    if holding == 2:
        reasons.append("majority holding language")
    elif holding == 1:
        reasons.append("court findings language")
    
    if frameworks:
        framework_str = "/".join(frameworks[:3])
        reasons.append(f"applies {framework_str}")
    
    analysis = app_breakdown.get("analysis_depth", 0)
    if analysis > 0.7:
        reasons.append("detailed legal analysis")
    
    if not reasons:
        case_name = page.get("case_name", "")
        if case_name:
            return f"Relevant to query based on case content."
    
    return "; ".join(reasons) + "."


def compute_framework_boost(case_name: str, frameworks_detected: List[str], doctrine_tag: Optional[str] = None) -> float:
    """Compute framework_boost for controlling frameworks.
    
    Boosts SCOTUS cases that DEFINE controlling frameworks (not just apply them).
    Also boosts CAFC cases that are themselves controlling authority (e.g., Phillips for claim construction).
    
    Args:
        case_name: Name of the case
        frameworks_detected: Frameworks detected in the text
        doctrine_tag: Optional doctrine classification of the query (e.g., "101", "103")
    
    Returns:
        Framework boost multiplier (1.0 = no boost, up to 1.25 for controlling authority)
    """
    case_lower = case_name.lower() if case_name else ""
    
    # Check if this case IS a controlling framework (the case that defines the doctrine)
    controlling_cases = {
        "alice": 1.25,  # Alice Corp. v. CLS Bank defines §101 software test
        "mayo": 1.20,   # Mayo defines §101 natural phenomena test
        "bilski": 1.15, # Bilski defines abstract idea category
        "ksr": 1.25,    # KSR defines §103 obviousness
        "graham": 1.15, # Graham v. John Deere defines §103 factors
        "markman": 1.25,# Markman defines claim construction as law
        "teva": 1.20,   # Teva defines deference standard
        "phillips": 1.20,# Phillips defines intrinsic evidence priority
        "nautilus": 1.20,# Nautilus defines indefiniteness standard
        "amgen": 1.25,  # Amgen defines enablement for genus claims
        "ebay": 1.25,   # eBay defines injunction factors
        "halo": 1.20,   # Halo defines willfulness standard
        "octane": 1.20, # Octane defines exceptional case
        "cuozzo": 1.20, # Cuozzo defines PTAB reviewability
        "thryv": 1.20,  # Thryv defines time-bar non-reviewability
        "sas": 1.20,    # SAS defines partial institution
        "festo": 1.20,  # Festo defines prosecution history estoppel
        "warner-jenkinson": 1.15,  # Warner-Jenkinson defines DOE
    }
    
    for framework, boost in controlling_cases.items():
        if framework in case_lower:
            return boost
    
    # No boost if not a defining case
    return 1.0


def rank_sources_by_composite(
    sources: List[Dict],
    pages_by_id: Dict[str, Dict],
    doctrine_tag: Optional[str] = None
) -> List[Dict]:
    """Re-rank sources by composite score and add explain metadata.
    
    Args:
        sources: List of source dicts (from build_sources_with_binding)
        pages_by_id: Dict mapping opinion_id to page data
        doctrine_tag: Optional doctrine classification for framework boost
    
    Returns:
        Sources sorted by composite_score with explain added
    """
    enriched = []
    
    for source in sources:
        opinion_id = source.get("opinion_id", "")
        page = pages_by_id.get(opinion_id, {})
        
        # Get citation verification score if available (new structure)
        citation_verif = source.get("citation_verification", {})
        verif_score = citation_verif.get("score", 0)
        verif_tier = citation_verif.get("tier", "")
        
        # Compute base relevance score from verification or default
        if verif_score:
            base_score = verif_score / 100.0
        else:
            base_score = 0.5
        
        if verif_tier == "strong":
            base_score = max(base_score, 0.7)
        elif verif_tier == "moderate":
            base_score = max(base_score, 0.5)
        
        # Merge page metadata with source metadata
        page_with_meta = {**page, **source}
        
        # Use origin from source if available (P0.3 fix)
        if source.get("court"):
            page_with_meta["origin"] = source.get("court")
        if source.get("precedential_status") == "precedential":
            page_with_meta["is_precedential"] = True
        elif source.get("precedential_status") == "nonprecedential":
            page_with_meta["is_precedential"] = False
        if source.get("is_en_banc"):
            page_with_meta["is_en_banc"] = True
        
        text = page.get("text", "") or source.get("quote", "")
        
        explain = compute_composite_score(base_score, page_with_meta, text)
        
        # Apply framework boost for controlling authorities (P1.4)
        case_name = source.get("case_name", "")
        frameworks = explain.get("application_breakdown", {}).get("frameworks_detected", [])
        framework_boost = compute_framework_boost(case_name, frameworks, doctrine_tag)
        
        if framework_boost > 1.0:
            explain["framework_boost"] = framework_boost
            explain["composite_score"] = round(explain["composite_score"] * framework_boost, 4)
        
        application_reason = generate_application_reason(explain, page_with_meta)
        
        # Normalize court in output (P0.3)
        normalized_court = normalize_origin(source.get("court", ""), case_name)
        
        enriched.append({
            **source,
            "court": normalized_court,  # Override with normalized court
            "explain": explain,
            "application_reason": application_reason
        })
    
    enriched.sort(key=lambda x: x.get("explain", {}).get("composite_score", 0), reverse=True)
    
    return enriched
