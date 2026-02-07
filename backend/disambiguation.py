import re
from typing import Any, Dict, List, Optional


def detect_option_reference(message: str) -> Optional[int]:
    """Detect if message is a reference to a previous numbered option.

    Returns the option number (1-indexed) if detected, None otherwise.
    """
    msg_lower = message.lower().strip()

    if msg_lower.isdigit() and 1 <= int(msg_lower) <= 10:
        return int(msg_lower)

    ordinal_patterns = [
        (r'\bsecond\b', 2), (r'\b2nd\b', 2),
        (r'\bthird\b', 3), (r'\b3rd\b', 3),
        (r'\bfourth\b', 4), (r'\b4th\b', 4),
        (r'\bfifth\b', 5), (r'\b5th\b', 5),
        (r'\bfirst\b', 1), (r'\b1st\b', 1),
    ]
    for pattern, num in ordinal_patterns:
        if re.search(pattern, msg_lower):
            return num

    patterns = [
        r'option\s*(\d+)',
        r'number\s*(\d+)',
        r'case\s*(\d+)',
        r'#\s*(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, msg_lower)
        if match:
            return int(match.group(1))

    return None


def _extract_reference_hints(message: str) -> Dict[str, Any]:
    msg = message.lower().strip()
    hints: Dict[str, Any] = {
        "is_followup_like": False,
        "ordinal": None,
        "year": None,
        "appeal_no": None,
        "party_tokens": set(),
    }
    if not msg:
        return hints

    followup_markers = ["that one", "this one", "the one", "newer", "older", "latest", "earlier", "google one", "apple one"]
    hints["is_followup_like"] = any(marker in msg for marker in followup_markers)

    ordinal_map = {
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
        "last": -1,
        "final": -1,
    }
    for word, val in ordinal_map.items():
        if re.search(rf"\b{word}\b", msg):
            hints["ordinal"] = val
            break

    year_match = re.search(r"\b(19|20)\d{2}\b", msg)
    if year_match:
        hints["year"] = int(year_match.group(0))

    appeal_match = re.search(r"\b\d{2}-\d{3,6}\b", msg)
    if appeal_match:
        hints["appeal_no"] = appeal_match.group(0)

    tokens = re.findall(r"[a-z0-9\.\-]+", msg)
    stop = {
        "the", "one", "case", "newer", "older", "latest", "earlier", "please", "about", "for", "with",
        "holding", "opinion", "what", "which", "when", "where", "why", "how", "does", "did", "is",
        "are", "was", "were", "explain", "tell", "me", "compare", "difference"
    }
    hints["party_tokens"] = {t for t in tokens if len(t) > 2 and t not in stop and not t.isdigit()}

    return hints


def resolve_candidate_reference(message: str, candidates: List[Dict[str, Any]]) -> Optional[int]:
    explicit = detect_option_reference(message)
    if explicit:
        return explicit

    if not candidates:
        return None

    hints = _extract_reference_hints(message)

    if hints["ordinal"] == -1:
        return len(candidates)
    if isinstance(hints["ordinal"], int) and hints["ordinal"] > 0:
        return hints["ordinal"]

    if hints["appeal_no"]:
        for i, c in enumerate(candidates, start=1):
            if hints["appeal_no"] in (c.get("appeal_no") or ""):
                return i

    scores = []
    for i, c in enumerate(candidates, start=1):
        label = (c.get("label") or "").lower()
        label_tokens = set(re.findall(r"[a-z0-9\.\-]+", label))
        overlap = len(hints["party_tokens"] & label_tokens)
        score = float(overlap)

        if hints["year"] and str(hints["year"]) in label:
            score += 1.0

        scores.append((score, i))

    scores.sort(reverse=True)
    if scores and scores[0][0] >= 1.0:
        if len(scores) == 1 or (scores[0][0] - scores[1][0]) >= 1.0:
            return scores[0][1]

    return None


def is_probable_disambiguation_followup(message: str) -> bool:
    hints = _extract_reference_hints(message)
    if hints["is_followup_like"]:
        return True
    if hints["ordinal"] is not None or hints["appeal_no"] or hints["year"]:
        return True

    msg = message.strip().lower()
    if "?" in msg or re.match(r"^(what|which|when|where|why|how|explain|compare|analyze|tell)\b", msg):
        return False

    return len(hints["party_tokens"]) > 0 and len(msg.split()) <= 8
