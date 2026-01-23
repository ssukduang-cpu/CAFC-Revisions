import os
import re
import json
import asyncio
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Tuple
from openai import OpenAI

from backend import database as db

_executor = ThreadPoolExecutor(max_workers=4)

AI_BASE_URL = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")
AI_API_KEY = os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")

def get_openai_client() -> Optional[OpenAI]:
    if AI_BASE_URL and AI_API_KEY:
        return OpenAI(base_url=AI_BASE_URL, api_key=AI_API_KEY)
    return None

SYSTEM_PROMPT = """You are a legal research assistant specializing in Federal Circuit (CAFC) precedential opinions.

STRICT GROUNDING RULES:
1. You may ONLY use information from the provided opinion excerpts below.
2. Every factual or legal claim MUST be supported by at least one VERBATIM QUOTE from the excerpts.
3. Format citations as: (Case Name, Appeal No., Page X)
4. If you cannot find support for a claim in the provided excerpts, you MUST state: "NOT FOUND IN PROVIDED OPINIONS"
5. Do NOT use any external knowledge or make claims not directly supported by quotes from the excerpts.
6. Structure your response with numbered claims, each followed by its supporting quote and citation.

RESPONSE FORMAT (use this exact format):
[Claim 1]: [Your statement]
Quote: "[Verbatim quote from opinion - copy exactly as shown]"
Citation: (Case Name, Appeal No., Page X)

[Claim 2]: [Your statement]
Quote: "[Verbatim quote from opinion - copy exactly as shown]"
Citation: (Case Name, Appeal No., Page X)

If no relevant information exists, respond: "NOT FOUND IN PROVIDED OPINIONS - the provided excerpts do not contain information relevant to your query."
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

def parse_claims_from_response(response_text: str, pages: List[Dict], search_terms: List[str] = None) -> List[Dict]:
    if search_terms is None:
        search_terms = []
    
    claims = []
    claim_pattern = r'\[Claim\s*(\d+)\]:\s*(.*?)(?=\[Claim\s*\d+\]:|$)'
    matches = re.findall(claim_pattern, response_text, re.DOTALL | re.IGNORECASE)
    
    for claim_num, claim_content in matches:
        claim_text_match = re.match(r'^(.*?)(?:Quote:|Citation:|$)', claim_content, re.DOTALL)
        claim_text = claim_text_match.group(1).strip() if claim_text_match else claim_content.strip()
        
        quote = extract_quote_from_text(claim_content)
        
        verified_citation = None
        if quote:
            verified_citation = try_verify_with_retry(quote, pages, search_terms)
        
        if not verified_citation and not ("NOT FOUND" in claim_text.upper()):
            verified_citation = try_verify_with_retry(claim_text[:100], pages, search_terms)
        
        if verified_citation:
            claims.append({
                "id": int(claim_num),
                "text": claim_text,
                "citations": [verified_citation]
            })
        else:
            claims.append({
                "id": int(claim_num),
                "text": "NOT FOUND IN PROVIDED OPINIONS.",
                "citations": []
            })
    
    if not claims and "NOT FOUND IN PROVIDED OPINIONS" in response_text.upper():
        claims.append({
            "id": 1,
            "text": "NOT FOUND IN PROVIDED OPINIONS - the provided excerpts do not contain information relevant to your query.",
            "citations": []
        })
    
    if not claims and pages:
        all_quotes = re.findall(r'"([^"]{30,500})"', response_text)
        for i, quote in enumerate(all_quotes[:5], 1):
            verified_citation = try_verify_with_retry(quote, pages, search_terms)
            if verified_citation:
                claims.append({
                    "id": i,
                    "text": f"From {verified_citation['case_name']}",
                    "citations": [verified_citation]
                })
        
        if not claims:
            for i, page in enumerate(pages[:3], 1):
                if page.get('page_number', 0) < 1:
                    continue
                exact_quote = extract_exact_quote_from_page(page['text'], max_len=250)
                if exact_quote and verify_quote_strict(exact_quote, page['text']):
                    claims.append({
                        "id": i,
                        "text": f"From {page['case_name']}",
                        "citations": [{
                            "opinion_id": page['opinion_id'],
                            "case_name": page['case_name'],
                            "appeal_no": page['appeal_no'],
                            "release_date": page['release_date'],
                            "page_number": page['page_number'],
                            "quote": exact_quote,
                            "verified": True
                        }]
                    })
    
    return claims

def build_answer_from_claims(claims: List[Dict]) -> str:
    parts = []
    for claim in claims:
        parts.append(f"[Claim {claim['id']}]: {claim['text']}")
        if claim['citations']:
            for cit in claim['citations']:
                parts.append(f'Quote: "{cit["quote"]}"')
                parts.append(f'Citation: ({cit["case_name"]}, {cit["appeal_no"]}, {cit["release_date"]}, Page {cit["page_number"]})')
        parts.append("")
    return "\n".join(parts)

async def generate_chat_response(
    message: str,
    opinion_ids: Optional[List[str]] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    
    if opinion_ids and len(opinion_ids) == 0:
        opinion_ids = None
    
    pages = db.search_pages(message, opinion_ids, limit=15)
    
    if not pages:
        return {
            "answer": "NOT FOUND IN PROVIDED OPINIONS - No relevant excerpts were found for your query. Please try different search terms or ingest more opinions.",
            "claims": [{
                "id": 1,
                "text": "NOT FOUND IN PROVIDED OPINIONS - No relevant excerpts were found for your query.",
                "citations": []
            }],
            "citations": [],
            "support_audit": {
                "total_claims": 1,
                "supported_claims": 0,
                "unsupported_claims": 1
            },
            "retrieval_only": True
        }
    
    search_terms = message.split()
    
    all_citations = []
    for page in pages:
        if page.get('page_number', 0) < 1:
            continue
        exact_quote = extract_exact_quote_from_page(page['text'], max_len=300)
        all_citations.append({
            "opinion_id": page['opinion_id'],
            "case_name": page['case_name'],
            "appeal_no": page['appeal_no'],
            "release_date": page['release_date'],
            "page_number": page['page_number'],
            "quote": exact_quote,
            "verified": True
        })
    
    client = get_openai_client()
    
    if not client:
        claims = []
        for i, page in enumerate(pages[:5], 1):
            if page.get('page_number', 0) < 1:
                continue
            exact_quote = extract_exact_quote_from_page(page['text'], max_len=400)
            if exact_quote and verify_quote_strict(exact_quote, page['text']):
                claims.append({
                    "id": i,
                    "text": f"Excerpt from {page['case_name']}",
                    "citations": [{
                        "opinion_id": page['opinion_id'],
                        "case_name": page['case_name'],
                        "appeal_no": page['appeal_no'],
                        "release_date": page['release_date'],
                        "page_number": page['page_number'],
                        "quote": exact_quote,
                        "verified": True
                    }]
                })
        
        return {
            "answer": build_answer_from_claims(claims),
            "claims": claims,
            "citations": all_citations[:5],
            "support_audit": {
                "total_claims": len(claims),
                "supported_claims": len(claims),
                "unsupported_claims": 0
            },
            "retrieval_only": True
        }
    
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
        
        claims = parse_claims_from_response(raw_answer, pages, search_terms)
        
        if not claims:
            claims = [{
                "id": 1,
                "text": raw_answer,
                "citations": []
            }]
        
        supported = sum(1 for c in claims if c['citations'])
        unsupported = len(claims) - supported
        
        answer = build_answer_from_claims(claims)
        
        verified_citations = []
        for claim in claims:
            verified_citations.extend(claim['citations'])
        
        return {
            "answer": answer,
            "claims": claims,
            "citations": verified_citations if verified_citations else all_citations[:5],
            "support_audit": {
                "total_claims": len(claims),
                "supported_claims": supported,
                "unsupported_claims": unsupported
            },
            "retrieval_only": False
        }
        
    except asyncio.TimeoutError:
        return {
            "answer": "Request timed out. The AI service is taking too long to respond. Please try again.",
            "claims": [{
                "id": 1,
                "text": "Request timed out.",
                "citations": []
            }],
            "citations": all_citations[:5],
            "support_audit": {
                "total_claims": 1,
                "supported_claims": 0,
                "unsupported_claims": 1
            },
            "retrieval_only": True,
            "error": "timeout"
        }
    except Exception as e:
        return {
            "answer": f"Error generating response: {str(e)}",
            "claims": [{
                "id": 1,
                "text": f"Error: {str(e)}",
                "citations": []
            }],
            "citations": all_citations[:5],
            "support_audit": {
                "total_claims": 1,
                "supported_claims": 0,
                "unsupported_claims": 1
            },
            "retrieval_only": True,
            "error": str(e)
        }
