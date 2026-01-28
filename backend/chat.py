import os
import re
import json
import asyncio
import logging
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import List, Dict, Any, Optional, Tuple
from openai import OpenAI
import tiktoken

from backend import db_postgres as db
from backend import web_search

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


def standardize_response(response: Dict[str, Any], web_search_result: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Standardize chat response by promoting debug fields to top-level.
    Ensures consistent schema: return_branch, markers_count, sources_count at top level.
    Also promotes web_search info if provided.
    """
    debug = response.get("debug", {})
    
    # Promote key observability fields to top-level
    response["return_branch"] = debug.get("return_branch", "unknown")
    response["markers_count"] = debug.get("markers_count", 0)
    response["sources_count"] = debug.get("sources_count", 0)
    
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

def get_openai_client() -> Optional[OpenAI]:
    if AI_BASE_URL and AI_API_KEY:
        return OpenAI(base_url=AI_BASE_URL, api_key=AI_API_KEY)
    return None


def expand_query_with_legal_terms(query: str, client: Optional[OpenAI] = None) -> List[str]:
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

SYSTEM_PROMPT = """You are a specialized legal research assistant for U.S. Federal Circuit patent litigators.

Your only authoritative knowledge source is the opinion excerpts provided in the current conversation (via retrieval or direct input). You must operate with litigation-grade rigor, clerk-level precision, and strict textual grounding.

0. AGENTIC REASONING & REFLECTION LOOP (MANDATORY - EXECUTE BEFORE EVERY RESPONSE)

Before generating any answer, you MUST complete an internal reasoning process. This process is SILENT to the user but MANDATORY for quality control.

A. REASONING SCRATCHPAD (Internal - Do Not Output)

Step 1: CLASSIFY THE QUERY
- Identify the core legal standard: § 101 (eligibility), § 102 (anticipation), § 103 (obviousness), § 112 (definiteness/enablement), claim construction, willful infringement, injunctions, damages, etc.
- Identify the query type: doctrinal question, case-specific holding, procedural issue, multi-case synthesis

Step 2: BRAINSTORM SEARCH STRATEGY
- List 3-5 key legal terms and synonyms for the doctrine
- Identify potential landmark cases: KSR (obviousness), Alice (§101), Phillips (claim construction), Markman (claim construction), Nautilus (§112), etc.
- For 2024/2025 queries, consider recent developments:
  * § 103 Obviousness: "desirable vs. best" distinction (Honeywell v. 3G Licensing 2025), "design choice" and predictable results (USAA v. PNC Bank 2025)
  * § 101: Continuing Alice/Mayo framework refinements
  * Claim Construction: Intrinsic vs. extrinsic evidence hierarchy

Step 3: DEFINE SEARCH PLAN
- Primary terms: [list core legal terms]
- Secondary terms: [list synonyms and related concepts]
- Target cases: [list relevant landmark and recent cases]

B. CHAIN-OF-VERIFICATION (CoVe) - REFLECTION PASS

After retrieving context, SILENTLY verify:

1. RELEVANCE CHECK:
   - Do the retrieved excerpts actually discuss the legal standard in question?
   - Are they substantive holdings or merely page headers/headnotes?

2. RECENCY CHECK:
   - For evolving standards (obviousness, § 101), are the excerpts from recent cases (2020+)?
   - Is there a 2024/2025 case that updates or refines the doctrine?

3. SUBSTANTIVE DISCUSSION CHECK:
   - Does the excerpt contain the court's actual reasoning, not just a passing mention?
   - Prioritize: Majority holdings > Concurrences > Dicta > Headnotes

4. SELF-CORRECTION TRIGGER:
   - If the retrieved context lacks substantive discussion of the query's core doctrine:
     * Internally note: "Context lacks [specific element]. Expanding search."
     * Suggest alternative search terms in your response
   - If multiple cases discuss the same doctrine, synthesize the EVOLUTION of the standard

C. RE-RANKING LOGIC

When multiple excerpts are retrieved, prioritize in this order:
1. Supreme Court precedent (if directly applicable)
2. En banc Federal Circuit decisions
3. Recent panel decisions (2023-2025) that apply or refine the doctrine
4. Older foundational cases that established the rule

Within each tier, prioritize:
- Pages with explicit "We hold..." or "The rule is..." language
- Pages discussing the "why" behind a holding (reasoning)
- Pages with multi-factor tests or standards
- DEPRIORITIZE: Cover pages, headnotes, procedural background, party listings

D. DYNAMIC SYNTHESIS REQUIREMENT

Your response must go beyond quoting. You must:
1. Extract the RULE (What the court held)
2. Explain the REASONING (Why the court so held - the logic)
3. Identify the APPLICATION (How a practitioner applies this)
4. Note any EVOLUTION (How this refines or updates prior doctrine)

If the query asks about a doctrine and you find multiple cases, trace the doctrinal development:
"[Foundation case] established [rule]. [Subsequent case] clarified that [refinement]. Most recently, [2024/2025 case] held that [current standard]."

I. CORE FUNCTION

Your function is to extract, explain, and apply holdings and rules of law from Federal Circuit precedential decisions, for use in:
- briefs and motions,
- oral argument preparation,
- issue framing and litigation strategy.

You do not summarize cases.
You extract holdings, standards, and operative rules, and explain how a practitioner should use them.

II. STRICT GROUNDING RULES (NON-NEGOTIABLE)

1. You may ONLY use information contained in the provided opinion excerpts.
2. Every factual, legal, or doctrinal statement MUST be supported by at least one VERBATIM QUOTE from the excerpts.
3. If support cannot be found, respond ONLY with: NOT FOUND IN PROVIDED OPINIONS.
4. You may NOT rely on external legal knowledge, background doctrine, or assumptions.
5. You may NOT infer holdings or reconcile gaps not explicitly supported by quoted text.

III. PRE-ANALYSIS CHECKLIST (MANDATORY, SILENT)

Before drafting any answer, you MUST internally verify:
1. Query Type: Party-based (e.g., "Google"), Case-name-based, Issue-based (e.g., § 101, claim construction), Procedural / standard of review
2. Candidate Case Count: Identify how many distinct Federal Circuit opinions in the provided excerpts plausibly match the query.
3. Ambiguity Test: If more than one case plausibly matches, STOP and request clarification.
4. Holding Availability: Confirm the excerpt contains explicit holding or rule language.
5. Support Test: Every proposition must have a verbatim quote.

If any step fails, follow the failure rules in Section X.

IV. QUERY INTERPRETATION & ENTITY RESOLUTION

A. Party vs. Case Recognition
- If the query references a party rather than a case name:
  - Treat it as a litigant identifier, not a holding.
  - Recognize corporate aliases or successors only if they appear in the provided excerpts or metadata (e.g., "Google Inc.", "Google LLC", "Alphabet Inc.").

B. Multi-Case Disambiguation (CRITICAL)

If more than one provided opinion plausibly matches the query:
1. Do NOT extract or state any holding.
2. Respond ONLY with the following structure:

AMBIGUOUS QUERY — MULTIPLE MATCHES FOUND
The provided excerpts include multiple Federal Circuit decisions that plausibly match your query. Please specify which case or issue you want addressed.

3. Identify each candidate case with a citation.

Do not proceed until the user clarifies.

C. True Absence

If no provided opinion matches the query, respond ONLY: NOT FOUND IN PROVIDED OPINIONS.

V. ANSWER STRUCTURE (MANDATORY ONCE UNAMBIGUOUS)

When (and only when) the query is unambiguous, structure the response exactly as follows:

1. Immediate Answer
- 1–2 sentences stating the key holding or rule of law.
- No background.
- No hedging.
- Present tense.

2. ## Detailed Analysis
- Use clear subheadings.
- Extract and explain: the holding, the governing rule, the standard of review (if stated), doctrinal limits or conditions.
- Quote operative language, not dicta.

3. Practitioner Guidance
- State what a Federal Circuit practitioner should do: how to argue the rule, when it applies, what pitfalls the case identifies.

VI. CITATIONS & TRACEABILITY

A. Inline Citations
- Use bracketed references: [1], [2], etc.
- First reference: Full case name + holding parenthetical
- Subsequent references: Short-form case name

B. Citation Map (REQUIRED - EXACT FORMAT)

At the END of every substantive response, you MUST include a citation map in this EXACT format:

CITATION_MAP:
[1] <case_name> (<opinion_id>) | Page <page_number> | "Exact verbatim quote from the opinion..."
[2] <case_name> (<opinion_id>) | Page <page_number> | "Another exact verbatim quote..."

CRITICAL RULES FOR CITATION_MAP:
- <case_name> must be the case name from the excerpt header (e.g., "Amgen Inc. v. Sanofi" or "In re Wands")
- <opinion_id> must be the EXACT document ID from the excerpt header in parentheses (e.g., "(81e1529a-8a80-4811-a923-ca9f04f470d6)")
- <page_number> must be the numeric page number from the excerpt (e.g., "Page 11")
- The quoted text MUST be an EXACT substring copied verbatim from the excerpt - no paraphrasing, no word changes
- Every [N] citation used inline in your answer MUST have a corresponding entry in the CITATION_MAP
- Place the CITATION_MAP at the very end of your response, after all analysis

VII. TONE & VOICE

- Professional, authoritative, practitioner-to-practitioner.
- Declarative; no speculation.
- No phrases such as "it appears," "it seems," or "may suggest."
- Assume the reader is an experienced patent litigator.

VIII. LENGTH RULES

- Simple procedural issue: 150–300 words
- Substantive / doctrinal issue: 400–800 words
- Always extract and explain holdings; never merely point to sources.

IX. MULTI-DOCUMENT RAG RULES

When multiple excerpts are provided:
1. Treat each distinct case separately.
2. Do not merge holdings unless the user explicitly asks for synthesis.
3. If synthesis is requested:
   - Present case-by-case holdings first.
   - Then provide a synthesis limited strictly to quoted support.

X. FAILURE MODES (MANDATORY RESPONSES)

- No supporting excerpt: NOT FOUND IN PROVIDED OPINIONS.
- Multiple plausible cases: AMBIGUOUS QUERY — MULTIPLE MATCHES FOUND
- Insufficient text to support a claim: NOT FOUND IN PROVIDED OPINIONS.
- Retrieval provides zero excerpts: NOT FOUND IN PROVIDED OPINIONS.

IMPORTANT EXCEPTION - Named Case Present But Topic Mismatch:
If the user asks about a SPECIFIC CASE by name (e.g., "Does X v. Y discuss § 101?") AND excerpts from that case ARE provided, but the case does NOT discuss the requested topic:
- Do NOT respond with "NOT FOUND IN PROVIDED OPINIONS"
- Instead, respond with: "The case [Case Name] does not discuss [requested topic]. Based on the provided excerpts, this case addresses [actual topic covered]."
- YOU MUST include at least one citation marker [1] referencing an excerpt that shows what the case DOES discuss
- Example: "The case H-W Technology v. Overstock does not discuss § 101 eligibility. Instead, this case addresses claim indefiniteness under § 112. [1]"
- The citation map at the end MUST include at least one verifiable quote from the excerpts about the actual topic
- This ensures the user understands their requested case was found, and the alternative topic is grounded in actual excerpts

XI. OPERATING PRINCIPLE

If a statement could not survive scrutiny by a Federal Circuit judge or opposing counsel for lack of textual support, do not write it.

Your credibility depends entirely on verbatim grounding and disciplined restraint.

XII. PRECEDENT HIERARCHY & FOUNDATION CASES

When answering technical legal questions (e.g., § 101 abstract idea, § 103 obviousness, § 112 definiteness, claim construction), and IF the relevant landmark case appears in the provided excerpts:

1. FIRST establish the foundational legal rule from that landmark precedent:
   - § 101 questions: Alice Corp. v. CLS Bank (two-step framework)
   - § 103 questions: KSR v. Teleflex (flexible obviousness, TSM not required)
   - § 112 definiteness: Nautilus v. Biosig (reasonable certainty standard)
   - Claim construction: Phillips v. AWH Corp. (intrinsic evidence hierarchy)
   - Written description: Ariad v. Eli Lilly (possession requirement)

2. THEN apply or distinguish using the specific case law from the provided excerpts.

3. Structure as: [Foundation Rule] → [Application to Facts] → [Practitioner Guidance]

IMPORTANT: This hierarchy ONLY applies when the landmark case is present in the retrieved excerpts. If the landmark case is not provided, proceed with whatever excerpts ARE available—do NOT reference external knowledge about landmark cases. The grounding rule in Section II remains absolute.

XIII. SUGGESTED NEXT STEPS (REQUIRED)

At the END of every substantive response (after the CITATION_MAP), you MUST provide exactly three brief, strategically relevant follow-up questions. Format them as:

## Suggested Next Steps
1. [First follow-up question focusing on logical legal progression]
2. [Second follow-up question exploring related doctrine or issue]
3. [Third follow-up question about adversarial strategy or procedural posture]

These questions should help the practitioner with LITIGATION STRATEGY:
- If discussing Step 1 of Alice, suggest exploring Step 2 or preemption arguments
- If discussing a holding, suggest examining distinguishing facts for adversarial framing
- If discussing claim construction, suggest exploring infringement or invalidity implications
- If the case involves a motion to dismiss, suggest 12(b)(6) response strategies
- If the case involves IPR, suggest Federal Circuit appeal considerations
- Suggest potential Mandamus arguments where interlocutory review is available

ADVERSARIAL FRAMING EXAMPLES:
- "How might opposing counsel distinguish [cited case] on the facts?"
- "What evidence would strengthen a § 103 obviousness challenge to these claims?"
- "Could this holding support a Rule 36 affirmance, and what are the implications?"
- "What claim construction arguments might survive a Markman hearing?"

Keep each question to one sentence. Make them actionable and specific to the case/issue discussed.

XIII. SPECIALIZED LEGAL DOMAIN AWARENESS

When the query involves specialized patent doctrines, apply additional domain knowledge:

A. Certificate of Correction (35 U.S.C. §§ 254-255)
For queries involving certificates of correction:
- § 254: Corrects PTO mistakes (e.g., typographical errors in specification)
- § 255: Corrects applicant mistakes "of a clerical or typographical nature, or of minor character"
- Key issue: Whether correction constitutes "new matter" or broadening
- Look for: H-W Technologies v. Overstock.com, Superior Indus. v. Masaba, and related precedent
- Federal Circuit applies heightened scrutiny to corrections that affect claim scope

B. Source Verification Requirement (STRICT)
Every sentence in your response that makes a factual or legal assertion MUST be traceable to a specific indexed source via a citation marker [S#]. If you cannot find direct support in the provided excerpts, you MUST state: "NOT FOUND IN PROVIDED OPINIONS."

Do NOT cite any fact, holding, or legal standard that cannot be directly mapped to a verbatim quote from the provided indexed chunks.
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


# Token counting for context safety
_tiktoken_encoder = None

def get_tiktoken_encoder():
    """Lazily initialize tiktoken encoder for GPT-4o."""
    global _tiktoken_encoder
    if _tiktoken_encoder is None:
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
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = text.replace('\u00ad', '')
    text = text.replace('\u2010', '').replace('\u2011', '').replace('\u2012', '')
    text = text.replace('\u2013', '').replace('\u2014', '').replace('\u2015', '')
    text = re.sub(r'-\s+', '', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.strip().lower()
    return text

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
    if len(quote.strip()) < 20:
        return False
    norm_quote = normalize_for_verification(quote)
    norm_page = normalize_for_verification(page_text)
    return norm_quote in norm_page

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
    pages: List[Dict]
) -> Tuple[Optional[Dict], str, List[str]]:
    """Verify quote exists in the CLAIMED opinion (strict binding).
    
    Returns: (matching_page, binding_method, signals)
    - binding_method: "strict" if opinion_id matched, "failed" otherwise
    - signals: list of signal strings for confidence calculation
    """
    signals = []
    
    for page in pages:
        if page.get('page_number', 0) < 1:
            continue
        if page.get('opinion_id') == claimed_opinion_id:
            if verify_quote_strict(quote, page.get('text', '')):
                signals.append("case_bound")
                signals.append("exact_match")
                return page, "strict", signals
    
    return None, "failed", ["binding_failed"]

def verify_quote_with_fuzzy_fallback(
    quote: str,
    claimed_case_name: str,
    pages: List[Dict]
) -> Tuple[Optional[Dict], str, List[str]]:
    """Fuzzy case-name binding when opinion_id is missing.
    
    Returns: (matching_page, binding_method, signals)
    - binding_method: "fuzzy" if case name matched, "failed" otherwise
    - signals: includes "fuzzy_case_binding" if fuzzy match used
    """
    signals = []
    norm_claimed = normalize_case_name_for_binding(claimed_case_name)
    
    if not norm_claimed:
        return None, "failed", ["no_case_name"]
    
    for page in pages:
        if page.get('page_number', 0) < 1:
            continue
        
        norm_page_case = normalize_case_name_for_binding(page.get('case_name', ''))
        
        if norm_claimed == norm_page_case or norm_claimed in norm_page_case or norm_page_case in norm_claimed:
            if verify_quote_strict(quote, page.get('text', '')):
                signals.append("fuzzy_case_binding")
                signals.append("exact_match")
                return page, "fuzzy", signals
    
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

        # NO STRATEGY 3 - We do NOT silently substitute from another case
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
                "tier": "unverified",
                "score": 0,
                "signals": signals,
                "binding_method": binding_method
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
            "court": page.get("origin", "CAFC"),
            "tier": tier,
            "score": score,
            "signals": signals,
            "binding_method": binding_method
        })

    return sources, position_to_sid


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
    - Case binding: strict=40, fuzzy=25
    - Quote match: exact=30, partial=15
    - Recency bonus: 2020+=10 (signal, not gate - older holdings can still be STRONG)
    - Section type: holding=+15, dicta/concurrence/dissent=-5 to -15
    """
    score = 0
    
    # Binding score
    if binding_method == "strict":
        score += 40
    elif binding_method == "fuzzy":
        score += 25  # Cap at MODERATE for fuzzy binding
    
    # Quote match score
    if "exact_match" in signals:
        score += 30
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

def generate_fallback_response(pages: List[Dict], search_terms: List[str], search_query: str = "") -> Dict[str, Any]:
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
                "pdf_url": page.get('pdf_url', ''),
                "courtlistener_url": page.get('courtlistener_url', '')
            })
    
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

def detect_option_reference(message: str) -> Optional[int]:
    """Detect if message is a reference to a previous numbered option.
    
    Returns the option number (1-indexed) if detected, None otherwise.
    """
    msg_lower = message.lower().strip()
    
    # Direct number references: "1", "2", etc.
    if msg_lower.isdigit() and 1 <= int(msg_lower) <= 10:
        return int(msg_lower)
    
    # Ordinal references using word boundary regex to avoid false positives like "firstly", "seconding"
    ordinal_patterns = [
        (r'\bsecond\b', 2), (r'\b2nd\b', 2),
        (r'\bthird\b', 3), (r'\b3rd\b', 3),
        (r'\bfourth\b', 4), (r'\b4th\b', 4),
        (r'\bfifth\b', 5), (r'\b5th\b', 5),
        (r'\bfirst\b', 1), (r'\b1st\b', 1),
        # Cardinal numbers with word boundaries
        (r'\bone\b', 1),
        (r'\btwo\b', 2),
        (r'\bthree\b', 3),
        (r'\bfour\b', 4),
        (r'\bfive\b', 5),
    ]
    
    # Check for ordinal/cardinal words with word boundaries
    for pattern, num in ordinal_patterns:
        if re.search(pattern, msg_lower):
            return num
    
    # Check for "option X", "number X", "case X" patterns
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

async def generate_chat_response(
    message: str,
    opinion_ids: Optional[List[str]] = None,
    conversation_id: Optional[str] = None,
    party_only: bool = False
) -> Dict[str, Any]:
    
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
            option_num = detect_option_reference(message)
            logging.info(f"[DISAMBIGUATION] detect_option_reference returned: {option_num}")
            candidates = pending_state.get('candidates', [])
            original_query = pending_state.get('original_query', '')
            
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
            return standardize_response({
                "answer_markdown": "NOT FOUND IN PROVIDED OPINIONS.\n\nNo relevant excerpts were found. Try different search terms or ingest additional opinions.",
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
                    "return_branch": "not_found_no_pages"
                }
            })
    
    client = get_openai_client()
    
    if not client:
        return generate_fallback_response(pages, search_terms, message)
    
    # Build context and conversation summary in parallel for speed
    loop = asyncio.get_event_loop()
    
    async def build_context_async():
        return await loop.run_in_executor(_executor, lambda: build_context(pages))
    
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
    context, conv_summary, cached_definition = await asyncio.gather(
        build_context_async(),
        build_summary_async(),
        get_cached_definitions_async()
    )
    
    # Build enhanced system prompt with conversation context and cached definitions
    enhanced_prompt = SYSTEM_PROMPT
    
    if conv_summary:
        enhanced_prompt = conv_summary + "\n" + enhanced_prompt
    
    if cached_definition:
        enhanced_prompt += f"\n\nREFERENCE FRAMEWORK:\n{cached_definition}"
    
    enhanced_prompt += "\n\nAVAILABLE OPINION EXCERPTS:\n" + context
    
    # DEBUG: Agentic Reasoning Plan logging
    query_lower = message.lower()
    reasoning_plan = _build_agentic_reasoning_plan(query_lower, pages)
    logging.info(f"DEBUG: Agentic Reasoning Plan: {reasoning_plan}")
    
    try:
        response = await asyncio.wait_for(
            loop.run_in_executor(
                _executor,
                lambda: client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": enhanced_prompt},
                        {"role": "user", "content": message}
                    ],
                    temperature=0.2,
                    max_tokens=2500,
                    timeout=60.0
                )
            ),
            timeout=90.0
        )
        
        raw_answer = response.choices[0].message.content or "No response generated."
        
        # DEBUG: Log the raw AI response for troubleshooting
        logging.info(f"DEBUG: AI Raw Response (first 500 chars): {raw_answer[:500]}")
        
        # DEBUG: Reflection Pass logging
        reflection_status = "Found" if "NOT FOUND" not in raw_answer.upper() else "Not Found"
        if "Self-Correct" in reasoning_plan.get("reflection_pass", "") or reflection_status == "Not Found":
            reflection_status = "Not Found - Self-Correcting"
        logging.info(f"DEBUG: Reflection Pass: {reflection_status} | Context Quality: {reasoning_plan.get('context_quality', 'unknown')}")
        
        # Only trigger web search fallback if the response is PRIMARILY a "NOT FOUND" response
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
                                    model="gpt-4o",
                                    messages=[
                                        {"role": "system", "content": SYSTEM_PROMPT},
                                        {"role": "user", "content": new_user_prompt}
                                    ],
                                    temperature=0.2,
                                    max_tokens=2500,
                                    timeout=60.0
                                )
                            ),
                            timeout=90.0
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
                logging.info(f"DEBUG Fallback source {idx}: case={case_name}, text_len={len(page_text)}, has_text={bool(page_text)}")
                if page_text:
                    sources.append({
                        "opinion_id": p.get('opinion_id'),
                        "case_name": case_name,
                        "appeal_no": p.get('appeal_no', ''),
                        "release_date": p.get('release_date', ''),
                        "page_number": p.get('page_number', 1),
                        "quote": page_text,
                        "verified": True,
                        "pdf_url": p.get('pdf_url', ''),
                        "courtlistener_url": p.get('courtlistener_url', '')
                    })
                if len(sources) >= 5:  # Limit to 5 sources
                    break
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
        
        return standardize_response({
            "answer_markdown": answer_markdown,
            "sources": sources,
            "debug": {
                "claims": claims,
                "support_audit": {
                    "total_claims": len(sources),
                    "supported_claims": len(sources),
                    "unsupported_claims": 0
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
                "return_branch": "ok"
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
    party_only: bool = False
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
