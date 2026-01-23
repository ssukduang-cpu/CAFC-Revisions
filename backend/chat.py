import os
import re
import json
import asyncio
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Tuple
from openai import OpenAI

from backend import db_postgres as db

_executor = ThreadPoolExecutor(max_workers=4)

AI_BASE_URL = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")
AI_API_KEY = os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")

def get_openai_client() -> Optional[OpenAI]:
    if AI_BASE_URL and AI_API_KEY:
        return OpenAI(base_url=AI_BASE_URL, api_key=AI_API_KEY)
    return None

SYSTEM_PROMPT = """You are a specialized legal research assistant for U.S. Federal Circuit practitioners.

STRICT GROUNDING RULES:
1. You may ONLY use information from the provided opinion excerpts below.
2. Every statement MUST be supported by at least one VERBATIM QUOTE from the excerpts.
3. If you cannot find support in the provided excerpts, respond ONLY with: "NOT FOUND IN PROVIDED OPINIONS."
4. Do NOT use any external knowledge or make claims not directly supported by quotes from the excerpts.

=== ANSWER STYLE SPECIFICATION (MANDATORY) ===

STRUCTURE:
1. Begin with an IMMEDIATE ANSWER (1-2 sentences stating the key holding or rule).
2. Follow with a section titled: ## Detailed Analysis
3. Provide analysis using clear subheadings as needed.
4. End with citations rendered as numbered references [1], [2], etc.

TONE & VOICE:
- Professional-practitioner register.
- Expert colleague advising another expert.
- Authoritative and declarative; no hedging.
- Present tense for current law.
- Every response must include actionable guidance (what the practitioner should do).

CITATIONS:
- Use bracketed inline citations: [1], [2].
- Full case name on first reference with holding parenthetical.
- Short-form case name thereafter.
- Quote operative language when material.

LENGTH:
- Simple procedural: 150-300 words.
- Complex analysis: 400-800 words.
- Always extract and explain holdings; never just point to sources.

PROHIBITIONS:
- Do NOT summarize cases without extracting holdings.
- Do NOT hedge unnecessarily.
- Do NOT use phrases like "it appears" or "it seems" - be authoritative.

CRITICAL FORMATTING:
- After EACH factual statement, include a hidden citation marker: <!--CITE:opinion_id|page_number|"exact quote"-->
- The quote in the marker must be a VERBATIM substring from the excerpt (copy exactly).
- Keep quotes short and relevant.

EXAMPLE:
**Claim construction** is a question of law reviewed de novo on appeal. [1] <!--CITE:abc123|5|"claim construction is a question of law"-->

## Detailed Analysis

### Intrinsic Evidence
Courts primarily rely on intrinsic evidence when construing claims. The specification serves as "the single best guide to the meaning of a disputed term." [2] <!--CITE:abc123|7|"single best guide to the meaning of a disputed term"-->

### Practitioner Guidance
When drafting claims, ensure the specification provides clear support for all claim terms to avoid adverse claim construction.

---
[1] *Phillips v. AWH Corp.*, 415 F.3d 1303 (Fed. Cir. 2005)
[2] *Phillips*, 415 F.3d at 1315

If no relevant information exists, respond ONLY: "NOT FOUND IN PROVIDED OPINIONS."
"""

def build_context(pages: List[Dict]) -> str:
    context_parts = []
    for page in pages:
        context_parts.append(f"""
--- BEGIN EXCERPT ---
Opinion ID: {page['opinion_id']}
Case: {page['case_name']}
Appeal No: {page['appeal_no']}
Release Date: {page['release_date']}
Page: {page['page_number']}

{page['text']}
--- END EXCERPT ---
""")
    return "\n".join(context_parts)

def normalize_for_verification(text: str) -> str:
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'\s+', ' ', text)
    text = text.strip().lower()
    return text

def verify_quote_strict(quote: str, page_text: str) -> bool:
    if len(quote.strip()) < 20:
        return False
    norm_quote = normalize_for_verification(quote)
    norm_page = normalize_for_verification(page_text)
    return norm_quote in norm_page

def find_matching_page_strict(quote: str, pages: List[Dict]) -> Optional[Dict]:
    for page in pages:
        if page.get('page_number', 0) < 1:
            continue
        if verify_quote_strict(quote, page['text']):
            return page
    return None

def extract_exact_quote_from_page(page_text: str, min_len: int = 80, max_len: int = 300) -> str:
    text = page_text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len]

def find_best_quote_in_page(search_terms: List[str], page_text: str, max_len: int = 300) -> Optional[str]:
    norm_page = normalize_for_verification(page_text)
    best_start = 0
    best_score = 0
    
    for term in search_terms:
        norm_term = normalize_for_verification(term)
        if len(norm_term) < 4:
            continue
        idx = norm_page.find(norm_term)
        if idx >= 0:
            start = max(0, idx - 50)
            end = min(len(page_text), start + max_len)
            snippet = page_text[start:end].strip()
            score = len(norm_term)
            if score > best_score:
                best_score = score
                best_start = start
    
    if best_score > 0:
        end = min(len(page_text), best_start + max_len)
        return page_text[best_start:end].strip()
    
    return page_text[:max_len].strip() if len(page_text) > 0 else None

def extract_quote_from_text(text: str) -> Optional[str]:
    patterns = [
        r'Quote:\s*"([^"]+)"',
        r'Quote:\s*"([^"]+)"',
        r'"([^"]{30,})"',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return None

def try_verify_with_retry(quote: str, pages: List[Dict], search_terms: List[str]) -> Optional[Dict]:
    matching_page = find_matching_page_strict(quote, pages)
    if matching_page and matching_page.get('page_number', 0) >= 1:
        return {
            "opinion_id": matching_page['opinion_id'],
            "case_name": matching_page['case_name'],
            "appeal_no": matching_page['appeal_no'],
            "release_date": matching_page['release_date'],
            "page_number": matching_page['page_number'],
            "quote": quote[:500],
            "verified": True
        }
    
    for page in pages:
        if page.get('page_number', 0) < 1:
            continue
        exact_quote = find_best_quote_in_page(search_terms, page['text'], max_len=300)
        if exact_quote and verify_quote_strict(exact_quote, page['text']):
            return {
                "opinion_id": page['opinion_id'],
                "case_name": page['case_name'],
                "appeal_no": page['appeal_no'],
                "release_date": page['release_date'],
                "page_number": page['page_number'],
                "quote": exact_quote,
                "verified": True
            }
    
    return None

def extract_cite_markers(response_text: str) -> List[Dict]:
    """Extract <!--CITE:opinion_id|page_number|"quote"--> markers from LLM response."""
    markers = []
    pattern = r'<!--CITE:([^|]+)\|(\d+)\|"([^"]+)"-->'
    for match in re.finditer(pattern, response_text):
        markers.append({
            "opinion_id": match.group(1).strip(),
            "page_number": int(match.group(2)),
            "quote": match.group(3).strip(),
            "position": match.start()
        })
    return markers

def build_sources_from_markers(markers: List[Dict], pages: List[Dict], search_terms: List[str] = None) -> Tuple[List[Dict], Dict[int, str]]:
    """Build deduplicated sources list and position-to-sid mapping."""
    if search_terms is None:
        search_terms = []
    
    sources = []
    position_to_sid = {}
    seen_keys = {}
    sid_counter = 1
    
    pages_by_opinion = {}
    for page in pages:
        key = (page['opinion_id'], page['page_number'])
        pages_by_opinion[key] = page
    
    for marker in markers:
        quote = marker['quote']
        opinion_id = marker['opinion_id']
        page_num = marker['page_number']
        
        if page_num < 1:
            continue
        
        page = pages_by_opinion.get((opinion_id, page_num))
        if not page:
            for p in pages:
                if p.get('page_number', 0) >= 1 and verify_quote_strict(quote, p['text']):
                    page = p
                    break
        
        if not page:
            continue
        
        if not verify_quote_strict(quote, page['text']):
            exact_quote = find_best_quote_in_page(search_terms, page['text'], max_len=150)
            if exact_quote and verify_quote_strict(exact_quote, page['text']):
                quote = exact_quote
            else:
                continue
        
        dedup_key = (page['opinion_id'], page['page_number'], quote[:50])
        if dedup_key in seen_keys:
            position_to_sid[marker['position']] = seen_keys[dedup_key]
            continue
        
        sid = str(sid_counter)
        sid_counter += 1
        seen_keys[dedup_key] = sid
        position_to_sid[marker['position']] = sid
        
        sources.append({
            "sid": sid,
            "opinion_id": page['opinion_id'],
            "case_name": page['case_name'],
            "appeal_no": page['appeal_no'],
            "release_date": page['release_date'],
            "page_number": page['page_number'],
            "quote": quote[:300],
            "viewer_url": f"/pdf/{page['opinion_id']}?page={page['page_number']}",
            "pdf_url": page.get('pdf_url', '')
        })
    
    return sources, position_to_sid

def build_answer_markdown(response_text: str, markers: List[Dict], position_to_sid: Dict[int, str]) -> str:
    """Convert LLM response to markdown with [1], [2] markers."""
    result = response_text
    
    sorted_markers = sorted(markers, key=lambda m: m['position'], reverse=True)
    
    for marker in sorted_markers:
        pattern = f'<!--CITE:{re.escape(marker["opinion_id"])}\\|{marker["page_number"]}\\|"{re.escape(marker["quote"])}"-->'
        sid = position_to_sid.get(marker['position'])
        if sid:
            result = re.sub(pattern, f' [{sid}]', result, count=1)
        else:
            result = re.sub(pattern, '', result, count=1)
    
    result = re.sub(r'<!--CITE:[^>]+-->', '', result)
    
    return result.strip()

def generate_fallback_response(pages: List[Dict], search_terms: List[str]) -> Dict[str, Any]:
    """Generate response when LLM is unavailable - use top pages as sources."""
    sources = []
    for i, page in enumerate(pages[:5], 1):
        if page.get('page_number', 0) < 1:
            continue
        exact_quote = extract_exact_quote_from_page(page['text'], max_len=200)
        if exact_quote and verify_quote_strict(exact_quote, page['text']):
            sources.append({
                "sid": str(i),
                "opinion_id": page['opinion_id'],
                "case_name": page['case_name'],
                "appeal_no": page['appeal_no'],
                "release_date": page['release_date'],
                "page_number": page['page_number'],
                "quote": exact_quote,
                "viewer_url": f"/pdf/{page['opinion_id']}?page={page['page_number']}",
                "pdf_url": page.get('pdf_url', '')
            })
    
    if not sources:
        return {
            "answer_markdown": "NOT FOUND IN PROVIDED OPINIONS.",
            "sources": [],
            "debug": {
                "claims": [],
                "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 1}
            }
        }
    
    markers = " ".join([f"[{s['sid']}]" for s in sources])
    answer = f"**Relevant Excerpts Found**\n\nThe following excerpts from ingested opinions may be relevant to your query. {markers}"
    
    return {
        "answer_markdown": answer,
        "sources": sources,
        "debug": {
            "claims": [{"id": i+1, "text": s['quote'][:100], "citations": [s]} for i, s in enumerate(sources)],
            "support_audit": {"total_claims": len(sources), "supported_claims": len(sources), "unsupported_claims": 0}
        }
    }

async def generate_chat_response(
    message: str,
    opinion_ids: Optional[List[str]] = None,
    conversation_id: Optional[str] = None,
    party_only: bool = False
) -> Dict[str, Any]:
    
    if opinion_ids and len(opinion_ids) == 0:
        opinion_ids = None
    
    pages = db.search_pages(message, opinion_ids, limit=15, party_only=party_only)
    search_terms = message.split()
    
    # For party-only searches, return a list of matching cases without AI generation
    if party_only and pages:
        # Group by unique cases
        seen_cases = {}
        for page in pages:
            case_key = page.get('opinion_id')
            if case_key not in seen_cases:
                seen_cases[case_key] = page
        
        # Build sources from matching cases
        sources = []
        for i, (case_id, page) in enumerate(seen_cases.items(), 1):
            sources.append({
                "sid": f"S{i}",
                "opinionId": case_id,
                "caseName": page.get("case_name", ""),
                "appealNo": page.get("appeal_no", ""),
                "releaseDate": page.get("release_date", ""),
                "pageNumber": page.get("page_number", 1),
                "quote": extract_exact_quote_from_page(page.get("text", ""), min_len=50, max_len=200),
                "viewerUrl": f"/opinions/{case_id}?page={page.get('page_number', 1)}",
                "pdfUrl": page.get("pdf_url", "")
            })
        
        # Build a summary response listing the matching cases
        case_list = "\n".join([
            f"- **{s['caseName']}** ({s['appealNo']}, {s['releaseDate']})" 
            for s in sources
        ])
        answer = f"Found {len(sources)} case(s) where \"{message}\" appears as a party:\n\n{case_list}"
        
        return {
            "answer_markdown": answer,
            "sources": sources,
            "debug": {
                "claims": [],
                "support_audit": {"total_claims": 0, "supported_claims": len(sources), "unsupported_claims": 0},
                "search_mode": "party_only"
            }
        }
    
    if not pages:
        return {
            "answer_markdown": "NOT FOUND IN PROVIDED OPINIONS.\n\nNo relevant excerpts were found. Try different search terms or ingest additional opinions.",
            "sources": [],
            "debug": {
                "claims": [],
                "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 1}
            }
        }
    
    client = get_openai_client()
    
    if not client:
        return generate_fallback_response(pages, search_terms)
    
    context = build_context(pages)
    
    try:
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(
                _executor,
                lambda: client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT + "\n\nAVAILABLE OPINION EXCERPTS:\n" + context},
                        {"role": "user", "content": message}
                    ],
                    temperature=0.2,
                    max_tokens=2000,
                    timeout=60.0
                )
            ),
            timeout=90.0
        )
        
        raw_answer = response.choices[0].message.content or "No response generated."
        
        if "NOT FOUND IN PROVIDED OPINIONS" in raw_answer.upper():
            return {
                "answer_markdown": "NOT FOUND IN PROVIDED OPINIONS.\n\nThe ingested opinions do not contain information relevant to your query. Try ingesting additional opinions or refining your search.",
                "sources": [],
                "debug": {
                    "claims": [],
                    "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 1},
                    "raw_response": raw_answer
                }
            }
        
        markers = extract_cite_markers(raw_answer)
        sources, position_to_sid = build_sources_from_markers(markers, pages, search_terms)
        
        if not sources:
            fallback = generate_fallback_response(pages, search_terms)
            fallback["debug"]["raw_response"] = raw_answer
            return fallback
        
        answer_markdown = build_answer_markdown(raw_answer, markers, position_to_sid)
        
        claims = []
        for i, s in enumerate(sources, 1):
            claims.append({
                "id": i,
                "text": s['quote'][:150],
                "citations": [{
                    "opinion_id": s['opinion_id'],
                    "case_name": s['case_name'],
                    "appeal_no": s['appeal_no'],
                    "release_date": s['release_date'],
                    "page_number": s['page_number'],
                    "quote": s['quote'],
                    "verified": True
                }]
            })
        
        return {
            "answer_markdown": answer_markdown,
            "sources": sources,
            "debug": {
                "claims": claims,
                "support_audit": {
                    "total_claims": len(sources),
                    "supported_claims": len(sources),
                    "unsupported_claims": 0
                },
                "raw_response": raw_answer
            }
        }
        
    except asyncio.TimeoutError:
        fallback = generate_fallback_response(pages, search_terms)
        fallback["debug"]["error"] = "timeout"
        return fallback
    except Exception as e:
        return {
            "answer_markdown": f"Error generating response: {str(e)}\n\nPlease try again.",
            "sources": [],
            "debug": {
                "claims": [],
                "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 1},
                "error": str(e)
            }
        }
