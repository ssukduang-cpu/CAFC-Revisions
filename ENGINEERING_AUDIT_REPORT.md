# CAFC Opinion Assistant - Engineering Audit Report

**Audit Date:** January 31, 2026  
**Auditor:** Engineering Audit System  
**Purpose:** Voyager AI Integration Readiness Assessment

---

## Executive Summary

The CAFC Opinion Assistant is a litigation-grade legal research system built on a **PostgreSQL-backed RAG architecture** with robust citation verification. The system ingests **4,720 court opinions (78,419 pages)** from authoritative legal sources and provides citation-verified answers using GPT-4o.

### Key Findings

| Category | Assessment | Score |
|----------|------------|-------|
| **Provenance** | Strong - All citations traced to PDF page sources | 85/100 |
| **Coverage** | Good - CAFC + 15 SCOTUS landmark cases | 75/100 |
| **Recency Controls** | Moderate - Weekly sync + web search fallback | 70/100 |
| **Determinism** | Strong - Fixed temperature (0.1), versioned corpus | 80/100 |
| **Citation Support** | Excellent - PDF links, page numbers, verification | 90/100 |
| **Data Hygiene** | Good - Deduplication, classification, normalization | 75/100 |

### **Voyager Readiness Score: 79/100** ✅

The system is **Voyager-ready with minor enhancements** needed for production deployment.

---

## Data Source Inventory

### 1. Primary Data Store: PostgreSQL Database

| Attribute | Details |
|-----------|---------|
| **Type** | PostgreSQL (Neon-backed via Replit) |
| **Tables** | `documents`, `document_pages`, `opinions`, `chunks`, `conversations`, `messages`, `sync_history`, `citation_telemetry` |
| **Record Count** | 4,720 documents, 78,419 pages, 757 conversations |
| **Access** | Drizzle ORM + raw SQL via `db_postgres.py` |
| **Configuration** | `DATABASE_URL` env var (line: `backend/db_postgres.py:15`) |
| **Caching** | In-memory LRU cache for legal definitions (`backend/chat.py:8`) |
| **TTL** | No TTL - persistent storage |

**Evidence:**
```python
# backend/db_postgres.py:15
DATABASE_URL = os.environ.get("DATABASE_URL")
```

### 2. OpenAI API (via Replit AI Integrations)

| Attribute | Details |
|-----------|---------|
| **Type** | LLM API |
| **Model** | GPT-4o (configurable via `CHAT_MODEL` env) |
| **Access** | OpenAI SDK with Replit proxy |
| **Authentication** | `AI_INTEGRATIONS_OPENAI_API_KEY`, `AI_INTEGRATIONS_OPENAI_BASE_URL` |
| **Configuration** | `backend/chat.py:437-442` |
| **Timeout** | 90s model timeout, 120s async wrapper |
| **Temperature** | 0.1 (deterministic) |
| **Failure Mode** | Returns "NOT FOUND" on timeout, triggers web search fallback |

**Evidence:**
```python
# backend/chat.py:437-442
AI_BASE_URL = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")
AI_API_KEY = os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")

if AI_BASE_URL and AI_API_KEY:
    return OpenAI(base_url=AI_BASE_URL, api_key=AI_API_KEY)
```

### 3. CourtListener API

| Attribute | Details |
|-----------|---------|
| **Type** | Legal Data API |
| **Base URL** | `https://www.courtlistener.com/api/rest/v4` |
| **Authentication** | `COURTLISTENER_API_TOKEN` (Bearer token) |
| **Usage** | PDF downloads, case lookup, cluster_id deduplication |
| **Configuration** | `backend/web_search.py:17-20`, `backend/scheduled_sync.py:17-18` |
| **Rate Limits** | Respects API limits; retry with exponential backoff |
| **Failure Mode** | Logs warning, falls back to CAFC website |

**Evidence:**
```python
# backend/web_search.py:17-21
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
COURTLISTENER_API_TOKEN = os.environ.get("COURTLISTENER_API_TOKEN")
COURTLISTENER_API_BASE = "https://www.courtlistener.com/api/rest/v4"
TAVILY_API_URL = "https://api.tavily.com/search"
```

### 4. Tavily Search API

| Attribute | Details |
|-----------|---------|
| **Type** | Web Search API |
| **Base URL** | `https://api.tavily.com/search` |
| **Authentication** | `TAVILY_API_KEY` |
| **Usage** | Fallback when local search returns "NOT FOUND" |
| **Configuration** | `backend/web_search.py:126-165` |
| **Domains Searched** | courtlistener.com, scholar.google.com, law.cornell.edu, cafc.uscourts.gov, casetext.com |
| **Failure Mode** | Returns empty results, user sees "NOT FOUND" |

**Evidence:**
```python
# backend/web_search.py:140-151
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
    ...
```

### 5. PDF Storage (Local Filesystem)

| Attribute | Details |
|-----------|---------|
| **Type** | Local file storage |
| **Path** | `data/pdfs/` |
| **Configuration** | `backend/ingestion.py:12` |
| **Format** | Original court PDFs |
| **Retention** | Permanent |

**Evidence:**
```python
# backend/ingestion.py:12
PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "pdfs")
```

### 6. Harvard Iowa Dataset (Initial Manifest)

| Attribute | Details |
|-----------|---------|
| **Type** | Static dataset |
| **Version** | v7.1 |
| **Usage** | Initial backfill of CAFC precedential opinions |
| **Update Cadence** | One-time import, supplemented by CourtListener sync |

### 7. CAFC Website (Deprecated Scraper)

| Attribute | Details |
|-----------|---------|
| **Type** | Web scraping (DEPRECATED) |
| **URL** | `https://www.cafc.uscourts.gov/home/case-information/opinions-orders/` |
| **Status** | Replaced by CourtListener API |
| **Configuration** | `backend/scraper.py` (marked deprecated) |

**Evidence:**
```python
# backend/scraper.py:1-11
"""
DEPRECATED: CAFC website scraper.
This module is DEPRECATED. The sync endpoint now uses CourtListener API.
"""
```

---

## Answer Pipeline Trace

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         USER QUERY                                       │
│                    "What is the Alice test?"                             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 1: DOCTRINE CLASSIFICATION (backend/chat.py)                       │
│  - classify_doctrine_tag() maps query → doctrine (101, 103, 112, etc.)   │
│  - Identifies controlling SCOTUS cases for injection                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 2: FULL-TEXT SEARCH (backend/db_postgres.py)                       │
│  - PostgreSQL GIN index with ts_rank                                     │
│  - OR-based to_tsquery for flexible matching                             │
│  - Returns matching document_pages with relevance scores                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 3: CONTROLLING CASE INJECTION (backend/chat.py)                    │
│  - fetch_controlling_scotus_pages() injects SCOTUS authority             │
│  - Alice, Mayo, KSR, Phillips, Markman always appear for doctrine        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 4: PRECEDENCE-AWARE RANKING (backend/ranking_scorer.py)            │
│  - Composite score = relevance × authority × gravity × recency           │
│  - Authority: SCOTUS (1.8) > en banc (1.6) > precedential (1.3)          │
│  - Two-pass retrieval: authoritative first, then precedential            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 5: QUOTABLE PASSAGE EXTRACTION (backend/chat.py)                   │
│  - extract_quotable_passages() identifies ~50 legal holdings per context │
│  - Labeled [Q1], [Q2]... for AI reference                                │
│  - GPT-4o-mini fallback when heuristics yield <3 passages                │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 6: CONTEXT BUILDING (backend/chat.py:build_context)                │
│  - Adjacent page expansion (±3 pages for continuity)                     │
│  - Token-aware pruning (80k limit via tiktoken)                          │
│  - Score-based prioritization                                            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 7: LLM GENERATION (OpenAI GPT-4o)                                  │
│  - Temperature: 0.1 (deterministic)                                      │
│  - Dynamic max_tokens: 1500 base + 500 per opinion_id (max 4000)         │
│  - System prompt enforces quote-first generation                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 8: CITATION VERIFICATION (backend/chat.py)                         │
│  - verify_quote_strict(): normalized substring match                     │
│  - verify_quote_with_case_binding(): page-level then case-level fallback │
│  - Confidence tiers: STRONG ≥70, MODERATE 50-69, WEAK 30-49, UNVERIFIED  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 9: WEB SEARCH FALLBACK (if NOT FOUND)                              │
│  - Tavily search for case citations                                      │
│  - CourtListener lookup and auto-ingestion                               │
│  - Retry query with new context                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 10: RESPONSE FORMATTING                                            │
│  - make_citations_clickable(): ([1] *Case Name*) format                  │
│  - Sources with PDF links, page numbers, confidence tiers                │
│  - Telemetry recording (verified %, latency)                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### Hallucination Risk Points

| Location | Risk | Mitigation |
|----------|------|------------|
| LLM Generation | Model may fabricate quotes | Quote-first prompt, [Q#] references only |
| Citation Binding | Wrong page attribution | Two-tier verification (page → case level) |
| Web Search | Unvetted external content | Only ingests from CourtListener |
| OCR Extraction | Garbled text | pytesseract + normalization variants |

---

## Citation Verification System

### Verification Flow

```python
# backend/chat.py:926-966
def verify_quote_with_case_binding(quote, claimed_opinion_id, pages, allow_case_level_fallback=True):
    # Pass 1: Strict page-level match
    for page in pages:
        if page["opinion_id"] == claimed_opinion_id:
            if verify_quote_strict(quote, page["text"]):
                return page, "strict", ["page_bound"]
    
    # Pass 2: Case-level fallback (caps at MODERATE tier)
    for page in opinion_pages:
        is_match, match_type = verify_quote_with_normalization_variants(quote, page["text"])
        if is_match:
            return page, "case_level", ["case_bound", "case_level_match"]
    
    return None, "failed", ["binding_failed"]
```

### Confidence Scoring Formula

```
Score = binding_score + match_score + section_bonus + recency_bonus

Where:
- binding_score: strict=40, fuzzy=25
- match_score: exact=30, partial=15
- section_bonus: holding=+15, dicta=-5
- recency_bonus: post-2020=+10
```

### Telemetry Tracking

| Metric | Target | Tracked |
|--------|--------|---------|
| Verified Citations | ≥90% (STRICT mode) | ✅ citation_telemetry table |
| Case-Attributed Unsupported | ≤0.5% | ✅ propositions_case_attributed_unsupported |
| P95 Latency | <10s | ✅ latency_ms column |
| Failure Reasons | Categorized | ✅ binding_failure_reasons JSON |

---

## Data Freshness & Update Mechanisms

### Scheduled Sync (Weekly)

```python
# backend/scheduled_sync.py:17-29
COURTLISTENER_BASE_URL = "https://www.courtlistener.com/api/rest/v4"
COURTLISTENER_API_TOKEN = os.environ.get("COURTLISTENER_API_TOKEN", "")

def get_session() -> requests.Session:
    session = requests.Session()
    headers = {
        'User-Agent': 'Federal-Circuit-AI-Research/1.0',
        'Authorization': f'Token {COURTLISTENER_API_TOKEN}'
    }
    session.headers.update(headers)
    return session
```

### On-Demand Web Search Ingestion

When local search returns "NOT FOUND":
1. Query Tavily for case citations
2. Extract case names from results
3. Look up in CourtListener
4. Ingest new cases automatically
5. Retry query with fresh context

---

## OCR Recovery System

```python
# backend/ocr_recovery.py:24-26
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

# Prioritized landmark cases
BIG_5_LANDMARK_CASES = ["Markman", "Phillips", "Vitronics", "Alice", "KSR"]
```

| Parameter | Value |
|-----------|-------|
| DPI | 150 (balanced speed/quality) |
| Min Recovered Chars | 5,000 |
| Hollow Detection | <1000 total chars OR <200 chars/page |

---

## Security & Authentication

### External API Endpoint

```python
# backend/external_api.py:86-109
def get_api_key():
    return os.environ.get("EXTERNAL_API_KEY")

async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    expected_key = get_api_key()
    if x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
```

### Rate Limiting

| Endpoint | Rate | Capacity |
|----------|------|----------|
| External API (`/api/v1/query`) | 5 req/sec | 10 burst |
| Internal Chat (`/api/chat`) | 10 req/sec | 20 burst |

---

## Risks & Mitigations

| Risk | Severity | Current Status | Mitigation |
|------|----------|----------------|------------|
| **LLM Hallucination** | High | Mitigated | Quote-first prompt, [Q#] binding, verification |
| **Stale Corpus** | Medium | Mitigated | Weekly CourtListener sync + web search |
| **OCR Errors** | Medium | Mitigated | pytesseract recovery, normalization variants |
| **API Rate Limits** | Low | Mitigated | Exponential backoff, rate limiters |
| **CourtListener TOS** | Low | Compliant | Proper attribution, reasonable rate |
| **PDF Copyright** | Low | Compliant | Government documents (public domain) |

---

## Voyager Readiness Score: 79/100

### Breakdown

| Criterion | Weight | Score | Weighted |
|-----------|--------|-------|----------|
| Provenance | 20% | 85 | 17.0 |
| Coverage | 15% | 75 | 11.25 |
| Recency Controls | 15% | 70 | 10.5 |
| Determinism & Auditability | 20% | 80 | 16.0 |
| Citation Support | 20% | 90 | 18.0 |
| Data Hygiene | 10% | 75 | 7.5 |
| **TOTAL** | **100%** | | **80.25** |

**Rounded Score: 79/100** ✅ Voyager Ready

### Next Steps for 90+ Score

1. **Add PTAB coverage** - Ingest Patent Trial and Appeal Board decisions
2. **Implement vector embeddings** - Add semantic search alongside FTS
3. **Add corpus versioning** - Tag each document with ingest timestamp
4. **Expand SCOTUS coverage** - Currently 15 landmark cases, expand to 50+
5. **Add audit logging** - Full request/response logging for reproducibility

---

## Evidence Appendix

### File Paths & Key Functions

| Component | File | Key Functions |
|-----------|------|---------------|
| Main Chat | `backend/chat.py` (3,532 lines) | `generate_chat_response()`, `build_context()`, `verify_quote_*()` |
| Database | `backend/db_postgres.py` (1,760 lines) | `search_pages_fts()`, `get_page_by_id()` |
| Ranking | `backend/ranking_scorer.py` (708 lines) | `compute_composite_score()`, `apply_authority_boost()` |
| Web Search | `backend/web_search.py` (422 lines) | `search_tavily()`, `lookup_courtlistener()` |
| Ingestion | `backend/ingestion.py` (305 lines) | `ingest_opinion()`, `download_pdf_with_retry()` |
| OCR | `backend/ocr_recovery.py` (413 lines) | `ocr_pdf()`, `get_hollow_documents()` |
| Sync | `backend/scheduled_sync.py` (410 lines) | `sync_new_opinions()` |
| External API | `backend/external_api.py` (233 lines) | `query_patent_law()` |
| Telemetry | `backend/telemetry.py` (365 lines) | `record_citation_telemetry()` |

### Environment Variables Required

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | ✅ | PostgreSQL connection |
| `AI_INTEGRATIONS_OPENAI_API_KEY` | ✅ | GPT-4o access |
| `AI_INTEGRATIONS_OPENAI_BASE_URL` | ✅ | Replit AI proxy |
| `COURTLISTENER_API_TOKEN` | ✅ | CourtListener API |
| `TAVILY_API_KEY` | ✅ | Web search fallback |
| `EXTERNAL_API_KEY` | ✅ | External API auth |
| `CHAT_MODEL` | ❌ | Override model (default: gpt-4o) |

---

**Report Generated:** January 31, 2026  
**Codebase Version:** Commit `27c5f5b9`  
**Total Backend LOC:** 12,272 lines Python
