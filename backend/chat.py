import os
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

RESPONSE FORMAT:
For each claim, provide:
[Claim N]: [Your statement]
Quote: "[Verbatim quote from opinion]"
Citation: (Case Name, Appeal No., Page X)

If no relevant information exists, respond: "NOT FOUND IN PROVIDED OPINIONS - the provided excerpts do not contain information relevant to your query."
"""

def build_context(pages: List[Dict]) -> str:
    context_parts = []
    for page in pages:
        context_parts.append(f"""
--- BEGIN EXCERPT ---
Case: {page['case_name']}
Appeal No: {page['appeal_no']}
Release Date: {page['release_date']}
Page: {page['page_number']}

{page['text']}
--- END EXCERPT ---
""")
    return "\n".join(context_parts)

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
            "citations": [],
            "support_audit": [],
            "retrieval_only": True
        }
    
    citations = []
    for page in pages:
        snippet = page['text'][:300].replace('\n', ' ').strip()
        citations.append({
            "case_name": page['case_name'],
            "appeal_no": page['appeal_no'],
            "release_date": page['release_date'],
            "page_number": page['page_number'],
            "quote": snippet + "..."
        })
    
    client = get_openai_client()
    
    if not client:
        answer = "RETRIEVAL-ONLY MODE (No AI model configured)\n\n"
        answer += "Relevant excerpts found:\n\n"
        for i, page in enumerate(pages[:5], 1):
            snippet = page['text'][:500].replace('\n', ' ').strip()
            answer += f"[{i}] From {page['case_name']} (Appeal No. {page['appeal_no']}, Page {page['page_number']}):\n"
            answer += f'"{snippet}..."\n\n'
        
        return {
            "answer": answer,
            "citations": citations[:5],
            "support_audit": [{"claim": f"Excerpt {i+1}", "citations": [citations[i]]} for i in range(min(5, len(citations)))],
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
        
        answer = response.choices[0].message.content or "No response generated."
        
        support_audit = []
        claims = answer.split("[Claim")
        for claim in claims[1:]:
            if "]:" in claim:
                parts = claim.split("]:", 1)
                claim_num = parts[0].strip()
                claim_text = parts[1].strip() if len(parts) > 1 else ""
                
                claim_citations = []
                for cit in citations:
                    if cit["case_name"].lower() in claim_text.lower():
                        claim_citations.append(cit)
                
                support_audit.append({
                    "claim": f"Claim {claim_num}",
                    "text": claim_text[:200],
                    "citations": claim_citations,
                    "supported": len(claim_citations) > 0 or "NOT FOUND" in claim_text.upper()
                })
        
        return {
            "answer": answer,
            "citations": citations,
            "support_audit": support_audit,
            "retrieval_only": False
        }
        
    except asyncio.TimeoutError:
        return {
            "answer": "Request timed out. The AI service is taking too long to respond. Please try again.\n\nHere are the relevant excerpts found:\n" + 
                     "\n".join([f"- {c['case_name']}, Page {c['page_number']}: \"{c['quote'][:150]}...\"" for c in citations[:3]]),
            "citations": citations[:5],
            "support_audit": [],
            "retrieval_only": True,
            "error": "timeout"
        }
    except Exception as e:
        return {
            "answer": f"Error generating response: {str(e)}\n\nFalling back to retrieval-only mode.",
            "citations": citations[:5],
            "support_audit": [],
            "retrieval_only": True,
            "error": str(e)
        }
