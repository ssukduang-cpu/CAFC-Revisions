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

SYSTEM_PROMPT = """You are an experienced Federal Circuit patent litigator providing concise legal research summaries.

STRICT GROUNDING RULES:
1. You may ONLY use information from the provided opinion excerpts below.
2. Every statement MUST be supported by at least one VERBATIM QUOTE from the excerpts.
3. If you cannot find support in the provided excerpts, respond ONLY with: "NOT FOUND IN PROVIDED OPINIONS."
4. Do NOT use any external knowledge or make claims not directly supported by quotes from the excerpts.

RESPONSE STYLE (Patent Litigator Voice):
Write naturally as a Federal Circuit practitioner would brief a colleague. Use these sections ONLY if you have verified supporting quotes:

**Bottom Line**
1-2 sentences summarizing the key holding.

**What the Court Held**
Short paragraphs explaining the legal analysis, weaving in short inline quotes.

**Practice Note** (optional - only if directly supported)
Practical implications for patent practitioners.

CRITICAL FORMATTING:
- Weave short quotes naturally into sentences using quotation marks.
- After EACH statement, include a hidden citation marker in this format: <!--CITE:opinion_id|page_number|"exact quote"-->
- The quote in the marker must be a VERBATIM substring from the excerpt (copy exactly).
- Do NOT use numbered claim labels like [Claim 1] in your response.
- Keep quotes short (under 100 characters when possible) and relevant.

EXAMPLE:
**Bottom Line**
The Federal Circuit held that means-plus-function claims require corresponding structure in the specification. <!--CITE:abc123|5|"means-plus-function claims require corresponding structure in the specification"-->

**What the Court Held**
The court emphasized that "a patent must describe the claimed invention in sufficient detail" to enable a skilled artisan. <!--CITE:abc123|7|"a patent must describe the claimed invention in sufficient detail"-->

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
        
        sid = f"S{sid_counter}"
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
    """Convert LLM response to markdown with [S1], [S2] markers."""
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
                "sid": f"S{i}",
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
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    
    if opinion_ids and len(opinion_ids) == 0:
        opinion_ids = None
    
    pages = db.search_pages(message, opinion_ids, limit=15)
    search_terms = message.split()
    
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
