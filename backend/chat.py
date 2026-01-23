import os
import re
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional
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

def normalize_text(text: str) -> str:
    text = re.sub(r'\s+', ' ', text)
    text = text.strip().lower()
    text = re.sub(r'[^\w\s]', '', text)
    return text

def get_words(text: str) -> List[str]:
    return normalize_text(text).split()

def verify_quote_in_page(quote: str, page_text: str) -> bool:
    norm_quote = normalize_text(quote)
    norm_page = normalize_text(page_text)
    
    if len(norm_quote) < 15:
        return False
    
    if norm_quote in norm_page:
        return True
    
    quote_words = get_words(quote)
    page_words = set(get_words(page_text))
    
    if len(quote_words) < 5:
        return False
    
    matching_words = sum(1 for w in quote_words if w in page_words and len(w) > 3)
    match_ratio = matching_words / len(quote_words)
    
    return match_ratio >= 0.6

def find_matching_page(quote: str, pages: List[Dict]) -> Optional[Dict]:
    best_match = None
    best_score = 0
    
    for page in pages:
        if verify_quote_in_page(quote, page['text']):
            quote_words = get_words(quote)
            page_words = set(get_words(page['text']))
            matching = sum(1 for w in quote_words if w in page_words and len(w) > 3)
            score = matching / max(1, len(quote_words))
            if score > best_score:
                best_score = score
                best_match = page
    
    return best_match

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

def parse_claims_from_response(response_text: str, pages: List[Dict]) -> List[Dict]:
    claims = []
    claim_pattern = r'\[Claim\s*(\d+)\]:\s*(.*?)(?=\[Claim\s*\d+\]:|$)'
    matches = re.findall(claim_pattern, response_text, re.DOTALL | re.IGNORECASE)
    
    for claim_num, claim_content in matches:
        claim_text_match = re.match(r'^(.*?)(?:Quote:|Citation:|$)', claim_content, re.DOTALL)
        claim_text = claim_text_match.group(1).strip() if claim_text_match else claim_content.strip()
        
        quote = extract_quote_from_text(claim_content)
        
        verified_citations = []
        unverified_quote = None
        
        if quote:
            matching_page = find_matching_page(quote, pages)
            if matching_page:
                verified_citations.append({
                    "opinion_id": matching_page['opinion_id'],
                    "case_name": matching_page['case_name'],
                    "appeal_no": matching_page['appeal_no'],
                    "release_date": matching_page['release_date'],
                    "page_number": matching_page['page_number'],
                    "quote": quote[:500],
                    "verified": True
                })
            else:
                unverified_quote = quote
        
        if not verified_citations and "NOT FOUND" in claim_text.upper():
            pass
        elif not verified_citations and unverified_quote:
            verified_citations.append({
                "opinion_id": "",
                "case_name": "Unverified",
                "appeal_no": "",
                "release_date": "",
                "page_number": 0,
                "quote": unverified_quote[:500],
                "verified": False
            })
        
        claims.append({
            "id": int(claim_num),
            "text": claim_text,
            "citations": verified_citations
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
            matching_page = find_matching_page(quote, pages)
            if matching_page:
                claims.append({
                    "id": i,
                    "text": f"From {matching_page['case_name']}",
                    "citations": [{
                        "opinion_id": matching_page['opinion_id'],
                        "case_name": matching_page['case_name'],
                        "appeal_no": matching_page['appeal_no'],
                        "release_date": matching_page['release_date'],
                        "page_number": matching_page['page_number'],
                        "quote": quote[:500],
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
    
    all_citations = []
    for page in pages:
        snippet = page['text'][:300].replace('\n', ' ').strip()
        all_citations.append({
            "opinion_id": page['opinion_id'],
            "case_name": page['case_name'],
            "appeal_no": page['appeal_no'],
            "release_date": page['release_date'],
            "page_number": page['page_number'],
            "quote": snippet + "..."
        })
    
    client = get_openai_client()
    
    if not client:
        claims = []
        for i, page in enumerate(pages[:5], 1):
            snippet = page['text'][:500].replace('\n', ' ').strip()
            claims.append({
                "id": i,
                "text": f"Excerpt from {page['case_name']}",
                "citations": [{
                    "opinion_id": page['opinion_id'],
                    "case_name": page['case_name'],
                    "appeal_no": page['appeal_no'],
                    "release_date": page['release_date'],
                    "page_number": page['page_number'],
                    "quote": snippet,
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
        
        claims = parse_claims_from_response(raw_answer, pages)
        
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
