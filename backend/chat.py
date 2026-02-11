import os
import re
import json
import asyncio
import logging
import importlib.util
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import List, Dict, Any, Optional, Tuple
try:
    import tiktoken
except Exception:
    tiktoken = None

try:
    from backend import db_postgres as db
except ModuleNotFoundError:
    db = None

from backend import web_search
from backend import ranking_scorer
from backend import voyager
from backend.disambiguation import detect_option_reference, resolve_candidate_reference, is_probable_disambiguation_followup

_executor = ThreadPoolExecutor(max_workers=4)


async def try_web_search_and_ingest(query: str, conversation_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Attempt to find relevant cases via web search when local results are insufficient.
    If cases are found on CourtListener, ingest them and return new pages.
    
    This implements the Search-to-Ingest loop:
    1. Search Tavily for case citations
    2. Look up cases in CourtListener
    3. Ingest any new cases found
    4. Wait for ingestion to complete with readable text
    5. Re-query local database with new content
    """
    try:
        logging.info(f"Starting web search for: {query[:80]}...")
        search_result = await web_search.find_and_prepare_cases(
            query=query,
            local_results=[],
            confidence_threshold=0.0
        )
        
        if not search_result.get("web_search_triggered"):
            return {"web_search_triggered": False}
        
        if not search_result.get("success"):
            return {
                "web_search_triggered": True,
                "success": False,
                "error": search_result.get("error"),
                "tavily_answer": search_result.get("tavily_answer", "")
            }
        
        cases_to_ingest = search_result.get("cases_to_ingest", [])
        if not cases_to_ingest:
            return {
                "web_search_triggered": True,
                "success": False,
                "tavily_answer": search_result.get("tavily_answer", ""),
                "cases_to_ingest": []
            }
        
        ingested_cases = []
        cases_found = []
        
        for case_info in cases_to_ingest[:3]:
            cluster_id = case_info.get("cluster_id")
            case_name = case_info.get("case_name", "Unknown Case")
            cases_found.append(case_name)
            
            if not cluster_id:
                logging.warning(f"No cluster_id for case: {case_name}")
                continue
            
            # Check if already exists
            existing = db.check_document_exists_by_cluster_id(cluster_id)
            if existing:
                if existing.get("ingested"):
                    ingested_cases.append({
                        "case_name": existing.get("case_name"),
                        "document_id": existing.get("id"),
                        "already_existed": True,
                        "status": "completed"
                    })
                    logging.info(f"Case already ingested: {case_name}")
                continue
            
            try:
                from backend.ingest import ingest_document_from_url
                
                logging.info(f"Learning case: {case_name}...")
                
                ingest_result = await ingest_document_from_url(
                    pdf_url=case_info.get("pdf_url"),
                    case_name=case_name,
                    cluster_id=cluster_id,
                    courtlistener_url=case_info.get("courtlistener_url"),
                    source="web_search"
                )
                
                doc_id = ingest_result.get("document_id")
                status = ingest_result.get("status", "unknown")
                
                if ingest_result.get("success") and status == "completed":
                    # Verify ingestion by checking for readable chunks
                    await asyncio.sleep(0.5)  # Brief pause for DB commit
                    
                    # Poll for ingestion completion with timeout
                    max_wait = 5.0
                    start_time = asyncio.get_event_loop().time()
                    ingestion_verified = False
                    
                    while (asyncio.get_event_loop().time() - start_time) < max_wait:
                        doc = db.get_document(doc_id) if doc_id else None
                        if doc and doc.get("ingested"):
                            # Verify we have chunks by document ID (more reliable than name search)
                            chunk_count = db.count_document_chunks(doc_id) if doc_id else 0
                            if chunk_count > 0:
                                ingestion_verified = True
                                break
                        await asyncio.sleep(0.5)
                    
                    if ingestion_verified:
                        db.record_web_search_ingest(
                            document_id=doc_id,
                            case_name=case_name,
                            cluster_id=cluster_id,
                            search_query=query
                        )
                        ingested_cases.append({
                            "case_name": case_name,
                            "document_id": doc_id,
                            "newly_ingested": True,
                            "status": "completed",
                            "num_pages": ingest_result.get("num_pages", 0)
                        })
                        logging.info(f"Successfully ingested: {case_name} ({ingest_result.get('num_pages', 0)} pages)")
                    else:
                        logging.warning(f"Ingestion verification failed for: {case_name}")
                        ingested_cases.append({
                            "case_name": case_name,
                            "document_id": doc_id,
                            "status": "verification_failed"
                        })
                        
                elif status == "ocr_required":
                    logging.warning(f"OCR required for: {case_name}")
                    ingested_cases.append({
                        "case_name": case_name,
                        "document_id": doc_id,
                        "status": "ocr_required",
                        "error": "Scanned PDF - OCR not yet supported"
                    })
                elif status == "already_exists":
                    ingested_cases.append({
                        "case_name": case_name,
                        "document_id": doc_id,
                        "already_existed": True,
                        "status": "completed"
                    })
                else:
                    logging.error(f"Ingestion failed for {case_name}: {ingest_result.get('error', status)}")
                    ingested_cases.append({
                        "case_name": case_name,
                        "status": status,
                        "error": ingest_result.get("error")
                    })
                    
            except Exception as e:
                logging.error(f"Failed to ingest {case_name}: {e}")
                ingested_cases.append({
                    "case_name": case_name,
                    "status": "error",
                    "error": str(e)
                })
                continue
        
        # Check if we have any successfully ingested cases
        successful_ingests = [c for c in ingested_cases if c.get("status") == "completed"]
        
        if successful_ingests:
            # Re-query with new content
            new_pages = db.search_pages(query, None, limit=15, party_only=False)
            logging.info(f"Web search complete: {len(successful_ingests)} cases ingested, {len(new_pages)} pages retrieved")
            return {
                "web_search_triggered": True,
                "success": True,
                "ingested_cases": ingested_cases,
                "cases_found": cases_found,
                "new_pages": new_pages,
                "tavily_answer": search_result.get("tavily_answer", "")
            }
        
        return {
            "web_search_triggered": True,
            "success": False,
            "ingested_cases": ingested_cases,
            "cases_found": cases_found,
            "tavily_answer": search_result.get("tavily_answer", ""),
            "cases_to_ingest": cases_to_ingest
        }
        
    except Exception as e:
        logging.error(f"Web search failed: {e}")
        import traceback
        traceback.print_exc()
        return {"web_search_triggered": False, "error": str(e)}

# LRU Cache for frequently cited legal definitions (bypass DB for common queries)
@lru_cache(maxsize=50)
def get_cached_legal_definition(term: str) -> Optional[str]:
    """
    Cache common legal test definitions that are frequently cited.
    These are well-established Federal Circuit standards that don't change.
    """
    common_definitions = {
        "alice_mayo": """The Alice/Mayo framework for patent eligibility under 35 U.S.C. § 101:
Step 1: Determine whether the claims are directed to a patent-ineligible concept (abstract idea, law of nature, or natural phenomenon).
Step 2A: If yes, determine whether the claim elements, individually or as an ordered combination, transform the nature of the claim into a patent-eligible application.
Step 2B: Search for an "inventive concept" that is sufficient to transform the abstract idea into a patent-eligible application.""",
        
        "obviousness": """The Graham v. John Deere framework for obviousness under 35 U.S.C. § 103:
1. Determine the scope and content of the prior art
2. Ascertain the differences between the prior art and the claims at issue
3. Resolve the level of ordinary skill in the pertinent art
4. Consider objective indicia of nonobviousness (secondary considerations)""",
        
        "claim_construction": """The claim construction standard under Phillips v. AWH Corp.:
Claims are construed from the perspective of a person of ordinary skill in the art at the time of invention.
Intrinsic evidence (claim language, specification, prosecution history) is primary.
Extrinsic evidence (dictionaries, expert testimony) is secondary.""",
        
        "willful_infringement": """The Halo Electronics standard for willful infringement:
Enhanced damages under § 284 require showing that the infringement was willful - 
i.e., that the infringer acted despite an objectively high likelihood that its actions 
constituted infringement of a valid patent, and this risk was either known or so obvious 
that it should have been known."""
    }
    
    # Normalize the term for lookup
    term_normalized = term.lower().replace(" ", "_").replace("-", "_")
    
    for key, definition in common_definitions.items():
        if key in term_normalized or term_normalized in key:
            return definition
    
    return None

def build_conversation_summary(conversation_id: str, max_turns: int = 3) -> str:
    """
    Build a condensed summary of the last N conversation turns.
    This maintains legal context awareness across multi-turn conversations.
    Reduced to 3 turns to avoid history bloat - legal follow-ups rarely need more context.
    """
    if not conversation_id:
        return ""
    
    try:
        messages = db.get_messages(conversation_id)
        if not messages or len(messages) < 2:
            return ""
        
        # Get last N turns (a turn = user message + assistant response)
        recent_messages = messages[-(max_turns * 2):]
        
        summary_parts = []
        current_topic = None
        mentioned_cases = set()
        mentioned_issues = set()
        
        for msg in recent_messages:
            role = msg.get('role', '')
            content = msg.get('content', '')[:500]  # Truncate long messages
            
            if role == 'user':
                summary_parts.append(f"User asked: {content[:200]}")
            elif role == 'assistant':
                # Extract key legal elements from assistant responses
                # Look for case names (pattern: word v. word)
                case_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+v\.\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b'
                cases = re.findall(case_pattern, content)
                for case in cases:
                    mentioned_cases.add(f"{case[0]} v. {case[1]}")
                
                # Look for legal issues (101, 102, 103, 112, claim construction, etc.)
                if '101' in content or 'eligibility' in content.lower():
                    mentioned_issues.add('patent eligibility (§ 101)')
                if '103' in content or 'obviousness' in content.lower():
                    mentioned_issues.add('obviousness (§ 103)')
                if '102' in content or 'anticipation' in content.lower():
                    mentioned_issues.add('anticipation (§ 102)')
                if 'claim construction' in content.lower():
                    mentioned_issues.add('claim construction')
        
        if not summary_parts and not mentioned_cases:
            return ""
        
        summary = "LEGAL CONTEXT FROM PRIOR TURNS:\n"
        
        if mentioned_cases:
            summary += f"Cases discussed: {', '.join(list(mentioned_cases)[:5])}\n"
        
        if mentioned_issues:
            summary += f"Legal issues: {', '.join(mentioned_issues)}\n"
        
        if summary_parts:
            summary += f"Recent context: {summary_parts[-1]}\n"
        
        return summary + "\n"
    
    except Exception as e:
        logging.warning(f"Could not build conversation summary: {e}")
        return ""


def add_pdf_links_to_sources(sources: List[Dict]) -> List[Dict]:
    """Add clickable PDF links to each source.
    
    Enriches sources with pdf_url field for frontend rendering.
    Format: /pdf/{opinion_id}?page={page_number}
    """
    enriched = []
    for source in sources:
        opinion_id = source.get("opinion_id") or source.get("opinionId")
        page_number = source.get("page_number") or source.get("pageNumber", 1)
        
        enriched_source = dict(source)
        if opinion_id:
            enriched_source["pdf_url"] = f"/pdf/{opinion_id}?page={page_number}"
        enriched.append(enriched_source)
    
    return enriched


def clean_case_name(case_name: str) -> str:
    """Clean case name by removing document type suffixes like [OPINION], [ORDER], etc."""
    import re
    if not case_name:
        return "Unknown Case"
    # Remove common document type suffixes
    cleaned = re.sub(r'\s*\[(OPINION|ORDER|ERRATA|JUDGMENT|DECISION)\]\s*$', '', case_name, flags=re.IGNORECASE)
    return cleaned.strip() or "Unknown Case"


def make_citations_clickable(answer_markdown: str, quote_registry: Dict[str, Dict], sources: Optional[List[Dict]] = None) -> str:
    """Replace [Q#] and [#] references in answer with clean clickable citations.
    
    Format: ([1] *Case Name*) - number is clickable link, case name in italics
    The Q# values are renumbered sequentially starting at 1 for each response.
    """
    import re
    
    # Track Q# citations in order of appearance and renumber them
    q_citation_map = {}  # Maps original Q# -> (new_number, case_name, pdf_url)
    citation_counter = [0]  # Use list for closure modification
    
    def get_citation_info(quote_id: str) -> tuple:
        """Get or assign citation info for a Q# citation."""
        if quote_id not in q_citation_map:
            citation_counter[0] += 1
            info = quote_registry.get(quote_id, {})
            opinion_id = info.get("opinion_id", "")
            page_number = info.get("page_number", 1)
            case_name = clean_case_name(info.get("case_name", "Unknown Case"))
            pdf_url = f"/pdf/{opinion_id}?page={page_number}" if opinion_id else ""
            q_citation_map[quote_id] = (citation_counter[0], case_name, pdf_url)
        return q_citation_map[quote_id]
    
    def replace_q_citation(match):
        quote_id = match.group(1)  # e.g., "Q1", "Q120"
        clean_num, case_name, pdf_url = get_citation_info(quote_id)
        # Format: ([1] *Case Name*) - frontend handles PDF links via sources array
        return f"([{clean_num}] *{case_name}*)"
    
    def replace_numeric_citation(match):
        num_str = match.group(1)  # e.g., "1", "2"
        full_ref = match.group(0)  # e.g., "[1]"
        
        if sources:
            idx = int(num_str) - 1  # Sources are 1-indexed in citations
            if 0 <= idx < len(sources):
                source = sources[idx]
                case_name = clean_case_name(source.get("case_name", "Unknown Case"))
                # Format: ([1] *Case Name*) - frontend handles PDF links via sources array
                return f"([{num_str}] *{case_name}*)"
        
        return full_ref
    
    # First, replace [Q1], [Q2], [Q120], etc. with clean case name links
    q_pattern = r'\[(Q\d+)\]'
    result = re.sub(q_pattern, replace_q_citation, answer_markdown)
    
    # Then, replace [1], [2], etc. that aren't already linked
    # Avoid matching already-linked citations by checking for no ( after ]
    num_pattern = r'\[(\d+)\](?!\()'
    result = re.sub(num_pattern, replace_numeric_citation, result)
    
    return result


def standardize_response(response: Dict[str, Any], web_search_result: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Standardize chat response by promoting debug fields to top-level.
    Ensures consistent schema: return_branch, markers_count, sources_count at top level.
    Also promotes web_search info and controlling_authorities if provided.
    Enriches sources with PDF links for clickable citations.
    """
    debug = response.get("debug", {})
    
    # Promote key observability fields to top-level
    response["return_branch"] = debug.get("return_branch", "unknown")
    response["markers_count"] = debug.get("markers_count", 0)
    response["sources_count"] = debug.get("sources_count", 0)
    
    # Ensure controlling_authorities is always present (empty array if not set)
    # These are SEPARATE from sources - recommended framework cases for the doctrine
    if "controlling_authorities" not in response:
        response["controlling_authorities"] = []
    
    # Enrich sources with PDF links for clickable citations
    if "sources" in response and isinstance(response["sources"], list):
        response["sources"] = add_pdf_links_to_sources(response["sources"])
    
    # Promote web search info to top-level for UI consumption
    if web_search_result:
        response["web_search_triggered"] = web_search_result.get("web_search_triggered", False)
        response["web_search_cases"] = [
            c.get("case_name", "Unknown") for c in web_search_result.get("ingested_cases", [])
            if c.get("status") == "completed"
        ]
    elif response.get("web_search_triggered"):
        # Already set in response
        pass
    else:
        response["web_search_triggered"] = False
        response["web_search_cases"] = []
    
    return response

AI_BASE_URL = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")
AI_API_KEY = os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")

def _get_openai_class():
    """Return OpenAI class if dependency is installed, else None.

    Keeps module importable in lightweight test environments where `openai`
    may not be installed.
    """
    if importlib.util.find_spec("openai") is None:
        return None
    from openai import OpenAI
    return OpenAI


def get_openai_client() -> Optional[Any]:
    OpenAI = _get_openai_class()
    if OpenAI is None:
        return None
    if AI_BASE_URL and AI_API_KEY:
        return OpenAI(base_url=AI_BASE_URL, api_key=AI_API_KEY)
    return None


def expand_query_with_legal_terms(query: str, client: Optional[Any] = None) -> List[str]:
    """Use GPT-4o to expand a conceptual query with related legal keywords.
    
    Returns a list of 5 related legal search terms for better FTS matching.
    Example: "after-arising technology" -> ["later-developed technology", "nascent technology", 
             "enablement time of filing", "commensurate scope claims", "written description"]
    """
    if not client:
        client = get_openai_client()
    if not client:
        return []
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """You are a Federal Circuit patent law expert. Given a legal query, generate 5 related legal search terms that would help find relevant case law.

Focus on:
- Synonyms and alternate phrasings of legal concepts
- Related doctrines or tests
- Key phrases from seminal cases
- Statutory language equivalents

Output ONLY the 5 terms, one per line, no numbers or bullets. Keep each term short (2-5 words)."""
                },
                {
                    "role": "user", 
                    "content": f"Generate 5 related legal search terms for: {query}"
                }
            ],
            max_tokens=150,
            temperature=0.3
        )
        
        terms = response.choices[0].message.content.strip().split('\n')
        terms = [t.strip() for t in terms if t.strip()][:5]
        logging.info(f"Query expansion: '{query[:40]}...' -> {terms}")
        return terms
    except Exception as e:
        logging.warning(f"Query expansion failed: {e}")
        return []

SYSTEM_PROMPT = """You are a senior U.S. appellate law clerk and patent litigator assisting with Federal Circuit and district-court patent matters.

Your primary obligation is to provide correct, usable legal doctrine and reasoning.
Document retrieval and case excerpts are SUPPORTING tools, not prerequisites for answering.

────────────────────────────────────────────────────
QUESTION-TYPE CLASSIFICATION (MANDATORY)
────────────────────────────────────────────────────
Before answering, silently classify the user's query as one or more of the following:

1. Doctrinal / black-letter law
2. Procedural or standard-of-review
3. Case-specific analysis
4. Multi-case synthesis
5. Fact-dependent application

If the query is (1) or (2):
• Answer directly from settled law and doctrine.
• DO NOT require the user to select a specific case.
• DO NOT respond with "ambiguous query," "multiple matches," or "not found."

If the query is (3):
• Ask for clarification only if a specific case is genuinely necessary.

If the query is (4) or (5):
• Synthesize across relevant authority unless the user explicitly requests a single case.

────────────────────────────────────────────────────
LEGAL-REASONING PRIORITY RULE
────────────────────────────────────────────────────
Legal reasoning always supersedes document matching.

Apply this hierarchy:
1. Statutory text and black-letter doctrine
2. Binding Supreme Court and Federal Circuit precedent
3. Representative cases (illustrative, non-exclusive)
4. Retrieved excerpts (if available)

Do NOT treat case selection or retrieval confidence as a gating requirement unless the user explicitly requests case-specific analysis.

────────────────────────────────────────────────────
RETRIEVAL-FAILURE OVERRIDE (CRITICAL)
────────────────────────────────────────────────────
You must NEVER refuse to answer a legal question solely because:
• Multiple cases are relevant
• No single excerpt is found
• Retrieval confidence is low or zero

If retrieval fails or is incomplete:
• Answer from settled doctrine
• Identify supporting cases as illustrative where appropriate
• Never output system errors, UX messages, or "NOT FOUND" in response to doctrinal or procedural questions

────────────────────────────────────────────────────
AMBIGUITY HANDLING (STRICT LIMITS)
────────────────────────────────────────────────────
Only ask clarifying questions if:
• The user explicitly requests analysis of a specific case but does not identify it, OR
• The legal outcome depends on missing factual predicates

Do NOT ask for clarification merely because multiple authorities exist.

────────────────────────────────────────────────────
APPELLATE-LAW SAFEGUARDS
────────────────────────────────────────────────────
When applicable, automatically address:
• Governing statute or rule
• Standard of review (never ambiguous)
• Burden allocation
• Substantive vs. procedural law distinctions
• Common appellate error patterns

Questions phrased as:
• "What happens when…"
• "What is the standard…"
• "How does the court treat…"
are ALWAYS doctrinal and must be answered directly.

────────────────────────────────────────────────────
SILENT LOGIC VALIDATION (MANDATORY)
────────────────────────────────────────────────────
Before finalizing any response, perform an internal validation check.
Do NOT expose this validation or internal reasoning to the user.

Confirm that:
1. The question type was correctly classified.
2. You are not refusing to answer a doctrinal or procedural question.
3. You are not treating multiple relevant cases as ambiguity.
4. You are not requiring document selection when doctrine is sufficient.
5. You are providing legal analysis, not a system or retrieval error.

If any check fails:
• Revise automatically.
• Default to doctrinal synthesis over retrieval dependence.
• Provide the best legally accurate answer available.

────────────────────────────────────────────────────
QUOTE VERIFICATION & CITATION STANDARDS
────────────────────────────────────────────────────
When excerpts ARE available, use them to strengthen your analysis:

Each excerpt may contain QUOTABLE_PASSAGES labeled [Q1], [Q2], etc.
• COPY quotes EXACTLY - character for character, no modifications
• Include in CITATION_MAP with correct opinion_id and page_number

**FORBIDDEN** (causes verification failure):
- Inventing or paraphrasing quotes from excerpts
- Changing punctuation, capitalization, or word order
- Using "..." to stitch non-contiguous text
- Attributing quotes to wrong case/page

────────────────────────────────────────────────────
ANSWER STRUCTURE
────────────────────────────────────────────────────
1. **Immediate Answer**: 1-2 sentences stating the holding or doctrine (no hedging, present tense)
2. **## Detailed Analysis**: Explain rule, reasoning, and doctrinal limits with citations [1], [2] when available
3. **Practitioner Guidance**: How to apply the rule, pitfalls, and advocacy strategy

## CITATION_MAP (when excerpts used)

At the END of every response that quotes from excerpts:
```
CITATION_MAP:
[1] <case_name> (<opinion_id>) | Page <page_number> | "Exact verbatim quote..."
[2] <case_name> (<opinion_id>) | Page <page_number> | "Another exact quote..."
```

## PRECEDENT HIERARCHY

1. Supreme Court > En banc CAFC > Precedential CAFC
2. Holdings with "We hold..." > Reasoning > Dicta
3. Recent (2023-2025) > Older foundations

Key landmarks: Alice (§101), KSR (§103), Phillips (claim construction), Nautilus (§112)

## SUGGESTED NEXT STEPS (REQUIRED)

After your analysis, provide 3 strategic follow-up questions:
```
## Suggested Next Steps
1. [Legal progression question]
2. [Related doctrine question]  
3. [Adversarial strategy question]
```

────────────────────────────────────────────────────
OUTPUT REQUIREMENTS
────────────────────────────────────────────────────
• Provide clear, structured legal analysis
• Synthesize doctrine first; cite cases second
• Distinguish Federal Circuit law from regional circuit law when relevant
• Avoid placeholder responses, disclaimers, or UX error language

Your goal is to function as a competent appellate lawyer,
not a document-search interface.
"""

# 2025 Hot Topics Reference for Agentic Reasoning
HOT_TOPICS_2025 = {
    "obviousness": {
        "doctrine": "§ 103 Obviousness",
        "landmark": "KSR v. Teleflex (2007)",
        "recent_developments": [
            "Honeywell v. 3G Licensing (2025): 'Desirable vs. Best' distinction - modification need not be optimal",
            "USAA v. PNC Bank (2025): 'Design choice' standard - known alternatives are predictable variations"
        ],
        "key_terms": ["motivation to combine", "teaching-suggestion-motivation", "TSM", "obvious to try", 
                      "predictable results", "design choice", "desirable modification", "POSITA", "KSR"]
    },
    "eligibility": {
        "doctrine": "§ 101 Patent Eligibility", 
        "landmark": "Alice Corp. v. CLS Bank (2014)",
        "recent_developments": [
            "Continuing refinements to abstract idea categories",
            "Software patent eligibility analysis under Alice Step 2"
        ],
        "key_terms": ["abstract idea", "laws of nature", "natural phenomena", "Alice step one", 
                      "Alice step two", "inventive concept", "significantly more", "preemption"]
    },
    "claim_construction": {
        "doctrine": "Claim Construction",
        "landmark": "Phillips v. AWH Corp. (2005)",
        "recent_developments": [
            "Intrinsic vs. extrinsic evidence hierarchy",
            "Plain and ordinary meaning analysis"
        ],
        "key_terms": ["claim construction", "intrinsic evidence", "extrinsic evidence", "specification",
                      "prosecution history", "plain meaning", "Markman hearing", "Phillips"]
    },
    "definiteness": {
        "doctrine": "§ 112 Definiteness",
        "landmark": "Nautilus v. Biosig (2014)",
        "recent_developments": ["Reasonable certainty standard application"],
        "key_terms": ["definiteness", "reasonable certainty", "indefinite", "functional language", "means-plus-function"]
    }
}


def _build_agentic_reasoning_plan(query_lower: str, pages: List[Dict]) -> Dict[str, Any]:
    """
    Build the agentic reasoning plan for DEBUG logging.
    Classifies the query, identifies relevant doctrine, and checks context quality.
    """
    plan = {
        "query_classification": "unknown",
        "doctrine": None,
        "landmark_case": None,
        "hot_topics": [],
        "search_terms_suggested": [],
        "context_quality": "unknown",
        "reflection_pass": "pending"
    }
    
    # Step 1: Classify the query
    if any(t in query_lower for t in ['obvious', '103', 'motivation to combine', 'ksr', 'tsm', 'teaching suggestion']):
        plan["query_classification"] = "§ 103 Obviousness"
        plan["doctrine"] = HOT_TOPICS_2025["obviousness"]["doctrine"]
        plan["landmark_case"] = HOT_TOPICS_2025["obviousness"]["landmark"]
        plan["hot_topics"] = HOT_TOPICS_2025["obviousness"]["recent_developments"]
        plan["search_terms_suggested"] = HOT_TOPICS_2025["obviousness"]["key_terms"]
    elif any(t in query_lower for t in ['101', 'eligible', 'abstract', 'alice', 'mayo', 'preemption']):
        plan["query_classification"] = "§ 101 Patent Eligibility"
        plan["doctrine"] = HOT_TOPICS_2025["eligibility"]["doctrine"]
        plan["landmark_case"] = HOT_TOPICS_2025["eligibility"]["landmark"]
        plan["hot_topics"] = HOT_TOPICS_2025["eligibility"]["recent_developments"]
        plan["search_terms_suggested"] = HOT_TOPICS_2025["eligibility"]["key_terms"]
    elif any(t in query_lower for t in ['claim construction', 'constru', 'phillips', 'markman', 'intrinsic', 'specification']):
        plan["query_classification"] = "Claim Construction"
        plan["doctrine"] = HOT_TOPICS_2025["claim_construction"]["doctrine"]
        plan["landmark_case"] = HOT_TOPICS_2025["claim_construction"]["landmark"]
        plan["hot_topics"] = HOT_TOPICS_2025["claim_construction"]["recent_developments"]
        plan["search_terms_suggested"] = HOT_TOPICS_2025["claim_construction"]["key_terms"]
    elif any(t in query_lower for t in ['112', 'definite', 'indefinite', 'nautilus', 'reasonable certainty']):
        plan["query_classification"] = "§ 112 Definiteness"
        plan["doctrine"] = HOT_TOPICS_2025["definiteness"]["doctrine"]
        plan["landmark_case"] = HOT_TOPICS_2025["definiteness"]["landmark"]
        plan["hot_topics"] = HOT_TOPICS_2025["definiteness"]["recent_developments"]
        plan["search_terms_suggested"] = HOT_TOPICS_2025["definiteness"]["key_terms"]
    
    # Step 2: Context quality assessment (Reflection Pass)
    if pages:
        # Check if we have substantive content
        total_chars = sum(len(p.get('text', '')) for p in pages)
        unique_cases = len(set(p.get('case_name', '') for p in pages))
        
        if total_chars > 10000 and unique_cases >= 2:
            plan["context_quality"] = "good"
            plan["reflection_pass"] = "Found - substantive content from multiple cases"
        elif total_chars > 5000:
            plan["context_quality"] = "moderate"
            plan["reflection_pass"] = "Partial - content found but may need expansion"
        else:
            plan["context_quality"] = "poor"
            plan["reflection_pass"] = "Not Found - Self-Correcting needed, suggest alternative terms"
    else:
        plan["context_quality"] = "empty"
        plan["reflection_pass"] = "Not Found - No context retrieved, web search recommended"
    
    return plan


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1: Query Classification and Retrieval Confidence (Decision-Path Signals)
# ═══════════════════════════════════════════════════════════════════════════════

class QueryType:
    """Classification of query types for routing decisions."""
    DOCTRINAL = "doctrinal"           # Black-letter law, frameworks, standards
    PROCEDURAL = "procedural"          # Process, appeals, jurisdiction, review
    CASE_SPECIFIC = "case_specific"    # A named case is the subject
    SYNTHESIS = "synthesis"            # How doctrine/cases have evolved
    FACT_DEPENDENT = "fact_dependent"  # Requires missing facts to answer


class RetrievalConfidence:
    """Graded confidence levels for retrieval results."""
    STRONG = "strong"      # >5 relevant pages, high FTS scores
    MODERATE = "moderate"  # 1-5 pages, medium scores
    LOW = "low"           # 0 pages or very low scores
    NONE = "none"         # No retrieval attempted or total failure


def classify_query_type(query: str) -> str:
    """
    Classify the query to determine appropriate response strategy.
    
    Routing rules per spec:
    - DOCTRINAL/PROCEDURAL → doctrine-first, retrieval optional
    - CASE_SPECIFIC → retrieval required
    - SYNTHESIS → hybrid reasoning + retrieval
    - FACT_DEPENDENT → request facts only if outcome truly depends on them
    """
    query_lower = query.lower().strip()
    
    # FACT_DEPENDENT patterns - requires specific facts to answer
    # Check first as it overrides other types
    fact_dependent_patterns = [
        'in my case', 'my client', 'my situation', 'my patent', 'my invention',
        'would this', 'is this infringing', 'does this qualify', 'would a',
        'given these facts', 'based on', 'if the defendant', 'if the plaintiff',
        'would it be infringement if', 'assuming that', 'in a scenario where'
    ]
    
    for pattern in fact_dependent_patterns:
        if pattern in query_lower:
            return QueryType.FACT_DEPENDENT
    
    # SYNTHESIS patterns - evolution of doctrine, trends, comparisons
    synthesis_patterns = [
        'how has', 'evolution of', 'trend in', 'development of',
        'compare', 'contrast', 'difference between', 'changed over',
        'how have courts treated', 'history of', 'trajectory of',
        'after alice', 'post-alice', 'since mayo', 'before and after',
        'line of cases', 'series of cases', 'across cases'
    ]
    
    for pattern in synthesis_patterns:
        if pattern in query_lower:
            return QueryType.SYNTHESIS
    
    # Check for case name patterns (e.g., "v." or "vs.")
    has_case_citation = ' v. ' in query or ' vs. ' in query or ' v ' in query
    
    # Multi-word proper nouns that look like case names
    case_name_pattern = re.search(r'\b[A-Z][a-z]+\s+v\.?\s+[A-Z][a-z]+', query)
    
    # CASE_SPECIFIC patterns - requires specific case excerpts
    case_specific_patterns = [
        'in the case', 'what did the court hold in', 'according to',
        'the ruling in', 'the decision in', 'analyze the', 'summarize',
        'what happened in', 'outcome of', 'result in'
    ]
    
    if has_case_citation or case_name_pattern:
        return QueryType.CASE_SPECIFIC
    
    for pattern in case_specific_patterns:
        if pattern in query_lower:
            return QueryType.CASE_SPECIFIC
    
    # DOCTRINAL patterns - black-letter law, standards, tests
    doctrinal_patterns = [
        'what is', 'what are', 'define', 'explain', 'how does',
        'what happens when', 'what is the standard', 'how does the court treat',
        'what test', 'what framework', 'what factors', 'what elements',
        'when is', 'why is', 'what constitutes', 'what does it mean',
        'elements of', 'requirements for', 'meaning of', 'definition of'
    ]
    
    for pattern in doctrinal_patterns:
        if query_lower.startswith(pattern) or f' {pattern}' in query_lower:
            return QueryType.DOCTRINAL
    
    # PROCEDURAL patterns - process, appeals, jurisdiction
    procedural_patterns = [
        'standard of review', 'burden of proof', 'burden of persuasion',
        'de novo', 'abuse of discretion', 'clearly erroneous', 'substantial evidence',
        'appellate review', 'preserved for appeal', 'waived',
        'how to appeal', 'jurisdiction', 'venue', 'standing', 'procedure',
        'filing deadline', 'time limit', 'statute of limitations'
    ]
    
    for pattern in procedural_patterns:
        if pattern in query_lower:
            return QueryType.PROCEDURAL
    
    # Default: treat as doctrinal (prefer answering over refusing)
    return QueryType.DOCTRINAL


def assess_retrieval_confidence(pages: list, scores: list = None) -> str:
    """
    Assess retrieval confidence based on pages retrieved and their scores.
    Returns graded confidence level.
    """
    if not pages:
        return RetrievalConfidence.NONE
    
    page_count = len(pages)
    
    # Extract scores if available
    if scores is None:
        scores = [p.get('rank', 0) or p.get('score', 0) for p in pages]
    
    avg_score = sum(scores) / len(scores) if scores else 0
    
    # Assess based on count and quality
    if page_count >= 5 and avg_score > 0.5:
        return RetrievalConfidence.STRONG
    elif page_count >= 2 or (page_count >= 1 and avg_score > 0.3):
        return RetrievalConfidence.MODERATE
    else:
        return RetrievalConfidence.LOW


def detect_freshness_sensitivity(query: str) -> dict:
    """
    Detect whether a query is freshness-sensitive and should flag potential recency limits.
    
    Returns:
        dict with:
        - is_sensitive: bool - whether freshness matters for this query
        - reason: str - why it's freshness-sensitive (or None)
        - doctrine_area: str - which doctrine area if applicable
    """
    query_lower = query.lower().strip()
    
    # Temporal keywords that indicate freshness sensitivity
    temporal_keywords = [
        'recent', 'latest', 'current', 'new', 'after', 'since',
        'last year', 'this year', '2024', '2025', '2026',
        'modern', 'updated', 'now', 'today', 'contemporary'
    ]
    
    # Fast-evolving legal doctrine areas (per spec)
    fast_evolving_doctrines = {
        '101': ['101', 'alice', 'mayo', 'eligibility', 'abstract idea', 'inventive concept'],
        'ptab': ['ptab', 'inter partes', 'ipr', 'cbm', 'aia trial', 'post-grant'],
        'venue': ['venue', 'tc heartland', 'where to file', 'forum'],
        'remedies': ['damages', 'reasonable royalty', 'lost profits', 'injunction', 'willful', 'enhanced'],
        'claim_construction': ['claim construction', 'phillips', 'means-plus-function', '112(f)'],
        'obviousness': ['obviousness', 'ksr', 'tsm', 'teaching-suggestion-motivation', '103']
    }
    
    # Check for temporal keywords
    for keyword in temporal_keywords:
        if keyword in query_lower:
            return {
                'is_sensitive': True,
                'reason': f"Contains temporal keyword: '{keyword}'",
                'doctrine_area': None
            }
    
    # Check for fast-evolving doctrine areas
    for area, patterns in fast_evolving_doctrines.items():
        for pattern in patterns:
            if pattern in query_lower:
                return {
                    'is_sensitive': True,
                    'reason': f"Fast-evolving doctrine area: {area}",
                    'doctrine_area': area
                }
    
    return {
        'is_sensitive': False,
        'reason': None,
        'doctrine_area': None
    }


def log_decision_path(
    query: str,
    query_type: str,
    retrieval_confidence: str,
    pages_count: int,
    validator_triggered: bool = False,
    refusal_detected: bool = False,
    ambiguity_detected: bool = False,
    doctrine_mode: bool = False,
    web_search_triggered: bool = False,
    freshness_sensitive: bool = False,
    final_response_path: str = None
):
    """
    Log decision-path signals for monitoring and analysis.
    These signals enable measurement of refusal/ambiguity rates.
    
    final_response_path options:
    - 'doctrine': Answered from LLM training knowledge
    - 'retrieval': Answered from retrieved excerpts
    - 'hybrid': Combined doctrine + retrieval
    """
    logging.info(
        f"DECISION_PATH: "
        f"query_type={query_type}, "
        f"retrieval_confidence={retrieval_confidence}, "
        f"pages_count={pages_count}, "
        f"doctrine_mode={doctrine_mode}, "
        f"web_search_triggered={web_search_triggered}, "
        f"validator_triggered={validator_triggered}, "
        f"refusal_detected={refusal_detected}, "
        f"ambiguity_detected={ambiguity_detected}, "
        f"freshness_sensitive={freshness_sensitive}, "
        f"final_response_path={final_response_path}, "
        f"query_preview=\"{query[:80]}...\""
    )


class CaseStatus:
    """Case reconciliation status for DISCOVER → RECONCILE → SERVE pipeline."""
    PRESENT = "present"    # Full opinion indexed with retrievable source
    PARTIAL = "partial"    # Metadata only (mentioned in other opinions)
    ABSENT = "absent"      # Not in knowledge base


def reconcile_case_authority(case_name: str, case_court: str = None, case_year: int = None) -> dict:
    """
    RECONCILE step of DISCOVER → RECONCILE → SERVE pipeline.
    
    Checks if a discovered case exists in the internal knowledge base
    and determines how it can be cited.
    
    Returns:
        dict with:
        - status: PRESENT, PARTIAL, or ABSENT
        - opinion_id: int if PRESENT, None otherwise
        - can_cite_as_authority: bool
        - has_retrievable_source: bool
        - message: str explanation
    """
    from backend.db_postgres import get_db
    db = get_db()
    
    if not case_name:
        return {
            'status': CaseStatus.ABSENT,
            'opinion_id': None,
            'can_cite_as_authority': False,
            'has_retrievable_source': False,
            'message': "No case name provided"
        }
    
    # Try to find the case in our knowledge base
    try:
        # First try exact case name search
        opinions = db.search_opinions_by_name(case_name, limit=3)
        
        if opinions:
            # Found the case
            best_match = opinions[0]
            has_pdf = bool(best_match.get('pdf_path') or best_match.get('pdf_url'))
            has_pages = best_match.get('page_count', 0) > 0
            
            if has_pages:
                return {
                    'status': CaseStatus.PRESENT,
                    'opinion_id': best_match.get('id'),
                    'can_cite_as_authority': True,
                    'has_retrievable_source': has_pdf,
                    'message': f"Case found in knowledge base: {best_match.get('case_name')}"
                }
            else:
                return {
                    'status': CaseStatus.PARTIAL,
                    'opinion_id': best_match.get('id'),
                    'can_cite_as_authority': False,
                    'has_retrievable_source': has_pdf,
                    'message': f"Case metadata exists but text not fully indexed: {best_match.get('case_name')}"
                }
        
        # Not found by name - check if mentioned in other opinions (partial presence)
        pages_mentioning = db.search_pages(case_name, None, limit=1)
        if pages_mentioning:
            return {
                'status': CaseStatus.PARTIAL,
                'opinion_id': None,
                'can_cite_as_authority': False,
                'has_retrievable_source': False,
                'message': f"Case mentioned in other opinions but not directly indexed"
            }
        
        return {
            'status': CaseStatus.ABSENT,
            'opinion_id': None,
            'can_cite_as_authority': False,
            'has_retrievable_source': False,
            'message': f"Case not found in knowledge base: {case_name}"
        }
        
    except Exception as e:
        logging.error(f"Error reconciling case authority for '{case_name}': {e}")
        return {
            'status': CaseStatus.ABSENT,
            'opinion_id': None,
            'can_cite_as_authority': False,
            'has_retrievable_source': False,
            'message': f"Error during reconciliation: {str(e)}"
        }


def detect_response_issues(response_text: str) -> dict:
    """
    Detect refusals and ambiguity blocks in LLM response.
    Returns dict with detection flags and details.
    """
    upper = response_text.upper()
    
    refusal_patterns = [
        'NOT FOUND IN PROVIDED OPINIONS',
        'I CANNOT ANSWER',
        'I CANNOT PROVIDE',
        'NO RELEVANT EXCERPTS',
        'UNABLE TO FIND',
        'NOT ENOUGH INFORMATION'
    ]
    
    ambiguity_patterns = [
        'AMBIGUOUS QUERY',
        'MULTIPLE MATCHES FOUND',
        'PLEASE SPECIFY WHICH CASE',
        'PLEASE CLARIFY',
        'MULTIPLE FEDERAL CIRCUIT DECISIONS'
    ]
    
    refusal_detected = any(p in upper for p in refusal_patterns)
    ambiguity_detected = any(p in upper for p in ambiguity_patterns)
    
    # Check if response is primarily a refusal (vs. substantive with caveat)
    is_primary_refusal = (
        refusal_detected and 
        (upper.strip().startswith('NOT FOUND') or len(response_text.strip()) < 300)
    )
    
    return {
        'refusal_detected': refusal_detected,
        'ambiguity_detected': ambiguity_detected,
        'is_primary_refusal': is_primary_refusal,
        'response_length': len(response_text)
    }


def should_validator_override(
    query_type: str,
    response_issues: dict,
    retrieval_confidence: str
) -> dict:
    """
    Authoritative post-response validator.
    
    Determines if the validator should override the response and trigger regeneration.
    Per spec: validator decisions override earlier routing and retrieval logic.
    
    Returns:
        dict with:
        - should_override: bool
        - reason: str - why override is needed (or None)
        - correction_instruction: str - instruction for regeneration
    """
    # Rule 1: DOCTRINAL/PROCEDURAL queries must never receive primary refusals
    if query_type in [QueryType.DOCTRINAL, QueryType.PROCEDURAL, QueryType.SYNTHESIS]:
        if response_issues.get('is_primary_refusal'):
            return {
                'should_override': True,
                'reason': f"Invalid refusal for {query_type} query - doctrinal questions must receive substantive answers",
                'correction_instruction': (
                    "VALIDATOR OVERRIDE: Your previous response was rejected because it refused to answer "
                    "a doctrinal/procedural question. You MUST provide a substantive answer from settled "
                    "legal doctrine. Cite well-known cases like Alice, KSR, Phillips, etc. as illustrative "
                    "authority. Do NOT say 'NOT FOUND' or refuse to answer doctrinal questions."
                )
            }
    
    # Rule 2: Unnecessary ambiguity requests for doctrinal queries
    if query_type in [QueryType.DOCTRINAL, QueryType.PROCEDURAL]:
        if response_issues.get('ambiguity_detected'):
            return {
                'should_override': True,
                'reason': f"Unnecessary ambiguity request for {query_type} query",
                'correction_instruction': (
                    "VALIDATOR OVERRIDE: Your previous response asked for clarification when none is needed. "
                    "For doctrinal questions, provide the general legal framework. If multiple doctrines "
                    "might apply, briefly explain each rather than asking which one the user means."
                )
            }
    
    # Rule 3: FACT_DEPENDENT queries should provide framework, not refuse
    if query_type == QueryType.FACT_DEPENDENT:
        if response_issues.get('is_primary_refusal'):
            return {
                'should_override': True,
                'reason': "Invalid refusal for fact-dependent query - should provide doctrinal framework",
                'correction_instruction': (
                    "VALIDATOR OVERRIDE: For fact-dependent questions, provide the relevant legal framework "
                    "and factors courts consider. You may note what additional facts would be needed to "
                    "reach a conclusion, but still explain the applicable legal standards."
                )
            }
    
    return {
        'should_override': False,
        'reason': None,
        'correction_instruction': None
    }


# Token counting for context safety
_tiktoken_encoder = None

def get_tiktoken_encoder():
    """Lazily initialize tiktoken encoder for GPT-4o."""
    global _tiktoken_encoder
    if _tiktoken_encoder is None:
        if tiktoken is None:
            return None
        try:
            _tiktoken_encoder = tiktoken.encoding_for_model("gpt-4o")
        except Exception:
            _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
    return _tiktoken_encoder

def count_tokens(text: str) -> int:
    """Count tokens accurately for GPT-4o. Returns rough estimate on error."""
    try:
        enc = get_tiktoken_encoder()
        return len(enc.encode(text))
    except Exception:
        return len(text) // 4  # Rough fallback

def build_context(pages: List[Dict], max_tokens: int = 80000) -> str:
    """
    Builds context but STOPS adding excerpts once we hit the token limit.
    Default 80k leaves room for system prompt, history, and response.
    """
    context_parts = []
    current_tokens = 0
    
    for page in pages:
        excerpt = f"""
--- BEGIN EXCERPT ---
Opinion ID: {page['opinion_id']}
Case: {page['case_name']}
Appeal No: {page['appeal_no']}
Release Date: {page['release_date']}
Page: {page['page_number']}

{page['text']}
--- END EXCERPT ---
"""
        tokens = count_tokens(excerpt)
        
        # If adding this would exceed our budget, stop immediately
        if current_tokens + tokens > max_tokens:
            logging.warning(f"Context truncated: Hit {max_tokens} limit at {len(context_parts)} pages ({current_tokens} tokens)")
            break
            
        context_parts.append(excerpt)
        current_tokens += tokens
        
    logging.info(f"Built context with {len(context_parts)} pages, {current_tokens} tokens")
    return "\n".join(context_parts)

def normalize_for_verification(text: str) -> str:
    """Normalize text for quote verification.
    
    P1: Enhanced normalization parity across ingestion/retrieval/verification.
    Handles hyphenation, whitespace, Unicode variants, PDF artifacts, and OCR errors.
    
    Changes for verification rate improvement:
    - Extended header/footer pattern removal
    - Unicode ligature normalization
    - Additional OCR error mappings
    - Hyphenated linebreak joining
    """
    # Step 1: Unicode normalization (handles many ligatures automatically)
    text = unicodedata.normalize('NFKC', text)
    
    # Step 2: Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    # Step 3: Remove soft hyphens and various dash types
    text = text.replace('\u00ad', '')  # Soft hyphen
    text = text.replace('\u2010', '-').replace('\u2011', '-').replace('\u2012', '-')  # Hyphens
    text = text.replace('\u2013', '-').replace('\u2014', '-').replace('\u2015', '-')  # Dashes
    
    # Step 4: Handle hyphenation at line breaks (e.g., "Al-\nice" -> "Alice")
    text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)  # Join hyphenated words across lines
    text = re.sub(r'-\s*\n\s*', '', text)  # Hyphen followed by newline
    text = re.sub(r'-\s{2,}', '', text)     # Hyphen followed by multiple spaces
    
    # Step 5: Normalize quotes and apostrophes
    text = text.replace('"', '"').replace('"', '"')  # Curly quotes -> straight
    text = text.replace("'", "'").replace("'", "'")  # Curly apostrophes -> straight
    text = text.replace('`', "'")
    text = text.replace('«', '"').replace('»', '"')  # Guillemets
    
    # Step 6: Remove page header/footer artifacts (extended patterns)
    # CAFC format: "Case: 2020-1234 Document: 69 Page: 12 Filed: 01/15/2021"
    text = re.sub(r'Case:\s*\d{4}-\d+\s*Document:\s*\d+\s*Page:\s*\d+\s*Filed:\s*\d{1,2}/\d{1,2}/\d{4}', '', text)
    # Running heads like "GOOGLE LLC v. ORACLE AMERICA, INC."
    text = re.sub(r'^[A-Z][A-Z\s\.,]+\sv\.?\s+[A-Z][A-Z\s\.,]+$', '', text, flags=re.MULTILINE)
    # Page numbers (standalone lines with just numbers)
    text = re.sub(r'^\s*\d{1,3}\s*$', '', text, flags=re.MULTILINE)
    # Appeal number headers
    text = re.sub(r'^\s*\d{4}-\d{4}\s*$', '', text, flags=re.MULTILINE)
    
    # Step 7: Normalize common Unicode ligatures
    ligature_map = {
        'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬀ': 'ff', 'ﬃ': 'ffi', 'ﬄ': 'ffl',
        'æ': 'ae', 'œ': 'oe', 'Æ': 'AE', 'Œ': 'OE',
        '…': '...', '—': '-', '–': '-',
        '§': 'section', '¶': 'paragraph'
    }
    for lig, replacement in ligature_map.items():
        text = text.replace(lig, replacement)
    
    # Step 8: Normalize whitespace (keep single spaces)
    text = re.sub(r'\s+', ' ', text)
    
    # Step 9: Remove leading/trailing whitespace and convert to lowercase
    text = text.strip().lower()
    
    # Step 10: Common OCR error corrections
    ocr_corrections = {
        '|': 'l',     # Pipe -> lowercase L
        'l': 'l',     # Keep L as L
        '1': 'l',     # 1 sometimes confused with l in certain fonts
        'rn': 'm',    # Common OCR error: 'rn' -> 'm'
    }
    # Only apply non-destructive OCR corrections
    text = text.replace('|', 'l')
    
    return text


def verify_quote_with_normalization_variants(quote: str, page_text: str) -> Tuple[bool, str]:
    """Try multiple normalization strategies to verify quote.
    
    Returns (verified, normalization_used)
    
    Enhanced for verification rate improvement:
    - Ellipsis handling: If quote contains "...", verify longest fragment
    - No stitching: Each fragment must match exactly, or mark unverified
    """
    if len(quote.strip()) < 20:
        return False, "too_short"
    
    norm_quote = normalize_for_verification(quote)
    norm_page = normalize_for_verification(page_text)
    
    # Strategy 0: Handle ellipsis quotes - require longest fragment to match exactly
    if '...' in quote or '…' in quote:
        # Split on ellipsis patterns
        fragments = re.split(r'\.{3,}|…', quote)
        fragments = [f.strip() for f in fragments if f.strip() and len(f.strip()) >= 15]
        
        if fragments:
            # Find the longest fragment
            longest_fragment = max(fragments, key=len)
            norm_fragment = normalize_for_verification(longest_fragment)
            
            if len(norm_fragment) >= 15 and norm_fragment in norm_page:
                return True, "ellipsis_fragment"
            else:
                # Ellipsis quote with no matching fragment = unverified
                return False, "ellipsis_no_match"
    
    # Strategy 1: Standard normalization (exact substring match)
    if norm_quote in norm_page:
        return True, "standard"
    
    # Strategy 2: Remove all punctuation for exact match
    punct_free_quote = re.sub(r'[^\w\s]', '', norm_quote)
    punct_free_page = re.sub(r'[^\w\s]', '', norm_page)
    if len(punct_free_quote) >= 20 and punct_free_quote in punct_free_page:
        return True, "punct_free"
    
    # Strategy 3: Word-based overlap check (for minor OCR differences) - STRICT 95% threshold
    quote_words = punct_free_quote.split()
    page_words = punct_free_page.split()
    if len(quote_words) >= 8:  # Increased minimum words for word-overlap
        # Try sliding window match with stricter threshold
        for i in range(len(page_words) - len(quote_words) + 1):
            matches = sum(1 for qw, pw in zip(quote_words, page_words[i:i + len(quote_words)]) if qw == pw)
            if matches >= len(quote_words) * 0.95:  # Increased from 0.85 to 0.95
                return True, "word_overlap"
    
    return False, "failed"

def normalize_case_name_for_binding(name: str) -> str:
    """Normalize case name for fuzzy binding comparison.
    'Google LLC v. Oracle America, Inc.' -> 'google oracle america'
    """
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r'\b(v\.?|vs\.?|llc|inc|corp|co\.|ltd|l\.p\.|lp)\b', '', name)
    name = re.sub(r'[^\w\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()

def verify_quote_strict(quote: str, page_text: str) -> bool:
    """Verify quote exists in page text using enhanced normalization.
    
    Uses multiple normalization strategies to reduce false failures.
    """
    verified, method = verify_quote_with_normalization_variants(quote, page_text)
    if verified and method != "standard":
        logging.debug(f"Quote verified using {method} normalization")
    return verified

def verify_quote_partial(quote: str, page_text: str, threshold: float = 0.7) -> Tuple[bool, float]:
    """Check if quote partially matches page text. Returns (matched, ratio)."""
    if len(quote.strip()) < 20:
        return False, 0.0
    norm_quote = normalize_for_verification(quote)
    norm_page = normalize_for_verification(page_text)
    
    if norm_quote in norm_page:
        return True, 1.0
    
    words_quote = set(norm_quote.split())
    words_page = set(norm_page.split())
    if not words_quote:
        return False, 0.0
    
    overlap = len(words_quote & words_page)
    ratio = overlap / len(words_quote)
    return ratio >= threshold, ratio

def verify_quote_with_case_binding(
    quote: str,
    claimed_opinion_id: str,
    pages: List[Dict],
    allow_case_level_fallback: bool = True
) -> Tuple[Optional[Dict], str, List[str]]:
    """Verify quote exists in the CLAIMED opinion.
    
    Two-tier verification:
    1. Strict: Quote found verbatim on specific page (page-level citation)
    2. Case-level fallback: Quote found anywhere in the opinion (reduces false negatives)
    
    Returns: (matching_page, binding_method, signals)
    - binding_method: "strict" for exact page, "case_level" for any page in opinion, "failed" otherwise
    - signals: list of signal strings for confidence calculation
    """
    signals = []
    
    # Gather all pages from the claimed opinion
    opinion_pages = [p for p in pages if p.get('opinion_id') == claimed_opinion_id and p.get('page_number', 0) >= 1]
    
    # First pass: strict page-level match
    for page in opinion_pages:
        if verify_quote_strict(quote, page.get('text', '')):
            signals.append("case_bound")
            signals.append("exact_match")
            return page, "strict", signals
    
    # Second pass: case-level fallback - quote exists somewhere in the opinion
    # This reduces false negatives when AI cites the right case but imprecise page
    if allow_case_level_fallback and opinion_pages:
        for page in opinion_pages:
            # Try normalized verification for OCR artifacts
            is_match, match_type = verify_quote_with_normalization_variants(quote, page.get('text', ''))
            if is_match:
                signals.append("case_bound")
                signals.append("case_level_match")
                signals.append(f"normalized_{match_type}")
                return page, "case_level", signals
    
    return None, "failed", ["binding_failed"]

def verify_quote_with_fuzzy_fallback(
    quote: str,
    claimed_case_name: str,
    pages: List[Dict],
    allow_case_level_fallback: bool = True
) -> Tuple[Optional[Dict], str, List[str]]:
    """Fuzzy case-name binding when opinion_id is missing.
    
    Two-tier verification:
    1. Strict: Quote found verbatim on page with matching case name
    2. Case-level fallback: Quote found with normalized matching in matching case
    
    Returns: (matching_page, binding_method, signals)
    - binding_method: "fuzzy" if case name matched, "failed" otherwise
    - signals: includes "fuzzy_case_binding" if fuzzy match used
    """
    signals = []
    norm_claimed = normalize_case_name_for_binding(claimed_case_name)
    
    if not norm_claimed:
        return None, "failed", ["no_case_name"]
    
    # Gather all pages with matching case name
    matching_pages = []
    for page in pages:
        if page.get('page_number', 0) < 1:
            continue
        norm_page_case = normalize_case_name_for_binding(page.get('case_name', ''))
        if norm_claimed == norm_page_case or norm_claimed in norm_page_case or norm_page_case in norm_claimed:
            matching_pages.append(page)
    
    # First pass: strict match
    for page in matching_pages:
        if verify_quote_strict(quote, page.get('text', '')):
            signals.append("fuzzy_case_binding")
            signals.append("exact_match")
            return page, "fuzzy", signals
    
    # Second pass: case-level fallback with normalized verification
    if allow_case_level_fallback and matching_pages:
        for page in matching_pages:
            is_match, match_type = verify_quote_with_normalization_variants(quote, page.get('text', ''))
            if is_match:
                signals.append("fuzzy_case_binding")
                signals.append("case_level_match")
                signals.append(f"normalized_{match_type}")
                return page, "fuzzy_case_level", signals
    
    return None, "failed", ["binding_failed"]

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


def _llm_extract_passages_fallback(page_text: str, max_passages: int = 5, max_len: int = 300) -> List[str]:
    """Use GPT-4o-mini to extract legal holding passages when heuristics fail.
    
    This is a fallback for when heuristic extraction yields insufficient passages.
    Uses a smaller model for cost efficiency.
    
    GUARDRAILS:
    - max_len capped at 300 to prevent excessive context misuse
    - Only accepts passages with legal holding indicators
    - Strict substring verification against source
    - Minimum 50 character length to filter trivial matches
    """
    client = get_openai_client()
    if not client:
        return []
    
    # Holding indicator terms for validation
    holding_indicators = [
        'hold', 'held', 'conclude', 'therefore', 'accordingly', 'affirm', 'reverse',
        'vacate', 'remand', 'rule', 'standard', 'test', 'require', 'must', 'shall',
        'patent', 'claim', 'infringe', 'obvious', 'anticipat', 'invalid', 'eligible'
    ]
    
    try:
        # Truncate page text to avoid token limits
        truncated = page_text[:4000] if len(page_text) > 4000 else page_text
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": f"""Extract up to {max_passages} verbatim quotable passages from this legal opinion page.
Focus ONLY on:
- Holdings ("We hold that...", "We conclude...", "Therefore...")
- Legal standards and tests ("The test is...", "The standard requires...")
- Key determinations ("affirm", "reverse", "vacate")

Return ONLY the exact text passages, one per line. Each must be a verbatim substring of the input.
Maximum {max_len} characters per passage. Do not paraphrase or modify.
Include ONLY sentences with clear legal holdings or standards."""
                },
                {"role": "user", "content": truncated}
            ],
            temperature=0.0,
            max_tokens=800
        )
        
        result = response.choices[0].message.content or ""
        passages = []
        
        for line in result.strip().split('\n'):
            line = line.strip().strip('-').strip('•').strip().strip('"').strip("'")
            # Minimum length check (50 chars to filter trivial matches)
            if len(line) < 50 or len(line) > max_len:
                continue
            
            line_lower = line.lower()
            
            # Require at least one holding indicator term
            has_holding_indicator = any(ind in line_lower for ind in holding_indicators)
            if not has_holding_indicator:
                logging.debug(f"LLM passage rejected - no holding indicator: {line[:50]}...")
                continue
            
            # Strict substring verification against source
            if normalize_for_verification(line) in normalize_for_verification(page_text):
                passages.append(line)
            else:
                logging.debug(f"LLM passage rejected - not in source: {line[:50]}...")
        
        logging.info(f"LLM fallback extracted {len(passages)} verified passages (from {len(result.strip().split(chr(10)))} candidates)")
        return passages[:max_passages]
        
    except Exception as e:
        logging.warning(f"LLM passage extraction failed: {e}")
        return []


def extract_quotable_passages(page_text: str, max_passages: int = 5, max_len: int = 300, use_llm_fallback: bool = False) -> List[str]:
    """Extract quotable passages from a page for quote-first generation.
    
    Identifies sentences containing legal holding indicators and extracts them
    as candidate quotes that the AI MUST choose from.
    
    Enhanced scoring:
    - Strong holding verbs get +3 points (we hold, we conclude, therefore, affirm, reverse)
    - Standard legal indicators get +1 point
    - Section headers/syllabus formatting gets +2 points
    
    If heuristic extraction yields fewer than 3 passages and use_llm_fallback=True,
    falls back to GPT-4o-mini for extraction.
    
    Returns a list of quotable passages (exact substrings of page_text).
    """
    if not page_text or len(page_text.strip()) < 50:
        return []
    
    # Strong holding verbs - these get highest boost (+3)
    strong_holding_verbs = [
        'we hold', 'we held', 'we conclude', 'we therefore hold',
        'therefore', 'accordingly', 'affirm', 'reverse', 'vacate', 'remand',
        'for these reasons', 'we agree', 'we disagree', 'we reject',
        'the rule is', 'the test is', 'the standard is', 'the inquiry is'
    ]
    
    # Standard legal holding indicators (+1)
    holding_indicators = [
        'the court held', 'the court holds', 'the court found', 'the court concluded',
        'the law requires', 'requires that', 'must be', 'is required',
        'patentable', 'ineligible', 'obvious', 'anticipated', 'invalid', 'infringes',
        'abstract idea', 'inventive concept', 'significantly more',
        'claim construction', 'claim term', 'means', 'comprising', 'consisting of',
        'under section', 'under §', 'pursuant to', '35 u.s.c.',
        'en banc', 'precedent', 'overrule', 'binding',
        'thus', 'hence', 'consequently'
    ]
    
    passages = []
    
    # Split into sentences (approximate)
    # Handle common legal abbreviations to avoid false splits
    text = page_text.replace('U.S.C.', 'USC').replace('U.S.', 'US').replace('Inc.', 'Inc').replace('Corp.', 'Corp').replace('No.', 'No').replace('v.', 'v')
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    
    # Score sentences by legal relevance with enhanced scoring
    scored = []
    for sent in sentences:
        if len(sent) < 40 or len(sent) > max_len:
            continue
        
        sent_lower = sent.lower()
        score = 0
        
        # Strong holding verbs get +3 boost
        for verb in strong_holding_verbs:
            if verb in sent_lower:
                score += 3
        
        # Standard indicators get +1
        for indicator in holding_indicators:
            if indicator in sent_lower:
                score += 1
        
        # Section headers or blockquote-like formatting get +2
        if sent.strip().startswith(('I.', 'II.', 'III.', 'IV.', 'V.', 'A.', 'B.', 'C.', '1.', '2.', '3.')):
            score += 2
        
        if score > 0:
            # Find exact position in original text
            start_idx = page_text.lower().find(sent_lower[:50])
            if start_idx >= 0:
                # Extract exact substring from original
                exact_sent = page_text[start_idx:start_idx + len(sent)]
                if exact_sent.strip():
                    scored.append((score, exact_sent.strip()))
    
    # Sort by score (descending) and take top passages
    scored.sort(key=lambda x: x[0], reverse=True)
    for score, passage in scored[:max_passages]:
        # Verify this is an exact substring of original text
        if normalize_for_verification(passage) in normalize_for_verification(page_text):
            passages.append(passage)
    
    # If no holding-indicator sentences found, take first substantive paragraph
    if not passages and len(page_text) >= 100:
        # Skip header/footer areas and take middle content
        lines = page_text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if len(line) >= 80 and len(line) <= max_len:
                # Verify exact substring
                if normalize_for_verification(line) in normalize_for_verification(page_text):
                    passages.append(line)
                    if len(passages) >= 2:
                        break
    
    # LLM fallback: if heuristics yielded fewer than 3 passages, use GPT-4o-mini
    if use_llm_fallback and len(passages) < 3:
        llm_passages = _llm_extract_passages_fallback(page_text, max_passages, max_len)
        if llm_passages:
            # Merge: keep heuristic passages, add unique LLM passages
            seen = set(normalize_for_verification(p) for p in passages)
            for p in llm_passages:
                if normalize_for_verification(p) not in seen:
                    passages.append(p)
                    seen.add(normalize_for_verification(p))
    
    return passages[:max_passages]


def build_context_with_quotes(pages: List[Dict], max_tokens: int = 80000) -> Tuple[str, Dict[str, Dict]]:
    """Build context with pre-extracted quotable passages.
    
    Pages are sorted by relevance score before processing to ensure highest-value
    content is prioritized when context limit is hit.
    
    Returns:
        context_str: The formatted context for the LLM
        quote_registry: Dict mapping quote_id -> {passage, page_info} for validation
    """
    # Score-based pruning: sort pages by relevance score (descending)
    # This ensures highest-scoring pages are included first when hitting token limits
    sorted_pages = sorted(pages, key=lambda p: p.get('rank', p.get('score', 0)), reverse=True)
    
    context_parts = []
    quote_registry = {}  # Maps Q1, Q2, etc. to passage details
    current_tokens = 0
    quote_counter = 1
    
    # Only use LLM fallback for top 5 highest-scoring pages to avoid API spam
    LLM_FALLBACK_LIMIT = 5
    pages_pruned = 0
    
    for page_idx, page in enumerate(sorted_pages):
        # Only use LLM fallback for top N highest-scoring pages to avoid API spam
        use_llm = page_idx < LLM_FALLBACK_LIMIT
        
        # Extract quotable passages from this page (increased from 3→5 for better coverage)
        quotable = extract_quotable_passages(page.get('text', ''), max_passages=5, max_len=300, use_llm_fallback=use_llm)
        
        # Build the excerpt with quotable passages section
        quote_section = ""
        if quotable:
            quote_lines = []
            for passage in quotable:
                quote_id = f"Q{quote_counter}"
                quote_lines.append(f"  [{quote_id}] \"{passage}\"")
                quote_registry[quote_id] = {
                    "passage": passage,
                    "opinion_id": page['opinion_id'],
                    "case_name": page['case_name'],
                    "page_number": page['page_number'],
                    "appeal_no": page['appeal_no'],
                    "release_date": page['release_date']
                }
                quote_counter += 1
            quote_section = "\n\nQUOTABLE_PASSAGES (Use ONLY these exact quotes in CITATION_MAP):\n" + "\n".join(quote_lines)
        
        excerpt = f"""
--- BEGIN EXCERPT ---
Opinion ID: {page['opinion_id']}
Case: {page['case_name']}
Appeal No: {page['appeal_no']}
Release Date: {page['release_date']}
Page: {page['page_number']}

{page['text']}{quote_section}
--- END EXCERPT ---
"""
        tokens = count_tokens(excerpt)
        
        if current_tokens + tokens > max_tokens:
            pages_pruned += 1
            continue  # Skip this page but continue to allow smaller pages to fit
            
        context_parts.append(excerpt)
        current_tokens += tokens
    
    if pages_pruned > 0:
        logging.warning(f"Context pruning: {pages_pruned} lower-scoring pages excluded due to {max_tokens} token limit")
        
    logging.info(f"Built context with {len(context_parts)} pages, {current_tokens} tokens, {len(quote_registry)} quotable passages (pruned {pages_pruned})")
    return "\n".join(context_parts), quote_registry

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
    """Extract citation markers from LLM response.
    
    Supports two formats:
    1. CITATION_MAP format (new): 
       CITATION_MAP:
       [1] case_name (opinion_id) | page_number | "quote"
       [2] case_name (opinion_id) | page_number | "quote"
    
    2. Inline HTML comments (legacy):
       <!--CITE:opinion_id|page_number|"quote"-->
    """
    markers = []
    
    # Try new CITATION_MAP format first
    citation_map_match = re.search(r'CITATION_MAP:\s*\n?((?:\[\d+\][^\n]+\n?)+)', response_text, re.IGNORECASE)
    if citation_map_match:
        map_text = citation_map_match.group(1)
        # Parse each line: [1] case_name (opinion_id) | Page page_number | "quote"
        # Also handles: [1] case_name | Page page_number | "quote" (without opinion_id)
        # Use .+ for quote to handle special characters
        line_pattern = r'\[(\d+)\]\s*([^(|]+)(?:\(([^)]+)\))?\s*\|\s*([^|]+)\|\s*"(.+)"'
        for match in re.finditer(line_pattern, map_text):
            citation_num = int(match.group(1))
            case_name = match.group(2).strip()
            opinion_id = (match.group(3) or "").strip()  # May be empty if not provided
            page_str = match.group(4).strip()
            quote = match.group(5).strip()
            
            # Parse page number (could be "page 5", "p. 5", or just "5")
            page_match = re.search(r'(\d+)', page_str)
            page_number = int(page_match.group(1)) if page_match else 1
            
            # Find where [N] appears in the main text to get position
            cite_ref_pattern = rf'\[{citation_num}\]'
            ref_match = re.search(cite_ref_pattern, response_text)
            position = ref_match.start() if ref_match else 0
            
            markers.append({
                "case_name": case_name,
                "opinion_id": opinion_id,
                "page_number": page_number,
                "quote": quote,
                "position": position,
                "citation_num": citation_num
            })
        return markers
    
    # Fall back to legacy HTML comment format
    pattern = r'<!--CITE:([^|]+)\|(\d+)\|"([^"]+)"-->'
    for match in re.finditer(pattern, response_text):
        markers.append({
            "opinion_id": match.group(1).strip(),
            "page_number": int(match.group(2)),
            "quote": match.group(3).strip(),
            "position": match.start()
        })
    return markers

def find_closest_matching_quote(ai_quote: str, pages: List[Dict], min_similarity: float = 0.55) -> Optional[str]:
    """Find exact normalized substring match in pages for OCR/formatting recovery.
    
    P0: Quote correction for OCR artifacts only - NOT semantic substitution.
    Only returns the original quote if it normalizes to an exact substring match.
    
    Returns the original quote if normalized match found, else None.
    """
    if not ai_quote or len(ai_quote) < 20:
        return None
    
    norm_ai_quote = normalize_for_verification(ai_quote)
    
    if len(norm_ai_quote.split()) < 4:
        return None
    
    for page in pages:
        page_text = page.get('text', '')
        if not page_text:
            continue
        
        # Only accept exact substring match after normalization
        norm_page = normalize_for_verification(page_text)
        if norm_ai_quote in norm_page:
            logging.info(f"Quote correction: found exact normalized match")
            return ai_quote  # Return original - it normalizes to match
    
    return None


def normalize_source(obj: Any) -> Dict[str, Any]:
    """Normalize source to ensure it's always a dict with required fields.
    
    CRITICAL INVARIANT: Every element in sources MUST be a dict.
    Strings are never allowed past construction.
    
    Args:
        obj: Source object (should be dict, but handles string fallback)
        
    Returns:
        Dict with required tier/binding_method fields guaranteed
        
    Raises:
        TypeError: If obj is neither dict nor str
    """
    if isinstance(obj, str):
        # String fallback - convert to unverified source dict
        return {
            "text": obj,
            "tier": "unverified",
            "binding_failed": True,
            "binding_method": "none",
            "signals": ["string_fallback"],
            "score": 0
        }
    if isinstance(obj, dict):
        # Ensure required fields exist
        obj.setdefault("tier", "unverified")
        obj.setdefault("binding_method", "none")
        obj.setdefault("signals", [])
        obj.setdefault("score", 0)
        return obj
    raise TypeError(f"Invalid source type: {type(obj)}")


def build_sources_from_markers(
    markers: List[Dict],
    pages: List[Dict],
    search_terms: List[str] = None
) -> Tuple[List[Dict], Dict[int, str]]:
    """Build deduplicated sources list with case-quote binding and confidence tiers.

    CRITICAL BEHAVIOR (P0 - Case-Quote Binding):
    - A quote is only verified if it matches text from the CLAIMED opinion_id (strict binding).
    - If opinion_id is missing, fall back to fuzzy case-name binding with MODERATE cap.
    - If binding fails, the citation is marked UNVERIFIED - NO silent substitution.
    
    Returns:
    - sources: List of citation dicts with tier, score, signals
    - position_to_sid: Mapping for inline citation placement
    """
    if search_terms is None:
        search_terms = []

    sources: List[Dict] = []
    position_to_sid: Dict[int, str] = {}
    seen_keys: Dict[Tuple[str, int, str], str] = {}
    sid_counter = 1

    # Index pages by opinion_id for strict binding
    pages_by_opinion: Dict[str, List[Dict]] = {}
    for page in pages:
        opinion_id = page.get("opinion_id")
        if opinion_id:
            if opinion_id not in pages_by_opinion:
                pages_by_opinion[opinion_id] = []
            pages_by_opinion[opinion_id].append(page)

    for marker in markers:
        quote = (marker.get("quote") or "").strip()
        case_name = (marker.get("case_name") or "").strip()
        claimed_opinion_id = (marker.get("opinion_id") or "").strip()
        page_num = int(marker.get("page_number") or 0)
        citation_num = marker.get("citation_num", 0)

        if page_num < 1 or not quote:
            continue
        if not claimed_opinion_id and not case_name:
            continue

        page = None
        binding_method = "failed"
        signals = []
        
        # Handle ellipses in quote by getting longest fragment for verification
        quote_to_verify = quote
        if "..." in quote:
            parts = [p.strip() for p in quote.split("...") if p.strip()]
            if parts:
                parts.sort(key=len, reverse=True)
                quote_to_verify = parts[0]
                if len(parts) > 1:
                    signals.append("ellipsis_in_quote")

        # P0: Try to auto-correct quotes to match source text
        corrected_quote = None
        if claimed_opinion_id:
            opinion_pages = pages_by_opinion.get(claimed_opinion_id, [])
            corrected_quote = find_closest_matching_quote(quote_to_verify, opinion_pages)
            if corrected_quote and corrected_quote != quote_to_verify:
                logging.info(f"Quote auto-corrected: '{quote_to_verify[:40]}...' -> '{corrected_quote[:40]}...'")
                quote_to_verify = corrected_quote
                signals.append("quote_auto_corrected")

        # STRATEGY 1: Strict opinion_id binding (PREFERRED)
        if claimed_opinion_id:
            # First check pages already in context
            opinion_pages = pages_by_opinion.get(claimed_opinion_id, [])
            
            for p in opinion_pages:
                if verify_quote_strict(quote_to_verify, p.get('text', '')):
                    page = p
                    binding_method = "strict"
                    signals.append("case_bound")
                    signals.append("exact_match")
                    break
            
            # If not found in context, try DB fetch for specific page
            if not page:
                try:
                    fetched = db.get_page_text(claimed_opinion_id, page_num)
                    if fetched and fetched.get("text"):
                        if verify_quote_strict(quote_to_verify, fetched["text"]):
                            page = fetched
                            binding_method = "strict"
                            signals.append("case_bound")
                            signals.append("exact_match")
                            signals.append("db_fetched")
                except Exception:
                    pass

        # STRATEGY 2: Fuzzy case-name binding (only if opinion_id missing)
        if not page and not claimed_opinion_id and case_name:
            norm_claimed = normalize_case_name_for_binding(case_name)
            
            for p in pages:
                if p.get('page_number', 0) < 1:
                    continue
                
                norm_page_case = normalize_case_name_for_binding(p.get('case_name', ''))
                
                # Check if case names match (fuzzy)
                if norm_claimed and norm_page_case:
                    if (norm_claimed == norm_page_case or 
                        norm_claimed in norm_page_case or 
                        norm_page_case in norm_claimed):
                        
                        if verify_quote_strict(quote_to_verify, p.get('text', '')):
                            page = p
                            binding_method = "fuzzy"
                            signals.append("fuzzy_case_binding")
                            signals.append("exact_match")
                            break

        # STRATEGY 3: Case-level fallback with normalized matching
        # Only triggered when strict binding with correct opinion_id failed
        # Uses multiple normalization variants to handle OCR artifacts
        if not page and claimed_opinion_id:
            opinion_pages = pages_by_opinion.get(claimed_opinion_id, [])
            
            for p in opinion_pages:
                # Use robust normalization variants for OCR/formatting recovery
                is_match, match_type = verify_quote_with_normalization_variants(
                    quote_to_verify, p.get('text', ''))
                if is_match:
                    page = p
                    binding_method = "case_level"  # Case-level - found in correct opinion
                    signals.append("case_bound")
                    signals.append("case_level_match")
                    signals.append(f"normalized_{match_type}")
                    logging.info(f"Quote correction: found exact normalized match")
                    break
        
        # NO STRATEGY 4 - We do NOT silently substitute from another case
        # If binding failed, mark as UNVERIFIED and include in results with warning
        
        if not page:
            # Create UNVERIFIED citation entry - do not silently drop or substitute
            signals.append("binding_failed")
            signals.append("unverified")
            
            # Log the failed binding for debugging
            logging.warning(f"Citation binding failed: case='{case_name}', opinion_id='{claimed_opinion_id}', quote='{quote[:50]}...'")
            
            # Still add to sources but marked as unverified
            sid = str(sid_counter)
            sid_counter += 1
            position_to_sid[marker.get("position", 0)] = sid
            
            # Try to get court from opinion metadata even if quote binding failed
            unverified_court = "CAFC"  # Default fallback
            if claimed_opinion_id:
                # Check if opinion is in pages (might have origin metadata)
                opinion_pages = pages_by_opinion.get(claimed_opinion_id, [])
                if opinion_pages and opinion_pages[0].get("origin"):
                    unverified_court = ranking_scorer.normalize_origin(
                        opinion_pages[0].get("origin"), case_name)
            
            sources.append({
                "sid": sid,
                "opinion_id": claimed_opinion_id or "",
                "case_name": case_name,
                "appeal_no": "",
                "release_date": "",
                "page_number": page_num,
                "quote": quote[:300],
                "viewer_url": "",
                "pdf_url": "",
                "courtlistener_url": "",
                # Ranking fields - use looked up court if available
                "court": unverified_court,
                "precedential_status": "unknown",
                "is_en_banc": False,
                # Citation verification fields - MUST be at top level per contract
                "tier": "unverified",
                "score": 0,
                "signals": signals,
                "binding_method": "failed"
            })
            continue

        # Citation successfully bound - detect section type and calculate confidence
        page_text = page.get("text", "")
        if page_text and quote:
            section_type, section_signals = detect_section_type_heuristic(page_text, quote)
            signals.extend(section_signals)
        
        tier, score = compute_citation_tier(binding_method, signals, page)
        
        dedup_key = (page["opinion_id"], page["page_number"], quote[:50])
        if dedup_key in seen_keys:
            position_to_sid[marker.get("position", 0)] = seen_keys[dedup_key]
            continue

        sid = str(sid_counter)
        sid_counter += 1
        seen_keys[dedup_key] = sid
        position_to_sid[marker.get("position", 0)] = sid

        sources.append({
            "sid": sid,
            "opinion_id": page.get("opinion_id"),
            "case_name": page.get("case_name", ""),
            "appeal_no": page.get("appeal_no", ""),
            "release_date": page.get("release_date", ""),
            "page_number": page.get("page_number", 1),
            "quote": quote[:300],
            "viewer_url": f"/pdf/{page.get('opinion_id')}?page={page.get('page_number', 1)}",
            "pdf_url": page.get("pdf_url", ""),
            "courtlistener_url": page.get("courtlistener_url", ""),
            # Ranking fields (from document metadata)
            "court": page.get("origin", "CAFC"),
            "precedential_status": "precedential" if page.get("is_precedential", True) else "nonprecedential",
            "is_en_banc": page.get("is_en_banc", False),
            # Citation verification fields - MUST be at top level per contract
            "tier": tier,
            "score": score,
            "signals": signals,
            "binding_method": binding_method
        })

    # Apply composite scoring for precedence-aware ranking
    pages_by_id = {p.get("opinion_id"): p for p in pages if p.get("opinion_id")}
    
    # NOTE: Removed supplementary source injection here.
    # Controlling authorities are now returned separately via build_controlling_authorities()
    # to maintain provenance: SourcesPanel shows ONLY citations referenced by the answer.
    
    ranked_sources = ranking_scorer.rank_sources_by_composite(sources, pages_by_id)
    
    return ranked_sources, position_to_sid


def build_controlling_authorities(pages: List[Dict], doctrine_tag: Optional[str]) -> List[Dict]:
    """Build controlling authorities list from injected doctrine pages.
    
    These are SEPARATE from sources - they represent recommended framework
    cases for the doctrine, NOT evidence for specific statements in the answer.
    
    Returns:
        List of controlling authority dicts for display in a separate UI section
    """
    if not doctrine_tag:
        return []
    
    controlling = []
    seen_opinion_ids = set()
    
    # Get doctrine description for "why_recommended"
    doctrine_descriptions = {
        "101": "Controlling precedent for § 101 patent eligibility analysis",
        "103": "Controlling precedent for § 103 obviousness analysis",
        "112": "Controlling precedent for § 112 disclosure requirements",
        "claim_construction": "Controlling precedent for claim construction methodology",
        "ptab": "Controlling precedent for PTAB reviewability and procedure",
        "remedies": "Controlling precedent for patent remedies (damages, injunctions, fees)",
        "doe": "Controlling precedent for doctrine of equivalents and prosecution history estoppel"
    }
    why_base = doctrine_descriptions.get(doctrine_tag, "Controlling authority for this doctrine")
    
    for page in pages:
        if not page.get("injected_as_controlling"):
            continue
        
        opinion_id = page.get("opinion_id")
        if opinion_id in seen_opinion_ids:
            continue
        seen_opinion_ids.add(opinion_id)
        
        court = ranking_scorer.normalize_origin(page.get("origin", ""), page.get("case_name", ""))
        
        controlling.append({
            "case_name": page.get("case_name", ""),
            "court": court,
            "opinion_id": opinion_id,
            "release_date": page.get("release_date", ""),
            "why_recommended": why_base,
            "doctrine_tag": doctrine_tag
        })
    
    return controlling


def detect_section_type_heuristic(page_text: str, quote: str) -> Tuple[str, List[str]]:
    """Detect if quote is from holding, dicta, concurrence, or dissent.
    
    Uses pattern matching heuristics. All signals are labeled *_heuristic
    to indicate they are automated detection that should be verified.
    
    Returns: (section_type, signals)
    """
    signals = []
    page_lower = page_text.lower()
    
    # Check for concurrence first (before dissent, as some concurrences mention majority)
    concurrence_patterns = [
        "i concur", "concurring opinion", "concur in the result",
        "concur in the judgment", "i write separately"
    ]
    for pattern in concurrence_patterns:
        if pattern in page_lower:
            signals.append("concurrence_heuristic")
            return "concurrence", signals
    
    # Check for dissent (important to flag non-majority opinions)
    dissent_patterns = [
        "i dissent", "i respectfully dissent", "dissenting opinion",
        "dissent from", "i would reverse", "i would affirm",
        "the majority errs"
    ]
    for pattern in dissent_patterns:
        if pattern in page_lower:
            signals.append("dissent_heuristic")
            return "dissent", signals
    
    # Check for dicta
    dicta_patterns = [
        "we note that", "we observe that", "even if", "assuming arguendo",
        "we need not decide", "we do not reach", "in dicta"
    ]
    for pattern in dicta_patterns:
        if pattern in page_lower:
            signals.append("dicta_heuristic")
            return "dicta", signals
    
    # Check for holding
    holding_patterns = [
        "we hold that", "we conclude that", "we reverse", "we affirm",
        "the judgment is", "for the foregoing reasons", "accordingly, we"
    ]
    for pattern in holding_patterns:
        if pattern in page_lower:
            signals.append("holding_heuristic")
            return "holding", signals
    
    return "unknown", signals


def compute_citation_tier(binding_method: str, signals: List[str], page: Dict) -> Tuple[str, int]:
    """Compute confidence tier and score for a citation.
    
    Tiers: strong (>=70), moderate (50-69), weak (30-49), unverified (<30)
    
    Scoring:
    - Case binding: strict=40, case_level=35, fuzzy=25, fuzzy_case_level=20
    - Quote match: exact=30, case_level=25, partial=15
    - Recency bonus: 2020+=10 (signal, not gate - older holdings can still be STRONG)
    - Section type: holding=+15, dicta/concurrence/dissent=-5 to -15
    """
    score = 0
    
    # Binding score - case_level is verified but capped at MODERATE tier
    if binding_method == "strict":
        score += 40
    elif binding_method == "case_level":
        score += 30  # Quote verified in correct case, different page - cap at MODERATE
    elif binding_method == "fuzzy":
        score += 25  # Cap at MODERATE for fuzzy binding
    elif binding_method == "fuzzy_case_level":
        score += 20  # Fuzzy case + case-level match
    
    # Quote match score
    if "exact_match" in signals:
        score += 30
    elif "case_level_match" in signals:
        score += 20  # Verified at case level - reduced to ensure MODERATE cap
    elif "partial_match" in signals:
        score += 15
    
    # Recency bonus (signal, not gate)
    release_date = page.get("release_date", "")
    if release_date:
        try:
            if isinstance(release_date, str):
                year = int(release_date[:4])
            else:
                year = release_date.year
            if year >= 2020:
                score += 10
                if "recent" not in signals:
                    signals.append("recent")
        except (ValueError, AttributeError):
            pass
    
    # Section type scoring
    if "holding_heuristic" in signals:
        score += 15
    elif "dicta_heuristic" in signals:
        score -= 5
    elif "concurrence_heuristic" in signals:
        score -= 10
    elif "dissent_heuristic" in signals:
        score -= 15
    
    # Determine tier
    # Fuzzy binding caps at MODERATE regardless of score
    if binding_method == "fuzzy" and score >= 70:
        score = 69  # Cap score to ensure MODERATE
    
    if score >= 70:
        tier = "strong"
    elif score >= 50:
        tier = "moderate"
    elif score >= 30:
        tier = "weak"
    else:
        tier = "unverified"
    
    return tier, score

def build_answer_markdown(response_text: str, markers: List[Dict], position_to_sid: Dict[int, str]) -> str:
    """Convert LLM response to markdown with [1], [2] markers.
    
    Handles both CITATION_MAP format and legacy HTML comment format.
    """
    result = response_text
    
    # Remove CITATION_MAP section from output (citations are already inline as [1], [2], etc.)
    result = re.sub(r'\n*CITATION_MAP:\s*\n(?:\[\d+\][^\n]+\n?)+', '', result, flags=re.IGNORECASE)
    
    # Handle legacy HTML comment format
    sorted_markers = sorted(markers, key=lambda m: m['position'], reverse=True)
    
    for marker in sorted_markers:
        if 'citation_num' not in marker:  # Only for legacy format
            pattern = f'<!--CITE:{re.escape(marker["opinion_id"])}\\|{marker["page_number"]}\\|"{re.escape(marker["quote"])}"-->'
            sid = position_to_sid.get(marker['position'])
            if sid:
                result = re.sub(pattern, f' [{sid}]', result, count=1)
            else:
                result = re.sub(pattern, '', result, count=1)
    
    # Clean up any remaining legacy markers
    result = re.sub(r'<!--CITE:[^>]+-->', '', result)
    
    return result.strip()


def apply_per_statement_provenance_gating(
    answer_markdown: str,
    sources: List[Dict]
) -> Tuple[str, List[Dict]]:
    """Apply per-statement provenance gating to ensure attorney-safe outputs.
    
    For any statement that attributes a holding to a specific case,
    requires at least one STRONG/MODERATE verified citation.
    Unsupported statements are tracked in statement_support metadata for frontend display.
    
    Returns:
        modified_answer: The answer markdown (unchanged)
        statement_support: List of statement support records with verification status
    """
    # Build lookup of verified citations by case name
    verified_cases = {}  # case_name_lower -> list of verified source sids
    for s in sources:
        tier = s.get('citation_verification', {}).get('tier', s.get('tier', 'unverified'))
        if tier in ('strong', 'moderate'):
            case_name = s.get('case_name', '').lower()
            if case_name:
                if case_name not in verified_cases:
                    verified_cases[case_name] = []
                verified_cases[case_name].append(s.get('sid', '?'))
    
    # Patterns that indicate case-attributed statements
    # e.g., "In Alice, the Court held...", "The Alice decision established...", "According to KSR..."
    case_attribution_patterns = [
        r'\b(In|Under|According to|Per|Following|Applying|Citing|As stated in|As held in)\s+([A-Z][a-zA-Z\-\'\s]+(?:v\.?\s+[A-Z][a-zA-Z\-\'\s]+)?)',
        r'\b(The\s+)?([A-Z][a-zA-Z\-\']+(?:\s+v\.?\s+[A-Z][a-zA-Z\-\']+)?)\s+(court|Court|decision|case|holding|held|established|ruled|stated|found|concluded)',
        r'([A-Z][a-zA-Z\-\']+(?:\s+v\.?\s+[A-Z][a-zA-Z\-\']+)?)\s+requires\b',
        r'([A-Z][a-zA-Z\-\']+(?:\s+v\.?\s+[A-Z][a-zA-Z\-\']+)?)\s+test\b',
        r'([A-Z][a-zA-Z\-\']+(?:\s+v\.?\s+[A-Z][a-zA-Z\-\']+)?)\s+framework\b',
    ]
    
    statement_support = []
    modified_lines = []
    
    # Split into sentences for analysis
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', answer_markdown)
    
    for sent_idx, sentence in enumerate(sentences):
        is_supported = True
        supporting_sids = []
        mentioned_cases = []
        
        # Check for inline citations in this sentence
        cite_refs = re.findall(r'\[(\d+)\]', sentence)
        for ref in cite_refs:
            # Find the source with this sid
            for s in sources:
                if s.get('sid') == ref:
                    tier = s.get('citation_verification', {}).get('tier', s.get('tier', 'unverified'))
                    if tier in ('strong', 'moderate'):
                        supporting_sids.append(ref)
                    break
        
        # Check for case-attributed statements
        for pattern in case_attribution_patterns:
            for match in re.finditer(pattern, sentence, re.IGNORECASE):
                # Extract the case name from the match
                case_name = None
                for group in match.groups():
                    if group and re.search(r'[A-Z]', group):
                        case_name = group.strip()
                        break
                
                if case_name:
                    # Clean up case name
                    case_name_lower = case_name.lower().strip()
                    # Remove common prefixes
                    for prefix in ['the ', 'in ', 'under ']:
                        if case_name_lower.startswith(prefix):
                            case_name_lower = case_name_lower[len(prefix):]
                    
                    mentioned_cases.append(case_name)
                    
                    # Check if this case has verified support
                    has_support = False
                    for verified_case in verified_cases:
                        if case_name_lower in verified_case or verified_case in case_name_lower:
                            has_support = True
                            supporting_sids.extend(verified_cases[verified_case])
                            break
                    
                    # Also check if there's a citation in this sentence
                    if cite_refs and supporting_sids:
                        has_support = True
                    
                    if not has_support:
                        is_supported = False
        
        # Record statement support
        statement_support.append({
            "sentence_idx": sent_idx,
            "text": sentence[:100] + "..." if len(sentence) > 100 else sentence,
            "supported": is_supported or not mentioned_cases,  # Only unsupported if cases were mentioned without support
            "mentioned_cases": mentioned_cases,
            "supporting_citations": list(set(supporting_sids))
        })
        
        modified_lines.append(sentence)
    
    modified_answer = ' '.join(modified_lines)
    return modified_answer, statement_support


def generate_fallback_response(pages: List[Dict], search_terms: List[str], search_query: str = "") -> Dict[str, Any]:
    """Generate response when LLM is unavailable - use top pages as sources."""
    sources = []
    for i, page in enumerate(pages[:5], 1):
        if page.get('page_number', 0) < 1:
            continue
        exact_quote = extract_exact_quote_from_page(page['text'], max_len=200)
        if exact_quote and verify_quote_strict(exact_quote, page['text']):
            sources.append(normalize_source({
                "sid": str(i),
                "opinion_id": page['opinion_id'],
                "case_name": page['case_name'],
                "appeal_no": page['appeal_no'],
                "release_date": page['release_date'],
                "page_number": page['page_number'],
                "quote": exact_quote,
                "viewer_url": f"/pdf/{page['opinion_id']}?page={page['page_number']}",
                "pdf_url": page.get('pdf_url', ''),
                "courtlistener_url": page.get('courtlistener_url', ''),
                "tier": "moderate",
                "binding_method": "fallback"
            }))
    
    pages_sample = [{"opinion_id": p.get("opinion_id"), "case_name": p.get("case_name"), "page_number": p.get("page_number")} for p in pages[:5]]
    
    if not sources:
        return standardize_response({
            "answer_markdown": "NOT FOUND IN PROVIDED OPINIONS.",
            "sources": [],
            "debug": {
                "claims": [],
                "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 1},
                "search_query": search_query,
                "search_terms": search_terms,
                "pages_count": len(pages),
                "pages_sample": pages_sample,
                "markers_count": 0,
                "markers": [],
                "sources_count": 0,
                "sources": [],
                "raw_response": None,
                "return_branch": "fallback_no_sources"
            }
        })
    
    markers = " ".join([f"[{s['sid']}]" for s in sources])
    answer = f"**Relevant Excerpts Found**\n\nThe following excerpts from ingested opinions may be relevant to your query. {markers}"
    
    return standardize_response({
        "answer_markdown": answer,
        "sources": sources,
        "debug": {
            "claims": [{"id": i+1, "text": s['quote'][:100], "citations": [s]} for i, s in enumerate(sources)],
            "support_audit": {"total_claims": len(sources), "supported_claims": len(sources), "unsupported_claims": 0},
            "search_query": search_query,
            "search_terms": search_terms,
            "pages_count": len(pages),
            "pages_sample": pages_sample,
            "markers_count": 0,
            "markers": [],
            "sources_count": len(sources),
            "sources": [{"sid": s.get("sid"), "opinion_id": s.get("opinion_id"), "page_number": s.get("page_number"), "quote": s.get("quote", "")[:120]} for s in sources[:10]],
            "raw_response": None,
            "return_branch": "fallback_with_sources"
        }
    })

def get_previous_action_items(conversation_id: str) -> List[Dict]:
    """Get action items from the most recent disambiguation response in the conversation."""
    if not conversation_id:
        return []
    
    try:
        messages = db.get_messages(conversation_id)
        # Look for the most recent assistant message with action_items
        for msg in reversed(messages):
            if msg.get('role') == 'assistant' and msg.get('citations'):
                citations = msg.get('citations')
                if isinstance(citations, str):
                    citations = json.loads(citations)
                action_items = citations.get('action_items', [])
                if action_items:
                    return action_items
        return []
    except Exception:
        return []

def get_previous_case_context(conversation_id: str) -> Optional[Dict]:
    """Get the case mentioned in the most recent exchange, for pronoun resolution."""
    if not conversation_id:
        return None
    
    try:
        messages = db.get_messages(conversation_id)
        # Look for the most recent assistant message with sources
        for msg in reversed(messages):
            if msg.get('role') == 'assistant' and msg.get('citations'):
                citations = msg.get('citations')
                if isinstance(citations, str):
                    citations = json.loads(citations)
                
                # Check for sources array
                sources = citations.get('sources', [])
                if sources and len(sources) > 0:
                    # Get unique cases from sources, counting occurrences
                    case_counts = {}
                    case_info = {}
                    for s in sources:
                        oid = s.get('opinionId') or s.get('opinion_id')
                        if oid:
                            case_counts[oid] = case_counts.get(oid, 0) + 1
                            if oid not in case_info:
                                case_info[oid] = {
                                    'opinion_id': oid,
                                    'case_name': s.get('caseName') or s.get('case_name', ''),
                                    'appeal_no': s.get('appealNo') or s.get('appeal_no', '')
                                }
                    
                    if len(case_counts) == 1:
                        # Only one case - use it
                        return list(case_info.values())[0]
                    elif len(case_counts) > 1:
                        # Multiple cases - use the one with most sources (most discussed)
                        top_case_id = max(case_counts.keys(), key=lambda k: case_counts[k])
                        return case_info[top_case_id]
                    return None
                
                # Check for action_items (disambiguation) - use first if only one
                action_items = citations.get('action_items', [])
                if action_items and len(action_items) == 1:
                    item = action_items[0]
                    return {
                        'opinion_id': item.get('opinion_id'),
                        'case_name': item.get('label', ''),
                        'appeal_no': ''
                    }
        return None
    except Exception:
        return None

def has_pronoun_reference(message: str) -> bool:
    """Check if message contains pronouns that likely refer to a previous case."""
    pronouns = [
        r'\bits\b', r'\bthis case\b', r'\bthat case\b', r'\bthe case\b',
        r'\bthe opinion\b', r'\bthis opinion\b', r'\bthat opinion\b',
        r'\bthe holding\b', r'\bthe ruling\b', r'\bthe decision\b'
    ]
    msg_lower = message.lower()
    return any(re.search(p, msg_lower) for p in pronouns)

def curate_sources_for_mode(sources: List[Dict], attorney_mode: bool) -> List[Dict]:
    """Filter and prioritize sources by confidence and relevance for response mode."""
    if not sources:
        return []

    def _tier_rank(src: Dict[str, Any]) -> int:
        tier = src.get('citation_verification', {}).get('tier', src.get('tier', 'unverified'))
        return {'strong': 4, 'moderate': 3, 'weak': 2, 'unverified': 1}.get(tier, 1)

    ranked = sorted(
        sources,
        key=lambda s: (
            _tier_rank(s),
            s.get('score', 0),
            s.get('explain', {}).get('composite_score', 0)
        ),
        reverse=True,
    )

    if attorney_mode:
        verified = [s for s in ranked if _tier_rank(s) >= 3]
        return (verified or ranked)[:8]

    return ranked[:10]


def append_citation_appendix(answer_markdown: str, sources: List[Dict]) -> str:
    """Append an interactive citation appendix so bottom citations are always clickable."""
    if not sources:
        return answer_markdown

    primary = []
    background = []
    for s in sources:
        tier = s.get('citation_verification', {}).get('tier', s.get('tier', 'unverified'))
        entry = f"- [{s.get('sid')}] **{s.get('case_name', 'Unknown Case')}** ({tier.upper()}, p.{s.get('page_number', '?')})"
        if tier in ('strong', 'moderate'):
            primary.append(entry)
        else:
            background.append(entry)

    appendix_parts = ["", "---", "### Citation Appendix"]
    if primary:
        appendix_parts.append("**Controlling / Highly Reliable**")
        appendix_parts.extend(primary)
    if background:
        appendix_parts.append("**Background / Lower-Confidence (use cautiously)**")
        appendix_parts.extend(background)

    return answer_markdown.rstrip() + "\n" + "\n".join(appendix_parts)


async def generate_chat_response(
    message: str,
    opinion_ids: Optional[List[str]] = None,
    conversation_id: Optional[str] = None,
    party_only: bool = False,
    attorney_mode: bool = False
) -> Dict[str, Any]:
    
    import time as _time
    _start_time = _time.time()
    _run_id = None
    _doctrine_tag = None
    _pages_for_audit = []
    _context_pages_for_audit = []
    _context_tokens = 0
    _model_name = "gpt-4o"
    _temperature = 0.1
    _max_tokens = 1500
    
    try:
        _run_id = voyager.create_query_run(conversation_id, message)
    except Exception as _ve:
        logging.debug(f"Voyager run creation skipped: {_ve}")
    
    if opinion_ids and len(opinion_ids) == 0:
        opinion_ids = None
    
    original_message = message
    resolved_opinion_id = None  # Will be set if we resolve to a specific case
    
    # PRIORITY 1: Check for pending disambiguation state (stored in DB)
    # This takes precedence over any other logic to prevent re-searching
    if conversation_id:
        pending_state = db.get_pending_disambiguation(conversation_id)
        logging.info(f"[DISAMBIGUATION] conversation_id={conversation_id}, pending_state={pending_state is not None}, message='{message}'")
        if pending_state:
            logging.info(f"[DISAMBIGUATION] pending_state contains {len(pending_state.get('candidates', []))} candidates")
            candidates = pending_state.get('candidates', [])
            original_query = pending_state.get('original_query', '')
            option_num = resolve_candidate_reference(message, candidates)
            logging.info(f"[DISAMBIGUATION] resolve_candidate_reference returned: {option_num}")
            
            if option_num:
                if 1 <= option_num <= len(candidates):
                    # Valid selection - resolve directly from stored candidates
                    selected = candidates[option_num - 1]
                    resolved_opinion_id = selected.get('opinion_id')
                    case_name = selected.get('label', '')
                    
                    # If selected case has no opinion_id, it's not in our database
                    if not resolved_opinion_id:
                        # Try to find it by case name
                        case_lookup = db.search_pages(case_name, None, limit=1, party_only=True)
                        if case_lookup:
                            resolved_opinion_id = case_lookup[0].get('opinion_id')
                            logging.info(f"Disambiguation: Found opinion_id {resolved_opinion_id} for case '{case_name}'")
                        else:
                            # Case not in database - keep pending state so user can select another option
                            logging.info(f"Disambiguation: Case '{case_name}' not found in database, keeping pending state")
                            # List the other available options
                            other_options = [f"{c.get('id')}. {c.get('label')}" for c in candidates if c.get('id') != selected.get('id')]
                            other_options_text = "\n".join(other_options) if other_options else "No other options available."
                            return standardize_response({
                                "answer_markdown": f"**{case_name}** is not currently in our indexed database.\n\nThis case may be referenced in other opinions but hasn't been ingested yet.\n\n**Available indexed options:**\n{other_options_text}\n\nYou can reply with the number of another option, or ask a new question.",
                                "sources": [],
                                "debug": {
                                    "claims": [],
                                    "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 0},
                                    "search_query": case_name,
                                    "search_terms": [],
                                    "pages_count": 0,
                                    "pages_sample": [],
                                    "markers_count": 0,
                                    "markers": [],
                                    "sources_count": 0,
                                    "sources": [],
                                    "raw_response": "",
                                    "return_branch": "disambiguation_case_not_found"
                                }
                            })
                    
                    # Success - we found the case, now clear disambiguation state
                    db.clear_pending_disambiguation(conversation_id)
                    
                    # Use original query context for the resolved case, but make it specific
                    if original_query:
                        # Replace generic terms with specific case name to prevent re-ambiguity
                        # e.g., "What is the holding of Google?" -> "What is the holding of Google LLC v. Ecofactor, Inc.?"
                        message = f"{original_query} (Specifically: {case_name})"
                    party_only = False
                    
                    # Log for debugging
                    logging.info(f"Disambiguation resolved: selected #{option_num} = {case_name} (opinion_id={resolved_opinion_id})")
                else:
                    # Out of range selection
                    db.clear_pending_disambiguation(conversation_id)
                    return standardize_response({
                        "answer_markdown": f"I only have {len(candidates)} option(s). Please reply with a number from 1 to {len(candidates)}, or restate your question.",
                        "sources": [],
                        "debug": {
                            "claims": [],
                            "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 0},
                            "search_query": message,
                            "search_terms": [],
                            "pages_count": 0,
                            "pages_sample": [],
                            "markers_count": 0,
                            "markers": [],
                            "sources_count": 0,
                            "sources": [],
                            "raw_response": "",
                            "return_branch": "disambiguation_out_of_range"
                        }
                    })
            else:
                # Keep pending state for one additional conversational follow-up.
                if is_probable_disambiguation_followup(message):
                    options_text = "\n".join([f"{c.get('id')}. {c.get('label')}" for c in candidates])
                    return standardize_response({
                        "answer_markdown": (
                            "I still have multiple possible case matches. "
                            "Please pick one option by number (or mention party name/appeal number):\n\n"
                            f"{options_text}"
                        ),
                        "sources": [],
                        "disambiguation": {
                            "pending": True,
                            "candidates": candidates
                        },
                        "debug": {
                            "claims": [],
                            "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 0},
                            "search_query": message,
                            "search_terms": [],
                            "pages_count": 0,
                            "pages_sample": [],
                            "markers_count": 0,
                            "markers": [],
                            "sources_count": 0,
                            "sources": [],
                            "raw_response": "",
                            "return_branch": "disambiguation_pending_followup"
                        }
                    })

                # User sent a new query, not a selection - clear old disambiguation
                db.clear_pending_disambiguation(conversation_id)
    
    # If we resolved an option to a specific case, search within that case
    if resolved_opinion_id:
        opinion_ids = [str(resolved_opinion_id)]
    
    # PRIORITY 2: Check for pronoun references to previously discussed case (e.g., "its holding", "this case")
    if not resolved_opinion_id and conversation_id and has_pronoun_reference(message):
        prev_case = get_previous_case_context(conversation_id)
        if prev_case and prev_case.get('opinion_id'):
            resolved_opinion_id = prev_case['opinion_id']
            opinion_ids = [str(resolved_opinion_id)]
            party_only = False  # Search full text within the resolved case
    
    # PRIORITY SEARCH: If query mentions a specific case (X v. Y pattern), 
    # search for that case FIRST to ensure it appears in context
    # Support MULTIPLE named cases in a single query (e.g., "Amgen v. Sanofi" AND "Honeywell v. 3G")
    named_case_pages = []
    all_named_case_pages = []  # Collect pages from ALL mentioned cases
    processed_case_names = set()  # Track which cases we've already processed
    
    # SYSTEMIC FIX: Legal Interrogatives list - words that should never be part of party names
    legal_interrogatives = {
        'say', 'says', 'said', 'about', 'regarding', 'holding', 'opinion', 'rule', 
        'standard', 'test', 'mean', 'meaning', 'claim', 'construction', 'plain',
        'decision', 'case', 'court', 'concerning', 'hold', 'doctrine', 'analysis',
        'framework', 'obviousness', 'infringement', 'validity', 'state', 'states',
        'stated', 'discuss', 'discusses', 'discussed', 'require', 'requires', 
        'required', 'use', 'using', 'intrinsic', 'extrinsic', 'evidence', 'patent',
        'patents', 'interpret', 'interpretation', 'ordinary', 'terms', 'term',
        'language', 'define', 'defines', 'defined', 'explain', 'explains', 'explained',
        'address', 'addresses', 'addressed', 'apply', 'applies', 'applied',
        'establish', 'establishes', 'established', 'determine', 'determines',
        'discuss', 'discusses', 'discussed', 'regarding', 'concerning', 'about'
    }
    
    # Legal entity suffixes that should terminate defendant capture
    entity_suffixes = {'inc', 'inc.', 'corp', 'corp.', 'co', 'co.', 'ltd', 'ltd.',
                       'llc', 'l.l.c.', 'llp', 'l.l.p.', 'gmbh', 'plc', 'lp', 'l.p.',
                       'na', 'n.a.', 'pllc', 'pc', 'p.c.', 'sa', 's.a.', 'ag',
                       'enterprises', 'international', 'technologies', 'systems',
                       'industries', 'group', 'company', 'corporation', 'incorporated'}
    
    # Look for case citations like "Phillips v. AWH Corp." or "Alice Corp. v. CLS Bank"
    # Case-insensitive for middle words to handle "H-W technology v. Overstock" (lowercase 'technology')
    case_patterns = re.findall(
        r'\b([A-Z][a-zA-Z\'\-\.]+(?:\s+[A-Za-z][a-zA-Z\'\-\.]+){0,2})\s+v\.?\s+([A-Za-z][a-zA-Z\'\-\.]+(?:\s+[A-Za-z\'\-\.]+){0,5})',
        message
    )
    # Filter out patterns where plaintiff starts with common verbs/adjectives
    stop_words = {'Explain', 'Based', 'Using', 'According', 'Following', 'Regarding', 
                  'What', 'How', 'Why', 'When', 'Where', 'Does', 'Did', 'Can', 'Should'}
    
    for match in case_patterns:
        plaintiff = match[0].strip()
        defendant = match[1].strip()
        
        # Strip leading stop words from plaintiff (sentence starters like "Does", "What")
        plaintiff_words = plaintiff.split()
        while plaintiff_words and plaintiff_words[0] in stop_words:
            plaintiff_words.pop(0)
        plaintiff = ' '.join(plaintiff_words)
        
        # Skip if no plaintiff remains after stripping
        if not plaintiff:
            continue
        
        # SYSTEMIC FIX: Apply hard anchor after entity suffix OR limit to 4 words max
        def_words = defendant.split()
        cleaned_words = []
        for i, word in enumerate(def_words):
            word_lower = word.lower().rstrip('.,?!')
            
            # Stop if we hit a legal interrogative
            if word_lower in legal_interrogatives:
                break
            
            cleaned_words.append(word)
            
            # Stop after entity suffix (e.g., "Corp.", "Inc.")
            if word_lower in entity_suffixes:
                break
            
            # Hard limit: max 4 words after v. unless entity suffix found
            if i >= 3:
                break
        
        defendant = ' '.join(cleaned_words) if cleaned_words else ''
        
        if not defendant or not plaintiff:
            continue
        
        # Build the case query
        case_query = f"{plaintiff} v. {defendant}"
        
        # DEBUG: Log parsed party name for verification
        logging.info(f"DEBUG: Parsed Party Name: [{case_query}] from query")
        
        if not party_only:
            logging.info(f"Detected specific case name in query: {case_query}")
            # Find document IDs matching the case name
            named_case_ids = db.find_documents_by_name(case_query)
            if not named_case_ids:
                named_case_ids = db.find_documents_by_name(defendant)
            
            if named_case_ids:
                logging.info(f"Found {len(named_case_ids)} matching documents for: {case_query}")
                # Extract key legal terms from the query for better FTS matching
                # Try successively simpler queries until we get results
                search_terms = [
                    message,  # Full query first
                    ' '.join([w for w in message.split() if len(w) > 4 and w.lower() not in 
                              {'what', 'which', 'where', 'when', 'does', 'according', 'explain', 'describe'}]),
                ]
                # Add common legal topic extractions
                legal_terms = []
                if 'claim construction' in message.lower():
                    legal_terms.append('claim construction')
                if 'evidence' in message.lower():
                    legal_terms.append('intrinsic evidence')
                if 'obviousness' in message.lower():
                    legal_terms.append('obviousness')
                if 'infringement' in message.lower():
                    legal_terms.append('infringement')
                if 'indefinite' in message.lower() or 'indefiniteness' in message.lower():
                    legal_terms.append('indefinite')
                if 'eligible' in message.lower() or 'eligibility' in message.lower() or '101' in message:
                    legal_terms.append('eligible abstract')
                if 'written description' in message.lower():
                    legal_terms.append('written description')
                if 'enablement' in message.lower():
                    legal_terms.append('enablement')
                if 'anticipat' in message.lower():  # anticipation, anticipated
                    legal_terms.append('anticipation prior art')
                if legal_terms:
                    search_terms.append(' '.join(legal_terms))
                # Also try searching with just key legal words from case pages
                search_terms.append('patent claim invalid')
                
                for search_term in search_terms:
                    if not search_term.strip():
                        continue
                    named_case_pages = db.search_pages(search_term, named_case_ids, limit=10, party_only=False)
                    if named_case_pages:
                        logging.info(f"Found {len(named_case_pages)} pages from named case using: '{search_term[:50]}...'")
                        break
                
                # CRITICAL FIX: If no FTS matches but we found the case, get pages anyway
                # This lets the AI explain what the case is actually about
                if not named_case_pages and named_case_ids:
                    logging.info(f"No FTS matches for named case, fetching first pages from {len(named_case_ids)} documents")
                    # Get first few pages from the case using a broad search
                    named_case_pages = db.search_pages('court patent', named_case_ids, limit=8, party_only=False)
                    if not named_case_pages:
                        # Ultra-fallback: just get any chunks from the documents
                        named_case_pages = db.search_pages('', named_case_ids, limit=8, party_only=True)
                    if named_case_pages:
                        logging.info(f"Retrieved {len(named_case_pages)} fallback pages from named case")
                
                # MULTI-CASE SUPPORT: Accumulate pages from ALL named cases instead of breaking
                if named_case_pages:
                    for page in named_case_pages:
                        key = (page.get('opinion_id'), page.get('page_number'))
                        if key not in processed_case_names:
                            processed_case_names.add(key)
                            all_named_case_pages.append(page)
                    logging.info(f"Accumulated {len(all_named_case_pages)} total pages from {len([m for m in case_patterns[:case_patterns.index(match)+1]])} named cases")
                    # Continue to next case pattern instead of breaking
                    continue
    
    pages = db.search_pages(message, opinion_ids, limit=15, party_only=party_only)
    
    # P0: Doctrine-triggered authoritative candidate injection
    # Classify query to determine if controlling SCOTUS cases should be injected
    doctrine_tag = ranking_scorer.classify_doctrine_tag(message)
    _doctrine_tag = doctrine_tag
    if doctrine_tag:
        logging.info(f"[DOCTRINE TAG] Query classified as: {doctrine_tag}")
        controlling_case_patterns = ranking_scorer.get_controlling_framework_candidates(doctrine_tag)
        if controlling_case_patterns:
            logging.info(f"[CONTROLLING INJECTION] Fetching SCOTUS candidates for doctrine={doctrine_tag}: {controlling_case_patterns}")
            controlling_pages = db.fetch_controlling_scotus_pages(controlling_case_patterns, pages_per_case=2)
            if controlling_pages:
                logging.info(f"[CONTROLLING INJECTION] Injected {len(controlling_pages)} controlling SCOTUS pages")
                # Debug: log the first few injected pages with their origin
                for cp in controlling_pages[:3]:
                    logging.info(f"[CONTROLLING INJECTION] Page: case={cp.get('case_name','?')[:40]}, origin={cp.get('origin')}, page={cp.get('page_number')}")
                # Deduplicate and merge controlling pages with search results
                seen_keys = set()
                merged_controlling = []
                # Add controlling pages first (highest priority)
                for p in controlling_pages:
                    key = (p.get('opinion_id'), p.get('page_number'))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        merged_controlling.append(p)
                # Add original search results
                for p in pages:
                    key = (p.get('opinion_id'), p.get('page_number'))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        merged_controlling.append(p)
                pages = merged_controlling
            else:
                logging.warning(f"[CONTROLLING INJECTION] No SCOTUS cases found for {controlling_case_patterns} - may be missing from corpus")
    
    # Merge named case results with FTS results, prioritizing ALL named cases
    # Use all_named_case_pages which contains pages from ALL mentioned cases
    if all_named_case_pages:
        seen_keys = set()
        merged_pages = []
        # Add ALL named case pages first (these are already deduplicated)
        for p in all_named_case_pages:
            key = (p.get('opinion_id'), p.get('page_number'))
            if key not in seen_keys:
                seen_keys.add(key)
                merged_pages.append(p)
        # Add remaining FTS results
        for p in pages:
            key = (p.get('opinion_id'), p.get('page_number'))
            if key not in seen_keys:
                seen_keys.add(key)
                merged_pages.append(p)
        pages = merged_pages[:15]  # Keep top 15
        logging.info(f"Context Merge Success - {len(all_named_case_pages)} named case pages + FTS = {len(pages)} total")
    
    # Phase 1 Smartness: Augment retrieval when baseline results are thin
    # This is ADDITIVE only - never replaces baseline, just adds candidates
    _phase1_telemetry = None
    try:
        from backend.smart.augmenter import augment_retrieval
        from backend.smart.config import SMART_EMBED_RECALL_ENABLED, SMART_QUERY_DECOMPOSE_ENABLED
        
        if SMART_EMBED_RECALL_ENABLED or SMART_QUERY_DECOMPOSE_ENABLED:
            def search_func(q, limit=10):
                return db.search_pages(q, opinion_ids, limit=limit, party_only=False)
            
            pages, _phase1_telemetry = augment_retrieval(
                query=message,
                baseline_results=pages,
                search_func=search_func
            )
    except Exception as _phase1_err:
        logging.debug(f"Phase 1 augmentation skipped: {_phase1_err}")
    
    search_terms = message.split()
    
    # Fallback retrieval strategy for natural language questions
    # PostgreSQL plainto_tsquery uses AND for multiple words, which often fails for long questions
    # Trigger fallback when: (1) no pages returned, OR (2) very few pages for a long query
    is_long_query = len(message.split()) >= 5
    needs_fallback = (not pages) or (len(pages) < 3 and is_long_query)
    
    if needs_fallback and not party_only:
        # QUERY EXPANSION: Use GPT-4o to generate related legal keywords for conceptual queries
        # This helps find relevant cases for abstract legal concepts like "after-arising technology"
        expanded_terms = expand_query_with_legal_terms(message)
        
        if expanded_terms:
            # Search with expanded terms first
            logging.info(f"Query expansion searching with: {expanded_terms}")
            all_expanded_pages = []
            seen_expanded_keys = set()
            
            for term in expanded_terms:
                results = db.search_pages(term, opinion_ids, limit=5, party_only=False)
                for p in results:
                    key = (p.get('opinion_id'), p.get('page_number'))
                    if key not in seen_expanded_keys:
                        seen_expanded_keys.add(key)
                        all_expanded_pages.append(p)
            
            if all_expanded_pages:
                # Sort by rank and use expanded results
                all_expanded_pages.sort(key=lambda x: x.get('rank', 0), reverse=True)
                
                # CONTEXT MERGE PERSISTENCE: Preserve named case pages - merge AFTER query expansion
                if named_case_pages:
                    # Add named case pages first (highest priority - they must NEVER be dropped)
                    seen_keys = set()
                    merged = []
                    for p in named_case_pages:
                        key = (p.get('opinion_id'), p.get('page_number'))
                        if key not in seen_keys:
                            seen_keys.add(key)
                            merged.append(p)
                    named_case_count = len(merged)
                    # Then add expanded results
                    for p in all_expanded_pages:
                        key = (p.get('opinion_id'), p.get('page_number'))
                        if key not in seen_keys:
                            seen_keys.add(key)
                            merged.append(p)
                    pages = merged[:15]
                    # DEBUG: Log context merge success
                    logging.info(f"DEBUG: Context Merge Success - {named_case_count} named case pages + {len(pages) - named_case_count} expanded pages = {len(pages)} total")
                else:
                    pages = all_expanded_pages[:15]
                    
                search_terms = expanded_terms
                logging.info(f"Query expansion found {len(pages)} pages")
        
        # If expansion didn't help, fall back to manual token extraction
        if not pages or len(pages) < 3:
            # Common English stopwords to remove
            stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'in', 'from', 'to', 'of', 'for', 
                         'on', 'at', 'by', 'with', 'it', 'its', 'this', 'that', 'be', 'been', 'being',
                         'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should',
                         'may', 'might', 'must', 'shall', 'can', 'and', 'or', 'but', 'if', 'when',
                         'what', 'how', 'why', 'where', 'which', 'who', 'whom', 'whose', 'than', 'then',
                         'so', 'as', 'not', 'no', 'yes', 'about', 'into', 'through', 'during', 'before',
                         'after', 'above', 'below', 'between', 'under', 'again', 'further', 'once',
                         'here', 'there', 'all', 'each', 'few', 'more', 'most', 'other', 'some', 'such',
                         'only', 'own', 'same', 'too', 'very', 'just', 'also', 'now', 'even', 'still',
                         'already', 'always', 'never', 'ever', 'often', 'sometimes', 'usually'}
            
            # Clean and tokenize the query
            # Remove section symbols, punctuation, and normalize
            cleaned_query = re.sub(r'[§\?!.,;:\'"()\[\]{}]', ' ', message)
            tokens = cleaned_query.lower().split()
            
            # Filter: remove stopwords, short tokens (<=2 chars), and pure numbers
            meaningful_tokens = [
                t for t in tokens 
                if t not in stopwords and len(t) > 2 and not t.isdigit()
            ]
            
            # Add domain-specific legal terms based on query context
            domain_terms = []
            message_lower = message.lower()
            if 'reissue' in message_lower or '251' in message_lower:
                domain_terms.extend(['reissue', 'recapture', 'broadening', 'broaden', 'enlarge', 'scope', 'original'])
            if 'claim' in message_lower:
                domain_terms.extend(['claim', 'claims', 'limitation', 'element'])
            if 'patent' in message_lower or 'prior art' in message_lower:
                domain_terms.extend(['patent', 'obviousness', 'anticipation', 'novelty', 'prior'])
            if 'infringement' in message_lower:
                domain_terms.extend(['infringement', 'infringe', 'infringes', 'literal', 'doctrine', 'equivalents'])
            if 'alice' in message_lower or 'mayo' in message_lower or 'eligibility' in message_lower or '101' in message_lower:
                domain_terms.extend(['alice', 'mayo', 'eligibility', 'abstract', 'idea', 'ineligible', 'section', 'step'])
            
            # Combine meaningful tokens with domain terms (deduplicate)
            all_search_tokens = list(set(meaningful_tokens + domain_terms))
            
            # Search each token individually and merge results
            all_pages = []
            seen_page_keys = set()
            
            for token in all_search_tokens:
                if token and len(token) > 2:
                    results = db.search_pages(token, opinion_ids, limit=5, party_only=False)
                    for p in results:
                        key = (p.get('opinion_id'), p.get('page_number'))
                        if key not in seen_page_keys:
                            seen_page_keys.add(key)
                            all_pages.append(p)
            
            # Sort by rank (higher is better) and keep top 15
            all_pages.sort(key=lambda x: x.get('rank', 0), reverse=True)
            
            # CONTEXT MERGE PERSISTENCE: Preserve named case pages in manual fallback too
            if named_case_pages:
                seen_keys = set()
                merged = []
                for p in named_case_pages:
                    key = (p.get('opinion_id'), p.get('page_number'))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        merged.append(p)
                named_case_count = len(merged)
                for p in all_pages:
                    key = (p.get('opinion_id'), p.get('page_number'))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        merged.append(p)
                pages = merged[:15]
                logging.info(f"DEBUG: Context Merge Success (fallback) - {named_case_count} named case pages preserved")
            else:
                pages = all_pages[:15]
            
            # Update search_terms to reflect what we actually searched for
            if pages:
                search_terms = all_search_tokens
    
    # Check if query references a specific case name (e.g., "H-W Technologies v. Overstock")
    # and trigger web search if that case isn't in our database
    # Case-insensitive matching for defendant to handle lowercase inputs like "overstock"
    specific_case_match = re.search(r'([A-Z][a-zA-Z0-9\-\.]+(?:\s+[A-Za-z\.]+)*)\s+v\.?\s+([A-Za-z][a-zA-Z0-9\-\.]+(?:\s+[A-Za-z\.]+)*)', message)
    if specific_case_match and pages:
        plaintiff = specific_case_match.group(1).strip()
        defendant = specific_case_match.group(2).strip()
        specific_case_name = f"{plaintiff} v. {defendant}"
        
        # Check if any of our results are from this specific case
        case_names_in_results = [p.get('case_name', '').lower() for p in pages]
        plaintiff_lower = plaintiff.lower().rstrip('s')  # Handle plural (Technologies -> Technology)
        defendant_lower = defendant.lower().rstrip('s')
        
        # Also check with shorter name stems for fuzzy matching
        plaintiff_stem = plaintiff_lower.replace('.', '').replace(',', '').split()[0] if plaintiff_lower else ''
        defendant_stem = defendant_lower.replace('.', '').replace(',', '').split()[0] if defendant_lower else ''
        
        # Check if either party name appears in any of our result case names
        found_specific_case = any(
            (plaintiff_lower in name or defendant_lower in name or
             (plaintiff_stem and plaintiff_stem in name) or 
             (defendant_stem and defendant_stem in name))
            for name in case_names_in_results
        )
        
        if not found_specific_case:
            logging.info(f"Specific case '{specific_case_name}' not found in local results, triggering web search")
            # We have results, but they don't include the specific case the user asked about
            # Trigger web search to find this specific case
            web_search_result = await try_web_search_and_ingest(message, conversation_id)
            
            if web_search_result.get("success") and web_search_result.get("new_pages"):
                # Successfully ingested new case, merge with existing named case pages
                web_pages = web_search_result["new_pages"]
                
                # CONTEXT MERGE PERSISTENCE: Preserve named case pages even after web search
                if named_case_pages:
                    seen_keys = set()
                    merged = []
                    for p in named_case_pages:
                        key = (p.get('opinion_id'), p.get('page_number'))
                        if key not in seen_keys:
                            seen_keys.add(key)
                            merged.append(p)
                    named_case_count = len(merged)
                    for p in web_pages:
                        key = (p.get('opinion_id'), p.get('page_number'))
                        if key not in seen_keys:
                            seen_keys.add(key)
                            merged.append(p)
                    pages = merged[:15]
                    logging.info(f"DEBUG: Context Merge Success (web search) - {named_case_count} named case pages + {len(pages) - named_case_count} web search pages = {len(pages)} total")
                else:
                    pages = web_pages
                
                search_terms = message.split()
                logging.info(f"Web search ingested new case(s), now have {len(pages)} pages")
            elif web_search_result.get("web_search_triggered"):
                # Web search triggered but didn't ingest - include info in response
                web_info = ""
                if web_search_result.get("tavily_answer"):
                    web_info = f"\n\n**Web Search Insight:**\n{web_search_result['tavily_answer'][:500]}..."
                if web_search_result.get("cases_to_ingest"):
                    case_names = [c.get("case_name", "Unknown") for c in web_search_result["cases_to_ingest"][:3]]
                    web_info += f"\n\n**Found Potentially Relevant Cases:**\n- " + "\n- ".join(case_names)
                    web_info += "\n\nThese cases may be ingested in future queries."
                
                if web_info:
                    pass  # We'll still try with existing pages but add web info later
    
    # Detect if the query looks like a question vs a simple party name lookup
    question_indicators = ['what', 'how', 'why', 'when', 'where', 'which', 'who', 
                           'holding', 'held', 'decide', 'rule', 'ruling', 'opinion',
                           'mean', 'explain', 'describe', 'tell', 'does', 'did', 'is', 'are', 'was', 'were',
                           'can', 'could', 'should', 'would', '?']
    message_lower = message.lower()
    is_question = any(word in message_lower for word in question_indicators) or len(message.split()) > 4
    
    # For party-only searches with a simple party name (not a question), list matching cases
    if party_only and pages and not is_question:
        # Group by unique cases
        seen_cases = {}
        for page in pages:
            case_key = page.get('opinion_id')
            if case_key not in seen_cases:
                seen_cases[case_key] = page
        
        # Build sources from matching cases
        sources = []
        for i, (case_id, page) in enumerate(seen_cases.items(), 1):
            sources.append(normalize_source({
                "sid": f"S{i}",
                "opinionId": case_id,
                "opinion_id": case_id,
                "caseName": page.get("case_name", ""),
                "case_name": page.get("case_name", ""),
                "appealNo": page.get("appeal_no", ""),
                "appeal_no": page.get("appeal_no", ""),
                "releaseDate": page.get("release_date", ""),
                "release_date": page.get("release_date", ""),
                "pageNumber": page.get("page_number", 1),
                "page_number": page.get("page_number", 1),
                "quote": extract_exact_quote_from_page(page.get("text", ""), min_len=50, max_len=200),
                "viewerUrl": f"/opinions/{case_id}?page={page.get('page_number', 1)}",
                "viewer_url": f"/opinions/{case_id}?page={page.get('page_number', 1)}",
                "pdfUrl": page.get("pdf_url", ""),
                "pdf_url": page.get("pdf_url", ""),
                "tier": "moderate",
                "binding_method": "party_listing"
            }))
        
        # Build a summary response listing the matching cases
        case_list = "\n".join([
            f"- **{s['caseName']}** ({s['appealNo']}, {s['releaseDate']})" 
            for s in sources
        ])
        answer = f"Found {len(sources)} case(s) where \"{message}\" appears as a party:\n\n{case_list}\n\nAsk a specific question about these cases (e.g., \"What was the holding in the Google case?\") to get detailed analysis."
        
        return standardize_response({
            "answer_markdown": answer,
            "sources": sources,
            "debug": {
                "claims": [],
                "support_audit": {"total_claims": 0, "supported_claims": len(sources), "unsupported_claims": 0},
                "search_query": message,
                "search_terms": search_terms,
                "pages_count": len(pages),
                "pages_sample": [{"opinion_id": p.get("opinion_id"), "case_name": p.get("case_name"), "page_number": p.get("page_number")} for p in pages[:5]],
                "markers_count": 0,
                "markers": [],
                "sources_count": len(sources),
                "sources": [{"sid": s.get("sid"), "opinionId": s.get("opinionId"), "caseName": s.get("caseName")} for s in sources[:10]],
                "raw_response": None,
                "return_branch": "party_only_listing"
            }
        })
    
    # For party-only mode with a question, find cases by party name then search their content
    if party_only and is_question:
        # Extract potential party names from the question (proper nouns, capitalized words)
        words = message.split()
        potential_parties = [w.strip('?.,!') for w in words if len(w) > 0 and w[0].isupper() and len(w) > 2 and w.lower() not in question_indicators]
        
        if potential_parties:
            # Search for cases matching the party names
            party_cases = []
            for party in potential_parties:
                party_pages = db.search_pages(party, None, limit=10, party_only=True)
                for p in party_pages:
                    if p.get('opinion_id') not in [c.get('opinion_id') for c in party_cases]:
                        party_cases.append(p)
            
            if party_cases:
                # Get the opinion IDs from matching party cases
                party_opinion_ids = [str(p.get('opinion_id')) for p in party_cases]
                party_opinion_ids = list(set(party_opinion_ids))
                
                # Extract meaningful search terms from the question (remove stopwords and question words)
                stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'in', 'from', 'to', 'of', 'for', 'on', 'at', 'by', 'with'}
                meaningful_words = [w.strip('?.,!').lower() for w in words 
                                   if w.strip('?.,!').lower() not in stopwords 
                                   and w.strip('?.,!').lower() not in question_indicators
                                   and w.strip('?.,!') not in potential_parties
                                   and len(w.strip('?.,!')) > 2]
                
                # Add legal-specific search terms based on question context
                legal_terms = []
                if any(t in message.lower() for t in ['holding', 'held', 'decide', 'rule', 'ruling']):
                    legal_terms.extend(['affirm', 'reverse', 'remand', 'held', 'hold', 'conclude'])
                
                # Search strategy: try multiple approaches to find relevant content
                # Note: PostgreSQL plainto_tsquery uses AND for multiple words,
                # so we search each term individually and combine results
                
                all_pages = []
                seen_page_keys = set()
                
                # First try meaningful words individually
                for word in meaningful_words:
                    if word and len(word) > 2:
                        results = db.search_pages(word, party_opinion_ids, limit=5, party_only=False)
                        for p in results:
                            key = (p.get('opinion_id'), p.get('page_number'))
                            if key not in seen_page_keys:
                                seen_page_keys.add(key)
                                all_pages.append(p)
                
                # Then try legal terms individually
                for term in legal_terms:
                    results = db.search_pages(term, party_opinion_ids, limit=5, party_only=False)
                    for p in results:
                        key = (p.get('opinion_id'), p.get('page_number'))
                        if key not in seen_page_keys:
                            seen_page_keys.add(key)
                            all_pages.append(p)
                
                # Sort by rank (if available) and limit
                all_pages.sort(key=lambda x: x.get('rank', 0), reverse=True)
                pages = all_pages[:15]
    
    if not pages:
        web_search_result = await try_web_search_and_ingest(message, conversation_id)
        
        if web_search_result.get("success") and web_search_result.get("new_pages"):
            pages = web_search_result["new_pages"]
            search_terms = message.split()
            logging.info(f"Web search found and ingested {len(web_search_result.get('ingested_cases', []))} new cases, now have {len(pages)} pages")
        elif web_search_result.get("web_search_triggered"):
            # Show Tavily answer prominently when we have it
            tavily_answer = web_search_result.get("tavily_answer", "")
            cases_to_ingest = web_search_result.get("cases_to_ingest", [])
            ingested_cases = web_search_result.get("ingested_cases", [])
            
            # Build informative response from web search
            if tavily_answer:
                # Use Tavily answer as main content with disclaimer
                web_info = f"**Based on web search** (not verified from indexed opinions):\n\n{tavily_answer[:1500]}"
                
                # Add failed cases info if any
                failed_cases = [c for c in ingested_cases if c.get("status") != "completed"]
                if cases_to_ingest or failed_cases:
                    case_names = [c.get("case_name", "Unknown") for c in (cases_to_ingest or failed_cases)[:3]]
                    web_info += f"\n\n**Relevant cases found** (PDFs not available for immediate indexing):\n- " + "\n- ".join(case_names)
                    web_info += "\n\n*Ask about a specific case by name to search for it again.*"
            else:
                web_info = "No relevant information found."
                if cases_to_ingest:
                    case_names = [c.get("case_name", "Unknown") for c in cases_to_ingest[:3]]
                    web_info += f"\n\n**Potentially relevant cases found:**\n- " + "\n- ".join(case_names)
            
            return standardize_response({
                "answer_markdown": web_info,
                "sources": [],
                "web_search_triggered": True,
                "debug": {
                    "claims": [],
                    "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 1},
                    "search_query": message,
                    "search_terms": search_terms,
                    "pages_count": 0,
                    "pages_sample": [],
                    "markers_count": 0,
                    "markers": [],
                    "sources_count": 0,
                    "sources": [],
                    "raw_response": None,
                    "return_branch": "not_found_web_search_attempted",
                    "web_search_result": web_search_result
                }
            })
        else:
            # ═══════════════════════════════════════════════════════════════════
            # PHASE 1 FIX: Don't block on empty retrieval - use doctrine mode
            # For doctrinal/procedural queries, let LLM answer from training knowledge
            # ═══════════════════════════════════════════════════════════════════
            query_type = classify_query_type(message)
            retrieval_confidence = RetrievalConfidence.NONE
            
            # Route based on query type per spec:
            # - DOCTRINAL/PROCEDURAL → doctrine-first, retrieval optional
            # - CASE_SPECIFIC → retrieval required
            # - SYNTHESIS → hybrid (answer doctrinally and note limits)
            # - FACT_DEPENDENT → request facts only if outcome truly depends
            
            if query_type in [QueryType.DOCTRINAL, QueryType.PROCEDURAL, QueryType.SYNTHESIS]:
                # Doctrine-answerable queries proceed to LLM without excerpts
                log_decision_path(
                    query=message,
                    query_type=query_type,
                    retrieval_confidence=retrieval_confidence,
                    pages_count=0,
                    doctrine_mode=True,
                    web_search_triggered=web_search_result.get("web_search_triggered", False)
                )
                logging.info(f"DOCTRINE_MODE: Empty retrieval for {query_type} query, proceeding to LLM without excerpts")
                # pages stays empty, but we continue to LLM - it will answer from doctrine
            elif query_type == QueryType.FACT_DEPENDENT:
                # Request missing facts rather than refusing
                log_decision_path(
                    query=message,
                    query_type=query_type,
                    retrieval_confidence=retrieval_confidence,
                    pages_count=0,
                    doctrine_mode=True,  # Will answer doctrinally while requesting facts
                    web_search_triggered=web_search_result.get("web_search_triggered", False)
                )
                logging.info(f"FACT_DEPENDENT: Empty retrieval, will provide doctrinal framework and request facts")
                # Continue to LLM with fact-dependent prompt guidance
            else:
                # CASE_SPECIFIC with no excerpts - this genuinely needs retrieval
                log_decision_path(
                    query=message,
                    query_type=query_type,
                    retrieval_confidence=retrieval_confidence,
                    pages_count=0,
                    refusal_detected=True,
                    web_search_triggered=web_search_result.get("web_search_triggered", False)
                )
                return standardize_response({
                    "answer_markdown": "No matching case found in the indexed opinions.\n\nTo analyze a specific case, please ensure it has been ingested, or try searching with different terms.",
                    "sources": [],
                    "debug": {
                        "claims": [],
                        "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 1},
                        "search_query": message,
                        "search_terms": search_terms,
                        "pages_count": 0,
                        "pages_sample": [],
                        "markers_count": 0,
                        "markers": [],
                        "sources_count": 0,
                        "sources": [],
                        "raw_response": None,
                        "return_branch": "not_found_case_specific_no_pages",
                        "query_type": query_type
                    }
                })
    
    # Assess retrieval confidence for logging
    retrieval_confidence = assess_retrieval_confidence(pages)
    query_type = classify_query_type(message)
    doctrine_mode = len(pages) == 0
    
    log_decision_path(
        query=message,
        query_type=query_type,
        retrieval_confidence=retrieval_confidence,
        pages_count=len(pages),
        doctrine_mode=doctrine_mode
    )
    
    client = get_openai_client()
    
    if not client:
        return generate_fallback_response(pages, search_terms, message)
    
    # Expand pages with adaptive adjacent context to reduce latency on routine queries
    adjacent_window = 1 if len(pages) <= 8 else 2
    expanded_pages = db.fetch_adjacent_pages(pages, window_size=adjacent_window, max_text_chars=1800)
    
    # Build context and conversation summary in parallel for speed
    loop = asyncio.get_event_loop()
    
    async def build_context_async():
        # Use quote-first generation with expanded pages: pre-extract quotable passages
        return await loop.run_in_executor(_executor, lambda: build_context_with_quotes(expanded_pages))
    
    async def build_summary_async():
        return await loop.run_in_executor(_executor, lambda: build_conversation_summary(conversation_id))
    
    async def get_cached_definitions_async():
        # Check if query mentions common legal tests
        cached_def = None
        query_lower = message.lower()
        if 'alice' in query_lower or 'mayo' in query_lower or '101' in query_lower:
            cached_def = get_cached_legal_definition('alice_mayo')
        elif 'obviousness' in query_lower or 'obvious' in query_lower or '103' in query_lower:
            cached_def = get_cached_legal_definition('obviousness')
        elif 'claim construction' in query_lower or 'phillips' in query_lower:
            cached_def = get_cached_legal_definition('claim_construction')
        elif 'willful' in query_lower or 'enhanced damages' in query_lower:
            cached_def = get_cached_legal_definition('willful_infringement')
        return cached_def
    
    # Run context building, summary generation, and cache lookup in parallel
    context_result, conv_summary, cached_definition = await asyncio.gather(
        build_context_async(),
        build_summary_async(),
        get_cached_definitions_async()
    )
    
    # Unpack context result (now returns tuple with quote_registry)
    context, quote_registry = context_result
    
    # Build enhanced system prompt with conversation context and cached definitions
    enhanced_prompt = SYSTEM_PROMPT
    
    if conv_summary:
        enhanced_prompt = conv_summary + "\n" + enhanced_prompt
    
    if cached_definition:
        enhanced_prompt += f"\n\nREFERENCE FRAMEWORK:\n{cached_definition}"
    
    # Handle doctrine mode (no excerpts available)
    if doctrine_mode or not context.strip():
        enhanced_prompt += """

AVAILABLE OPINION EXCERPTS:
[No opinion excerpts were retrieved for this query.]

DOCTRINE MODE ACTIVE: Answer this question from settled Federal Circuit and Supreme Court 
patent law doctrine. You have the legal training and knowledge to answer doctrinal and 
procedural questions accurately. Cite well-known cases as illustrative authority where 
appropriate (e.g., Alice, KSR, Phillips, Nautilus), but do not fabricate specific quotes 
or page numbers.

If this query requires analysis of a SPECIFIC case that was not retrieved, inform the user 
that the specific case is not currently indexed, and offer to answer the general doctrinal 
question instead.
"""
    else:
        enhanced_prompt += "\n\nAVAILABLE OPINION EXCERPTS:\n" + context
    
    # DEBUG: Agentic Reasoning Plan logging
    query_lower = message.lower()
    reasoning_plan = _build_agentic_reasoning_plan(query_lower, pages)
    logging.info(f"DEBUG: Agentic Reasoning Plan: {reasoning_plan}")
    
    # Dynamic max_tokens tuned for faster first response
    # Base 1100 + 350 per opinion_id, capped at 2600
    base_tokens = 1100
    opinion_bonus = len(opinion_ids or []) * 350
    max_tokens = min(2600, base_tokens + opinion_bonus)
    logging.info(f"Dynamic max_tokens: {max_tokens} (base={base_tokens}, bonus={opinion_bonus})")
    
    # Configurable model via environment variable
    model_name = os.environ.get("CHAT_MODEL", "gpt-4o")
    
    try:
        response = await asyncio.wait_for(
            loop.run_in_executor(
                _executor,
                lambda: client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": enhanced_prompt},
                        {"role": "user", "content": message}
                    ],
                    temperature=0.1,  # Lower for more deterministic, less hallucination
                    max_tokens=max_tokens,
                    timeout=90.0  # Increased API timeout
                )
            ),
            timeout=120.0  # Increased asyncio timeout
        )
        
        raw_answer = response.choices[0].message.content or "No response generated."
        
        # DEBUG: Log the raw AI response for troubleshooting
        logging.info(f"DEBUG: AI Raw Response (first 500 chars): {raw_answer[:500]}")
        
        # ═══════════════════════════════════════════════════════════════════
        # PHASE 1: Post-response issue detection and logging
        # ═══════════════════════════════════════════════════════════════════
        response_issues = detect_response_issues(raw_answer)
        
        # Update decision path log with response analysis
        log_decision_path(
            query=message,
            query_type=query_type,
            retrieval_confidence=retrieval_confidence,
            pages_count=len(pages),
            doctrine_mode=doctrine_mode,
            validator_triggered=False,  # Phase 2 will make this authoritative
            refusal_detected=response_issues['refusal_detected'],
            ambiguity_detected=response_issues['ambiguity_detected']
        )
        
        # Log specific issue details for monitoring
        if response_issues['refusal_detected']:
            logging.warning(f"POST_RESPONSE_ISSUE: refusal_detected=True, is_primary={response_issues['is_primary_refusal']}, query_type={query_type}")
        if response_issues['ambiguity_detected']:
            logging.warning(f"POST_RESPONSE_ISSUE: ambiguity_detected=True, query_type={query_type}")
        
        # ═══════════════════════════════════════════════════════════════════
        # AUTHORITATIVE POST-RESPONSE VALIDATOR
        # Per spec: validator decisions override earlier routing/retrieval logic
        # ═══════════════════════════════════════════════════════════════════
        validator_result = should_validator_override(query_type, response_issues, retrieval_confidence)
        validator_triggered = validator_result['should_override']
        
        if validator_triggered:
            logging.warning(f"VALIDATOR_OVERRIDE: {validator_result['reason']}")
            
            # Regenerate with correction instruction
            try:
                correction_prompt = validator_result['correction_instruction']
                retry_messages = [
                    {"role": "system", "content": enhanced_prompt + f"\n\n{correction_prompt}"},
                    {"role": "user", "content": message}
                ]
                
                retry_response = await asyncio.wait_for(
                    loop.run_in_executor(
                        _executor,
                        lambda: client.chat.completions.create(
                            model=model_name,
                            messages=retry_messages,
                            temperature=0.1,
                            max_tokens=max_tokens,
                            timeout=90.0
                        )
                    ),
                    timeout=120.0
                )
                
                raw_answer = retry_response.choices[0].message.content or raw_answer
                logging.info(f"VALIDATOR_OVERRIDE_SUCCESS: Regenerated response (length={len(raw_answer)})")
                
                # Update decision path log with validator trigger
                log_decision_path(
                    query=message,
                    query_type=query_type,
                    retrieval_confidence=retrieval_confidence,
                    pages_count=len(pages),
                    doctrine_mode=doctrine_mode,
                    validator_triggered=True,
                    refusal_detected=False,  # Reset since we regenerated
                    ambiguity_detected=False,
                    final_response_path='doctrine' if doctrine_mode else 'hybrid'
                )
                
            except Exception as validator_err:
                logging.error(f"Validator regeneration failed: {validator_err}")
                # Fall through with original response
        
        # DEBUG: Reflection Pass logging
        reflection_status = "Found" if not response_issues['refusal_detected'] or validator_triggered else "Not Found"
        if "Self-Correct" in reasoning_plan.get("reflection_pass", "") or (response_issues['refusal_detected'] and not validator_triggered):
            reflection_status = "Not Found - Self-Correcting"
        logging.info(f"DEBUG: Reflection Pass: {reflection_status} | Context Quality: {reasoning_plan.get('context_quality', 'unknown')}")
        
        # Only trigger web search fallback if the response is PRIMARILY a "NOT FOUND" response
        # Skip this if validator already handled the refusal
        # Don't trigger if the AI provided substantive content but also included a NOT FOUND caveat
        is_not_found_response = (
            raw_answer.upper().strip().startswith("NOT FOUND") or
            len(raw_answer.strip()) < 200 and "NOT FOUND" in raw_answer.upper()
        )
        
        if is_not_found_response:
            # AI couldn't find relevant info in local results - try web search as fallback
            logging.info(f"AI returned NOT FOUND (primary), attempting web search fallback for: {message[:100]}")
            
            try:
                web_search_result = await try_web_search_and_ingest(message, conversation_id)
                
                if web_search_result.get("success") and web_search_result.get("new_pages"):
                    # Successfully ingested new cases, retry with the new pages
                    new_pages = web_search_result["new_pages"]
                    logging.info(f"Web search fallback found {len(new_pages)} new pages, retrying query")
                    
                    # Build context using the standard format for consistency
                    new_context = build_context(new_pages[:15])
                    new_user_prompt = f"OPINION EXCERPTS:\n{new_context}\n\n---\n\nQUESTION: {message}"
                    
                    try:
                        # Make new API call with fresh context
                        retry_response = await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(
                                _executor,
                                lambda: client.chat.completions.create(
                                    model=model_name,
                                    messages=[
                                        {"role": "system", "content": SYSTEM_PROMPT},
                                        {"role": "user", "content": new_user_prompt}
                                    ],
                                    temperature=0.1,
                                    max_tokens=max_tokens,
                                    timeout=90.0
                                )
                            ),
                            timeout=120.0
                        )
                        
                        retry_answer = retry_response.choices[0].message.content or "No response generated."
                        
                        # If still not found after retry, return with web search info (don't retry again)
                        if "NOT FOUND IN PROVIDED OPINIONS" in retry_answer.upper():
                            case_names = web_search_result.get("cases_found", [])
                            web_info = ""
                            if case_names:
                                web_info = f"\n\n**New cases were ingested but no relevant excerpts found.**\n\nIngested: " + ", ".join(case_names[:3])
                            
                            return standardize_response({
                                "answer_markdown": f"NOT FOUND IN PROVIDED OPINIONS.{web_info}\n\nThe topic may require more specialized case law. Try refining your search terms.",
                                "sources": [],
                                "web_search_triggered": True,
                                "debug": {
                                    "claims": [],
                                    "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 1},
                                    "search_query": message,
                                    "web_search_result": web_search_result,
                                    "return_branch": "web_search_fallback_still_not_found"
                                }
                            })
                        
                        # Success! Update raw_answer and pages for downstream processing
                        raw_answer = retry_answer
                        pages = new_pages
                        
                    except Exception as retry_err:
                        logging.error(f"Retry API call failed: {retry_err}")
                        # Fall through to return NOT FOUND with web search info
                        case_names = web_search_result.get("cases_found", [])
                        return standardize_response({
                            "answer_markdown": f"NOT FOUND IN PROVIDED OPINIONS.\n\nNew cases were discovered and ingested, but an error occurred. Please try your query again.",
                            "sources": [],
                            "web_search_triggered": True,
                            "debug": {"return_branch": "web_search_retry_error", "error": str(retry_err)}
                        })
                else:
                    # Web search didn't find anything either
                    web_info = ""
                    case_names = web_search_result.get("cases_found", [])
                    if case_names:
                        web_info = f"\n\n**Potentially relevant cases found but not yet indexed:**\n- " + "\n- ".join(case_names[:5])
                    
                    return standardize_response({
                        "answer_markdown": f"NOT FOUND IN PROVIDED OPINIONS.{web_info}\n\nThe ingested opinions do not contain information relevant to your query. Try ingesting additional opinions or refining your search.",
                        "sources": [],
                        "web_search_triggered": True,
                        "debug": {
                            "claims": [],
                            "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 1},
                            "search_query": message,
                            "web_search_result": web_search_result,
                            "return_branch": "llm_returned_not_found_web_search_no_results"
                        }
                    })
                    
            except Exception as web_err:
                logging.error(f"Web search fallback failed: {web_err}")
                # Return original NOT FOUND response if web search fails
                return standardize_response({
                    "answer_markdown": "NOT FOUND IN PROVIDED OPINIONS.\n\nThe ingested opinions do not contain information relevant to your query. Try ingesting additional opinions or refining your search.",
                    "sources": [],
                    "debug": {
                        "claims": [],
                        "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 1},
                        "search_query": message,
                        "return_branch": "llm_returned_not_found_web_search_error",
                        "web_search_error": str(web_err)
                    }
                })
        
        # Handle AMBIGUOUS QUERY response - pass through the clarification message
        if "AMBIGUOUS QUERY" in raw_answer.upper() or "MULTIPLE MATCHES FOUND" in raw_answer.upper():
            # Extract candidate cases from the response for clickable action items
            action_items = []
            # Match formats like:
            # "1. **Case Name** (Appeal No. XX-XXXX)"
            # "1. **Case Name**, Appeal No. XX-XXXX (date)"  
            # "1. **Case Name**, cited in multiple cases"
            
            # First pattern: numbered case with bold name and optional appeal info
            case_pattern = r'(\d+)\.\s+\*\*([^*]+)\*\*'
            for match in re.finditer(case_pattern, raw_answer):
                num = match.group(1)
                case_name = match.group(2).strip().rstrip(',')
                
                # Try to extract appeal number from text after the case name
                remaining_text = raw_answer[match.end():match.end()+100]
                appeal_match = re.search(r'Appeal\s*No\.?\s*(\d{2}-\d+)', remaining_text, re.IGNORECASE)
                appeal_no = appeal_match.group(1) if appeal_match else ""
                
                # Look up the opinion_id for this case to enable direct selection
                case_lookup = db.search_pages(case_name, None, limit=1, party_only=True)
                opinion_id = case_lookup[0].get('opinion_id') if case_lookup else None
                
                action_items.append({
                    "id": num,
                    "label": case_name,
                    "appeal_no": appeal_no,
                    "action": f"What is the holding in {case_name}?",
                    "opinion_id": str(opinion_id) if opinion_id else None
                })
            
            # STORE disambiguation candidates in DB for next turn resolution
            if conversation_id and action_items:
                db.set_pending_disambiguation(
                    conversation_id,
                    candidates=action_items,
                    original_query=original_message
                )
                logging.info(f"Stored disambiguation: {len(action_items)} candidates for query '{original_message}'")
            
            return standardize_response({
                "answer_markdown": raw_answer,
                "sources": [],
                "action_items": action_items,
                "disambiguation": {
                    "pending": True,
                    "candidates": action_items
                },
                "debug": {
                    "claims": [],
                    "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 0},
                    "search_query": message,
                    "search_terms": search_terms,
                    "pages_count": len(pages),
                    "pages_sample": [{"opinion_id": p.get("opinion_id"), "case_name": p.get("case_name"), "page_number": p.get("page_number")} for p in pages[:5]],
                    "markers_count": 0,
                    "markers": [],
                    "sources_count": 0,
                    "sources": [],
                    "raw_response": raw_answer,
                    "return_branch": "disambiguation"
                }
            })
        
        markers = extract_cite_markers(raw_answer)
        sources, position_to_sid = build_sources_from_markers(markers, pages, search_terms)
        sources = curate_sources_for_mode(sources, attorney_mode)
        
        # FALLBACK: If AI provided substantive answer but no CITATION_MAP markers,
        # generate sources from the context pages that were used
        if not sources and pages and len(raw_answer) > 200 and "NOT FOUND" not in raw_answer.upper()[:100]:
            logging.info(f"No citation markers found in AI response, generating sources from {len(pages)} context pages")
            # Create sources from the top context pages
            seen_cases = set()
            for idx, p in enumerate(pages[:10]):
                case_name = p.get('case_name', 'Unknown')
                # Only include unique cases
                case_key = (p.get('opinion_id'), case_name)
                if case_key in seen_cases:
                    continue
                seen_cases.add(case_key)
                
                # Extract a relevant quote from the page
                page_text = p.get('text', '')[:300].strip()
                logging.info(f"DEBUG Fallback source {idx}: case={case_name}, origin={p.get('origin')}, text_len={len(page_text)}, injected={p.get('injected_as_controlling', False)}")
                if page_text:
                    source_entry = {
                        "sid": str(idx + 1),
                        "opinion_id": p.get('opinion_id'),
                        "case_name": case_name,
                        "appeal_no": p.get('appeal_no', ''),
                        "release_date": p.get('release_date', ''),
                        "page_number": p.get('page_number', 1),
                        "quote": page_text,
                        "verified": True,
                        "pdf_url": f"/pdf/{p.get('opinion_id')}?page={p.get('page_number', 1)}",
                        "courtlistener_url": p.get('courtlistener_url', ''),
                        "court": p.get('origin', 'CAFC'),
                        # Citation verification fields - MUST be at top level per contract
                        "tier": "moderate",
                        "score": 50,
                        "signals": ["fallback_source", "context_page"],
                        "binding_method": "context",
                        "injected_as_controlling": p.get('injected_as_controlling', False)
                    }
                    explain = ranking_scorer.compute_composite_score(0.5, p, page_text)
                    source_entry["explain"] = explain
                    source_entry["application_reason"] = ranking_scorer.generate_application_reason(explain, p)
                    sources.append(normalize_source(source_entry))
                    
            # Sort fallback sources by composite score, then limit to 5
            sources.sort(key=lambda x: x.get("explain", {}).get("composite_score", 0), reverse=True)
            sources = sources[:5]  # Limit to 5 after sorting by score
            logging.info(f"DEBUG Fallback generated {len(sources)} sources")
        
        # Strict grounding enforcement: require sources OR substantive content
        if not sources and not (len(raw_answer) > 300 and pages):
            # Strict grounding enforcement: never return uncited raw model text without context
            return standardize_response({
                "answer_markdown": "NOT FOUND IN PROVIDED OPINIONS.\n\nNo verifiable excerpts were found in the ingested opinions that support an answer to your query. Try refining your question or ingesting additional opinions.",
                "sources": [],
                "debug": {
                    "claims": [],
                    "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 1},
                    "search_query": message,
                    "search_terms": search_terms,
                    "pages_count": len(pages),
                    "pages_sample": [{"opinion_id": p.get("opinion_id"), "case_name": p.get("case_name"), "page_number": p.get("page_number")} for p in pages[:5]],
                    "markers_count": len(markers),
                    "markers": [{"opinion_id": m.get("opinion_id"), "page_number": m.get("page_number"), "quote_preview": (m.get("quote") or "")[:120], "position": m.get("position")} for m in markers[:10]],
                    "sources_count": 0,
                    "sources": [],
                    "raw_response": raw_answer,
                    "return_branch": "rejected_uncited_response"
                }
            })
        
        answer_markdown = build_answer_markdown(raw_answer, markers, position_to_sid)
        
        # P0: Apply per-statement provenance gating in attorney mode.
        if attorney_mode:
            answer_markdown, statement_support = apply_per_statement_provenance_gating(
                answer_markdown, sources
            )
        else:
            _, statement_support = apply_per_statement_provenance_gating(answer_markdown, sources)

        # Make [Q#] and [#] citations clickable with PDF links
        answer_markdown = make_citations_clickable(answer_markdown, quote_registry, sources)
        answer_markdown = append_citation_appendix(answer_markdown, sources)
        
        # Calculate citation metrics for telemetry (P1)
        total_citations = len(sources)
        verified_citations = sum(1 for s in sources 
                                  if s.get('citation_verification', {}).get('tier', s.get('tier', 'unverified')) 
                                  in ('strong', 'moderate'))
        unverified_citations = total_citations - verified_citations
        unverified_rate = (unverified_citations / total_citations * 100) if total_citations > 0 else 0
        
        unsupported_statements = sum(1 for ss in statement_support if not ss.get('supported', True))
        total_statements = len(statement_support)
        
        logging.info(f"CITATION_TELEMETRY: total={total_citations}, verified={verified_citations}, "
                     f"unverified={unverified_citations} ({unverified_rate:.1f}%), "
                     f"unsupported_statements={unsupported_statements}/{total_statements}")
        
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
        
        # Build controlling authorities (separate from cited sources for provenance)
        controlling_authorities = build_controlling_authorities(pages, doctrine_tag)
        
        # Build quote_registry summary for frontend (maps Q# to PDF links)
        quote_links = {
            qid: {
                "pdf_url": f"/pdf/{info['opinion_id']}?page={info['page_number']}",
                "case_name": info["case_name"],
                "page_number": info["page_number"],
                "passage_preview": info["passage"][:100] if info.get("passage") else ""
            }
            for qid, info in quote_registry.items()
        }
        
        _latency_ms = int((_time.time() - _start_time) * 1000)
        
        _verification_results = []
        for idx, s in enumerate(sources):
            _verification_results.append({
                "citation_index": idx,
                "page_id": s.get("page_id"),
                "opinion_id": s.get("opinion_id"),
                "confidence_tier": s.get("citation_verification", {}).get("tier", s.get("tier", "unverified")),
                "match_type": s.get("citation_verification", {}).get("binding_method", "unknown"),
                "binding_tags": s.get("citation_verification", {}).get("signals", []),
                "verified": s.get("verified", False)
            })
        
        if _run_id:
            try:
                voyager.complete_query_run_async(
                    run_id=_run_id,
                    pages=pages,
                    context_pages=pages[:15],
                    total_tokens=_context_tokens,
                    model_name=model_name,
                    temperature=0.1,
                    max_tokens=max_tokens,
                    answer=answer_markdown,
                    verifications=_verification_results,
                    latency_ms=_latency_ms,
                    failure_reason=None,
                    phase1_telemetry=_phase1_telemetry
                )
            except Exception as _ve:
                logging.debug(f"Voyager logging skipped: {_ve}")
        
        return standardize_response({
            "answer_markdown": answer_markdown,
            "sources": sources,
            "quote_links": quote_links,
            "controlling_authorities": controlling_authorities,
            "statement_support": statement_support,
            "debug": {
                "claims": claims,
                "support_audit": {
                    "total_claims": len(sources),
                    "supported_claims": verified_citations,
                    "unsupported_claims": unverified_citations,
                    "unsupported_statements": unsupported_statements
                },
                "citation_metrics": {
                    "total_citations": total_citations,
                    "verified_citations": verified_citations,
                    "unverified_citations": unverified_citations,
                    "unverified_rate_pct": round(unverified_rate, 1),
                    "total_statements": total_statements,
                    "unsupported_statements": unsupported_statements
                },
                "search_query": message,
                "search_terms": search_terms,
                "pages_count": len(pages),
                "pages_sample": [{"opinion_id": p.get("opinion_id"), "case_name": p.get("case_name"), "page_number": p.get("page_number")} for p in pages[:5]],
                "markers_count": len(markers),
                "markers": [{"opinion_id": m.get("opinion_id"), "page_number": m.get("page_number"), "quote_preview": (m.get("quote") or "")[:120], "position": m.get("position")} for m in markers[:10]],
                "sources_count": len(sources),
                "sources": [{"sid": s.get("sid"), "opinion_id": s.get("opinion_id"), "page_number": s.get("page_number"), "quote": s.get("quote", "")[:120]} for s in sources[:10]],
                "raw_response": raw_answer,
                "return_branch": "ok",
                "doctrine_tag": doctrine_tag,
                "controlling_authorities_count": len(controlling_authorities),
                "run_id": _run_id,
                "phase1_telemetry": _phase1_telemetry
            }
        })
        
    except asyncio.TimeoutError:
        fallback = generate_fallback_response(pages, search_terms, message)
        fallback["debug"]["error"] = "timeout"
        fallback["debug"]["return_branch"] = "timeout_fallback"
        return standardize_response(fallback)
    except Exception as e:
        logging.error(f"Chat error: {str(e)}, query: {message}")
        return standardize_response({
            "answer_markdown": f"Error generating response: {str(e)}\n\nPlease try again.",
            "sources": [],
            "debug": {
                "claims": [],
                "support_audit": {"total_claims": 0, "supported_claims": 0, "unsupported_claims": 1},
                "search_query": message,
                "search_terms": search_terms,
                "pages_count": len(pages) if pages else 0,
                "pages_sample": [{"opinion_id": p.get("opinion_id"), "case_name": p.get("case_name"), "page_number": p.get("page_number")} for p in (pages or [])[:5]],
                "markers_count": 0,
                "markers": [],
                "sources_count": 0,
                "sources": [],
                "raw_response": None,
                "error": str(e),
                "return_branch": "exception"
            }
        })


async def generate_chat_response_stream(
    message: str,
    opinion_ids: Optional[List[str]] = None,
    conversation_id: Optional[str] = None,
    party_only: bool = False,
    attorney_mode: bool = False
):
    """
    Streaming version of generate_chat_response that yields SSE events.
    Yields: 'data: {"type": "token", "content": "..."}\n\n' for each token
            'data: {"type": "sources", "sources": [...]}\n\n' at the end
            'data: {"type": "done"}\n\n' when complete
    """
    import json
    
    # First, do the search and context building (non-streaming part)
    search_terms = message.split()
    
    if opinion_ids:
        pages = []
        for oid in opinion_ids:
            opinion_pages = db.get_pages_for_opinion(oid)
            pages.extend(opinion_pages)
    else:
        pages = db.search_pages(message, None, limit=20, party_only=party_only)
        
        # Fallback retrieval if needed
        if len(pages) < 5 and len(message.split()) > 10:
            short_query = " ".join(message.split()[:8])
            more_pages = db.search_pages(short_query, None, limit=10, party_only=party_only)
            seen_ids = {(p.get('opinion_id'), p.get('page_number')) for p in pages}
            for p in more_pages:
                key = (p.get('opinion_id'), p.get('page_number'))
                if key not in seen_ids:
                    pages.append(p)
                    seen_ids.add(key)
    
    if not pages:
        # Try web search to find and ingest relevant cases
        yield 'data: {"type": "status", "message": "Searching for relevant cases..."}\n\n'
        
        try:
            web_search_result = await try_web_search_and_ingest(message, conversation_id)
            
            if web_search_result.get("success") and web_search_result.get("new_pages"):
                # Emit learning status for each case
                for case in web_search_result.get("ingested_cases", []):
                    if case.get("status") == "completed":
                        case_name = case.get("case_name", "Unknown")
                        escaped_name = case_name.replace('"', '\\"').replace('\n', ' ')
                        yield f'data: {{"type": "learning", "case_name": "{escaped_name}"}}\n\n'
                
                pages = web_search_result["new_pages"]
                yield 'data: {"type": "status", "message": "Found relevant cases. Analyzing..."}\n\n'
            else:
                # Web search didn't find anything useful
                cases_found = web_search_result.get("cases_found", [])
                web_info = ""
                if cases_found:
                    web_info = " Some cases were found but could not be indexed."
                yield f'data: {{"type": "token", "content": "NOT FOUND IN PROVIDED OPINIONS.\\n\\nNo matching opinions found in the database.{web_info}"}}\n\n'
                yield 'data: {"type": "sources", "sources": []}\n\n'
                yield 'data: {"type": "done"}\n\n'
                return
        except Exception as e:
            logging.error(f"Web search failed in streaming: {e}")
            yield 'data: {"type": "token", "content": "NOT FOUND IN PROVIDED OPINIONS.\\n\\nNo matching opinions found in the database."}\n\n'
            yield 'data: {"type": "sources", "sources": []}\n\n'
            yield 'data: {"type": "done"}\n\n'
            return
    
    client = get_openai_client()
    if not client:
        yield 'data: {"type": "token", "content": "AI service unavailable. Please try again later."}\n\n'
        yield 'data: {"type": "done"}\n\n'
        return
    
    # Build context with parallel operations
    loop = asyncio.get_event_loop()
    context = await loop.run_in_executor(_executor, lambda: build_context(pages))
    conv_summary = await loop.run_in_executor(_executor, lambda: build_conversation_summary(conversation_id))
    
    # Check for cached legal definitions
    cached_def = None
    query_lower = message.lower()
    if 'alice' in query_lower or 'mayo' in query_lower or '101' in query_lower:
        cached_def = get_cached_legal_definition('alice_mayo')
    elif 'obviousness' in query_lower or 'obvious' in query_lower or '103' in query_lower:
        cached_def = get_cached_legal_definition('obviousness')
    
    # Build enhanced prompt
    enhanced_prompt = SYSTEM_PROMPT
    if conv_summary:
        enhanced_prompt = conv_summary + "\n" + enhanced_prompt
    if cached_def:
        enhanced_prompt += f"\n\nREFERENCE FRAMEWORK:\n{cached_def}"
    enhanced_prompt += "\n\nAVAILABLE OPINION EXCERPTS:\n" + context
    
    # Signal that we're starting to generate
    yield 'data: {"type": "start"}\n\n'
    
    try:
        # Use streaming API
        stream = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": enhanced_prompt},
                {"role": "user", "content": message}
            ],
            temperature=0.2,
            max_tokens=2500,
            stream=True
        )
        
        full_response = ""
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                full_response += token
                # Escape for JSON
                escaped_token = json.dumps(token)[1:-1]  # Remove quotes from json.dumps
                yield f'data: {{"type": "token", "content": "{escaped_token}"}}\n\n'
        
        # Process the complete response to extract sources
        markers = extract_cite_markers(full_response)
        sources, position_to_sid = build_sources_from_markers(markers, pages, search_terms)
        sources = curate_sources_for_mode(sources, attorney_mode)
        
        # Send sources at the end
        sources_json = json.dumps(sources)
        yield f'data: {{"type": "sources", "sources": {sources_json}}}\n\n'
        
        # Signal completion
        yield 'data: {"type": "done"}\n\n'
        
    except Exception as e:
        logging.error(f"Streaming error: {e}")
        error_msg = json.dumps(str(e))[1:-1]
        yield f'data: {{"type": "error", "message": "{error_msg}"}}\n\n'
        yield 'data: {"type": "done"}\n\n'
