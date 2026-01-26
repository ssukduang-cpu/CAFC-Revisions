"""
Web Search Module for CAFC Opinion Assistant.

Provides hybrid search capability: when local retrieval confidence is low,
triggers web search via Tavily API to find relevant case citations and 
potentially ingest new cases from CourtListener.
"""

import os
import re
import httpx
import asyncio
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
COURTLISTENER_API_TOKEN = os.environ.get("COURTLISTENER_API_TOKEN")

COURTLISTENER_API_BASE = "https://www.courtlistener.com/api/rest/v4"
TAVILY_API_URL = "https://api.tavily.com/search"

CONFIDENCE_THRESHOLD = 0.6

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def extract_case_citations(text: str) -> List[Dict[str, str]]:
    """
    Extract case names and citations from search result text.
    Returns list of dicts with case_name and citation fields.
    """
    extracted = []
    
    full_case_pattern = r'([A-Z][a-zA-Z0-9\s\.\-&,\'()]+?(?:Inc\.|Corp\.|LLC|L\.?C\.?|Co\.|Ltd\.)?)\s+v\.\s+([A-Z][a-zA-Z0-9\s\.\-&,\'()]+?(?:Inc\.|Corp\.|LLC|L\.?C\.?|Co\.|Ltd\.))(?:\s*,\s*(?:No\.\s*[\d\-]+))?(?:\s*,?\s*(\d{3}\s+F\.(?:2d|3d)\s+\d+|\d{3}\s+U\.S\.\s+\d+))?'
    matches = re.findall(full_case_pattern, text)
    
    for match in matches:
        plaintiff = match[0].strip().rstrip(',.')
        defendant = match[1].strip().rstrip(',.')
        citation = match[2].strip() if len(match) > 2 and match[2] else None
        
        if len(plaintiff) < 2 or len(defendant) < 2:
            continue
        if len(plaintiff) > 80 or len(defendant) > 80:
            continue
            
        case_name = f"{plaintiff} v. {defendant}"
        extracted.append({
            "case_name": case_name,
            "citation": citation,
            "plaintiff": plaintiff,
            "defendant": defendant
        })
    
    simple_pattern = r'([A-Z][a-zA-Z\.\-]+(?:\s+[A-Z][a-zA-Z\.\-]+)*)\s+v\.\s+([A-Z][a-zA-Z\.\-]+(?:\s+[a-zA-Z\.\-]+)*)'
    simple_matches = re.findall(simple_pattern, text)
    for match in simple_matches:
        plaintiff = match[0].strip()
        defendant = match[1].strip()
        
        if len(plaintiff) < 2 or len(defendant) < 2:
            continue
        if len(plaintiff) > 40 or len(defendant) > 40:
            continue
        
        case_name = f"{plaintiff} v. {defendant}"
        if not any(c.get("case_name") == case_name for c in extracted):
            extracted.append({
                "case_name": case_name,
                "citation": None,
                "plaintiff": plaintiff,
                "defendant": defendant
            })
    
    fed_cir_pattern = r'(\d{3})\s+(F\.(?:2d|3d))\s+(\d+)'
    cites = re.findall(fed_cir_pattern, text)
    for vol, reporter, page in cites:
        cite_str = f"{vol} {reporter} {page}"
        if not any(c.get("citation") == cite_str for c in extracted):
            extracted.append({
                "case_name": None,
                "citation": cite_str,
                "volume": vol,
                "reporter": reporter,
                "page": page
            })
    
    return extracted


def extract_legal_topics(query: str) -> List[str]:
    """
    Extract legal topics from user query for targeted search.
    """
    topics = []
    
    topic_patterns = {
        "certificate_of_correction": [r"certificate\s+of\s+correction", r"§\s*254", r"§\s*255", r"35\s+U\.?S\.?C\.?\s*§?\s*254", r"35\s+U\.?S\.?C\.?\s*§?\s*255"],
        "patent_eligibility": [r"§\s*101", r"35\s+U\.?S\.?C\.?\s*§?\s*101", r"abstract\s+idea", r"alice", r"mayo"],
        "obviousness": [r"§\s*103", r"35\s+U\.?S\.?C\.?\s*§?\s*103", r"obviousness", r"ksr", r"graham"],
        "claim_construction": [r"claim\s+construction", r"markman", r"phillips"],
        "infringement": [r"infringement", r"doctrine\s+of\s+equivalents", r"literal\s+infringement"],
        "written_description": [r"§\s*112", r"written\s+description", r"enablement"],
        "willfulness": [r"willful", r"enhanced\s+damages", r"halo", r"seagate"],
    }
    
    query_lower = query.lower()
    for topic, patterns in topic_patterns.items():
        for pattern in patterns:
            if re.search(pattern, query_lower, re.IGNORECASE):
                topics.append(topic)
                break
    
    return list(set(topics))


async def search_tavily(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Search Tavily API for legal information.
    Focuses on legal repositories and CourtListener.
    """
    if not TAVILY_API_KEY:
        return {"success": False, "error": "TAVILY_API_KEY not configured"}
    
    legal_query = f"Federal Circuit CAFC patent law {query}"
    
    topics = extract_legal_topics(query)
    if "certificate_of_correction" in topics:
        legal_query = f"35 USC 254 255 certificate of correction patent {query}"
    
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": legal_query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_domains": [
            "courtlistener.com",
            "scholar.google.com",
            "law.cornell.edu",
            "cafc.uscourts.gov",
            "casetext.com",
            "law.justia.com"
        ],
        "include_answer": True,
        "include_raw_content": False
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(TAVILY_API_URL, json=payload)
            response.raise_for_status()
            data = response.json()
            
            results = data.get("results", [])
            answer = data.get("answer", "")
            
            all_citations = []
            for result in results:
                content = result.get("content", "") + " " + result.get("title", "")
                citations = extract_case_citations(content)
                for citation in citations:
                    citation["source_url"] = result.get("url", "")
                    citation["source_title"] = result.get("title", "")
                all_citations.extend(citations)
            
            if answer:
                answer_citations = extract_case_citations(answer)
                all_citations.extend(answer_citations)
            
            unique_cases = {}
            for citation in all_citations:
                key = citation.get("case_name") or citation.get("citation")
                if key and key not in unique_cases:
                    unique_cases[key] = citation
            
            return {
                "success": True,
                "query": legal_query,
                "answer": answer,
                "results": results,
                "extracted_cases": list(unique_cases.values()),
                "topics_detected": topics
            }
            
    except httpx.HTTPStatusError as e:
        logger.error(f"Tavily API error: {e}")
        return {"success": False, "error": f"HTTP error: {e.response.status_code}"}
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        return {"success": False, "error": str(e)}


async def search_courtlistener(case_name: str) -> Optional[Dict[str, Any]]:
    """
    Search CourtListener for a specific case by name.
    Returns case metadata if found.
    """
    if not COURTLISTENER_API_TOKEN:
        logger.warning("COURTLISTENER_API_TOKEN not configured")
    
    headers = {
        "Authorization": f"Token {COURTLISTENER_API_TOKEN}" if COURTLISTENER_API_TOKEN else "",
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            search_url = f"{COURTLISTENER_API_BASE}/search/"
            params = {
                "q": case_name,
                "court": "cafc",
                "type": "o",
                "stat_Precedential": "on",
                "order_by": "score desc"
            }
            
            response = await client.get(search_url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            results = data.get("results", [])
            if not results:
                return None
            
            best_match = results[0]
            cluster_id = best_match.get("cluster_id")
            
            return {
                "cluster_id": cluster_id,
                "case_name": best_match.get("caseName", ""),
                "date_filed": best_match.get("dateFiled", ""),
                "docket_number": best_match.get("docketNumber", ""),
                "citation": best_match.get("citation", []),
                "pdf_url": f"https://www.courtlistener.com/pdf/{cluster_id}/" if cluster_id else None,
                "courtlistener_url": f"https://www.courtlistener.com/opinion/{cluster_id}/" if cluster_id else None,
                "snippet": best_match.get("snippet", "")
            }
            
    except Exception as e:
        logger.error(f"CourtListener search failed: {e}")
        return None


async def find_and_prepare_cases(
    query: str, 
    local_results: List[Dict[str, Any]],
    confidence_threshold: float = CONFIDENCE_THRESHOLD
) -> Dict[str, Any]:
    """
    Main entry point for hybrid search.
    
    1. Check if local results have sufficient confidence
    2. If not, trigger web search via Tavily
    3. Extract case citations from web results
    4. Look up cases in CourtListener
    5. Return list of cases ready for ingestion
    
    Args:
        query: User's legal question
        local_results: Results from local FTS search
        confidence_threshold: Minimum score to skip web search
        
    Returns:
        Dict with web search results and cases to potentially ingest
    """
    max_local_score = 0.0
    if local_results:
        scores = [r.get("score", 0) for r in local_results if isinstance(r.get("score"), (int, float))]
        max_local_score = max(scores) if scores else 0.0
    
    if local_results and max_local_score > confidence_threshold:
        return {
            "web_search_triggered": False,
            "reason": f"Local confidence {max_local_score:.2f} > threshold {confidence_threshold}",
            "cases_to_ingest": []
        }
    
    logger.info(f"Low local confidence ({max_local_score:.2f}), triggering web search...")
    
    tavily_results = await search_tavily(query)
    
    if not tavily_results.get("success"):
        return {
            "web_search_triggered": True,
            "success": False,
            "error": tavily_results.get("error"),
            "cases_to_ingest": []
        }
    
    extracted_cases = tavily_results.get("extracted_cases", [])
    cases_to_ingest = []
    
    for case_info in extracted_cases[:5]:
        case_name = case_info.get("case_name")
        if not case_name:
            continue
        
        cl_result = await search_courtlistener(case_name)
        if cl_result and cl_result.get("cluster_id"):
            cases_to_ingest.append({
                "case_name": cl_result["case_name"],
                "cluster_id": cl_result["cluster_id"],
                "pdf_url": cl_result["pdf_url"],
                "courtlistener_url": cl_result["courtlistener_url"],
                "date_filed": cl_result.get("date_filed"),
                "source": "web_search",
                "search_query": query
            })
        
        await asyncio.sleep(0.5)
    
    return {
        "web_search_triggered": True,
        "success": True,
        "tavily_answer": tavily_results.get("answer", ""),
        "topics_detected": tavily_results.get("topics_detected", []),
        "extracted_cases_count": len(extracted_cases),
        "cases_to_ingest": cases_to_ingest,
        "web_results": tavily_results.get("results", [])[:3]
    }


async def ingest_discovered_case(
    case_info: Dict[str, Any],
    db_module
) -> Dict[str, Any]:
    """
    Ingest a case discovered via web search.
    
    Args:
        case_info: Dict with cluster_id, pdf_url, case_name from CourtListener
        db_module: Database module for document operations
        
    Returns:
        Ingestion result
    """
    from backend.ingest.ingest_document import ingest_document_from_url
    
    cluster_id = case_info.get("cluster_id")
    pdf_url = case_info.get("pdf_url")
    case_name = case_info.get("case_name", "Unknown Case")
    
    if not cluster_id or not pdf_url:
        return {"success": False, "error": "Missing cluster_id or pdf_url"}
    
    with db_module.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM documents WHERE courtlistener_cluster_id = %s",
            (cluster_id,)
        )
        existing = cursor.fetchone()
        if existing:
            return {
                "success": True,
                "already_exists": True,
                "document_id": existing["id"],
                "case_name": case_name
            }
    
    try:
        result = await ingest_document_from_url(
            pdf_url=pdf_url,
            case_name=case_name,
            cluster_id=cluster_id,
            source="web_search"
        )
        
        if result.get("success"):
            with db_module.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO web_search_ingests 
                    (document_id, case_name, cluster_id, search_query, ingested_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT DO NOTHING
                """, (
                    result.get("document_id"),
                    case_name,
                    cluster_id,
                    case_info.get("search_query", "")
                ))
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to ingest discovered case {case_name}: {e}")
        return {"success": False, "error": str(e)}


def should_trigger_web_search(
    local_results: List[Dict[str, Any]],
    query: str
) -> Tuple[bool, str]:
    """
    Determine whether to trigger web search based on local results and query.
    
    Returns:
        Tuple of (should_search, reason)
    """
    if not local_results:
        return True, "No local results found"
    
    max_score = max((r.get("score", 0) for r in local_results), default=0)
    if max_score < CONFIDENCE_THRESHOLD:
        return True, f"Low confidence score ({max_score:.2f} < {CONFIDENCE_THRESHOLD})"
    
    topics = extract_legal_topics(query)
    specialized_topics = ["certificate_of_correction"]
    if any(t in topics for t in specialized_topics):
        if max_score < 0.8:
            return True, f"Specialized topic detected with moderate confidence ({max_score:.2f})"
    
    return False, f"Sufficient local confidence ({max_score:.2f})"
