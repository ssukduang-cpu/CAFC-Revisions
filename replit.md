# CAFC Opinion Assistant

## Overview

A full-stack legal research application that provides natural-language conversations with precedential CAFC (Court of Appeals for the Federal Circuit) opinions. The system scrapes, ingests, and indexes federal court opinions, then uses Retrieval-Augmented Generation (RAG) to deliver citation-backed answers derived directly from the opinion text. Its core purpose is to enable legal practitioners to query CAFC precedent with strict source verification, ensuring every claim is supported by verbatim quotes from ingested PDFs with proper citations.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend
- **Framework:** React with TypeScript, built using Vite.
- **UI Components:** shadcn/ui with Radix UI primitives.
- **Styling:** Tailwind CSS, supporting light/dark modes.
- **State Management:** React Query for server state, React Context for application state.
- **Routing:** Wouter.
- **Layout:** Three-panel resizable interface (sidebar, chat, sources panel).
- **UX Improvements:** Auto-opening sources panel, multi-stage loading indicators, onboarding banner, mobile-friendly design, expandable quotes, opinion library dashboard with virtualized lists and integrated PDF viewer, party-only search toggle.
- **Chat Performance:** Server-Sent Events (SSE) for real-time token streaming, conversation context summarization for multi-turn coherence, suggested next steps, LRU cache for legal definitions, parallel processing for context building.
- **Named Case Priority:** Two-stage search for specific case names (e.g., "Phillips v. AWH Corp."):
  1. **Systemic Regex Boundary Protection:** Regex extracts case name with:
     - Legal Interrogatives stop-list (40+ words: say, about, meaning, claim, construction, etc.) that terminate defendant capture
     - Entity suffix anchors (Corp., Inc., LLC, Ltd., GmbH, etc.) that terminate capture immediately after business entity suffixes
     - Hard 4-word limit after "v." unless entity suffix found sooner
     - **Stop word stripping:** Leading interrogatives like "Does", "What", "How" are stripped from plaintiff name
     - DEBUG logging: "Parsed Party Name: [X]" for real-time verification
  2. `find_documents_by_name()` locates matching document IDs with:
     - Case name normalization (Corp./Corporation, Inc./Incorporated)
     - **Flexible matching:** Splits "X v. Y" and matches both parts separately when substring match fails
     - Falls back to plaintiff-only search if full name doesn't match
  3. FTS search within matched documents using extracted legal terms (claim construction, intrinsic evidence, obviousness, indefiniteness, enablement, etc.)
  4. **Fallback page retrieval:** If FTS returns no results but case is found, retrieve pages using broad terms ("court patent")
  5. **Topic Mismatch Handling:** When case is found but doesn't discuss requested topic:
     - AI explains what the case DOES cover instead of returning "NOT FOUND"
     - AI includes proper citation markers pointing to excerpts about what the case covers
     - All responses go through normal strict citation enforcement (no bypass)
  6. **Context Merge Persistence:** Named case pages are ALWAYS preserved across all search fallback paths:
     - Query expansion: Named case pages merged first, then expanded results
     - Manual token extraction: Named case pages merged first, then token results
     - Web search ingestion: Named case pages merged first, then web search results
     - DEBUG logging: "Context Merge Success - X named + Y expanded = Z total"
     - Maximum 15 pages total with named case pages guaranteed to survive

### Backend
- **Framework:** Python FastAPI.
- **API Pattern:** RESTful endpoints under `/api/`.
- **Key Features:** Opinion syncing and ingestion, batch ingestion with retry/validation, ingestion status and integrity checks, RAG-powered chat, conversation history management, admin endpoints for manifest building and batch ingestion control, PDF serving with security.
- **Core Logic:** Strict citation enforcement, page-based retrieval, filtering for precedential opinions, smart disambiguation and context resolution for ambiguous queries, consistent API response schema.

### Data Layer
- **Database:** PostgreSQL with Drizzle ORM.
- **Schema:** Tables for opinions, chunks, conversations, and messages.
- **Text Search:** PostgreSQL GIN index on `tsvector` columns for full-text search across chunked opinion text.
- **PDF Processing:** `pdf-parse` library for text extraction, `cleanup_hyphenated_text()` for hyphenation cleanup.
- **Ingestion Robustness:** Retry logic with exponential backoff, validation for empty/corrupt PDFs, SHA256 tracking to avoid reprocessing, batch processing, integrity checks, and a robust PDF download fallback mechanism to CourtListener.
- **Hollow PDF Validation Gate:** Blocks ingestion of low-quality PDFs:
  - Minimum 200 chars/page for multi-page documents (blocks scanned/image PDFs)
  - Minimum 500 total characters for any document
  - DEBUG logging: "Text Density Score: X chars, Y pages, Z chars/page"
  - Audit script: `backend/audit_hollow_pdfs.py` identifies existing hollow documents
- **OCR Recovery System:** Recovers text from scanned/image PDFs using OCR:
  - Script: `backend/ocr_recovery.py` with pytesseract + pdf2image at 300 DPI
  - Big 5 landmark case priority: Markman, Phillips, Vitronics, Alice, KSR
  - Hollow document detection aligned with validation gate thresholds
  - Status marking: 'recovered' (≥5000 chars) or 'ocr_partial' (less than 5000 chars)
  - Dependency check: `python ocr_recovery.py --check-deps` verifies tesseract/poppler
  - Usage: `python ocr_recovery.py --limit 10 --priority-only` for Big 5 cases

### Advanced Search Features (POST /api/search)
- **Hybrid Ranking:** `ts_rank * (1.0 / (days_old / 365 + 1))` formula boosts recent documents.
- **Phrase Search:** Quoted terms use `phraseto_tsquery` for exact phrase matching.
- **Fuzzy Matching:** pg_trgm `similarity()` > 0.2 on case names for typo-tolerant search.
- **Keyset Pagination:** Base64-encoded cursor with (score, release_date, uuid) tuple for stable ordering.
- **Filters:** author_judge, originating_forum, exclude_r36 (Rule 36 judgments).
- **Rate Limiting:** Leaky bucket algorithm, 10 requests/second capacity per client.

### AI Integration
- **Provider:** OpenAI via Replit AI Integrations.
- **Model:** GPT-4o for chat completions.
- **RAG Pattern:** Retrieved chunks injected into system prompt, enforcing verbatim quotes and "NOT FOUND IN PROVIDED OPINIONS" for unsupported claims.
- **Token Safety:** tiktoken-based counting with 80k token limit on context, 2000 char limit on search results, 3-turn conversation history to prevent token overflow.
- **Persona:** Patent Litigator, styling natural language output as Federal Circuit practitioner briefing with sections like "Bottom Line", "What the Court Held", and "Practice Note". Inline markers like `[S1]` for citations.
- **Landmark Case System:** Curated list of 94 landmark cases organized by doctrine, with citation discovery features.
- **Domain-Specific Search Enhancement:** Fallback search logic includes domain term expansion for patent law queries (reissue/recapture, claim construction, obviousness/anticipation, infringement/equivalents, Alice/Mayo/§101 eligibility). This improves recall for natural language questions about specific patent doctrines.
- **AI-Powered Query Expansion:** When initial FTS search returns insufficient results (<3 pages for long queries), uses GPT-4o to generate 5 related legal keywords before database search. For example, "after-arising technology" expands to ["after-arising technology enablement", "unforeseeable advancements patent scope", "enablement requirement future inventions", "predictability enablement doctrine", "utility and enablement standard"]. This dramatically improves retrieval for conceptual or doctrinal queries that may not match verbatim case text.
- **Agentic Reasoning & Reflection Loop:** Before every response, the system executes an internal reasoning process:
  1. **Query Classification:** Identifies legal doctrine (§101, §102, §103, §112, claim construction)
  2. **Search Strategy:** Lists key terms, synonyms, and relevant landmark cases (KSR, Alice, Phillips, Nautilus)
  3. **Chain-of-Verification (CoVe):** Reflection pass checks relevance, recency, and substantive discussion quality
  4. **Re-ranking Logic:** Prioritizes Supreme Court > En banc > Recent panels > Foundational cases
  5. **Dynamic Synthesis:** Extracts RULE, REASONING, APPLICATION, and doctrinal EVOLUTION
  - DEBUG logging: "Agentic Reasoning Plan" with doctrine/landmarks/context quality, "Reflection Pass" status
- **2025 Hot Topics Reference:** Built-in reference data for recent developments:
  - Obviousness: "Desirable vs. Best" (Honeywell v. 3G Licensing 2025), "Design choice" (USAA v. PNC Bank 2025)
  - Eligibility, Claim Construction, Definiteness doctrine updates

## External Dependencies

### Database
- **PostgreSQL:** Primary data store, accessed via `DATABASE_URL` and `psycopg2`.

### AI Services
- **OpenAI API:** Accessed through Replit AI Integrations using `AI_INTEGRATIONS_OPENAI_API_KEY` and `AI_INTEGRATIONS_OPENAI_BASE_URL`.

### External Data Sources
- **Harvard Iowa Dataset (v7.1):** Comprehensive CAFC precedential opinions dataset (2004-2024), used for building the complete manifest of ~5,968 precedential cases.
- **CAFC Website:** Primary source for PDF downloads (cafc.uscourts.gov/opinions-orders/).
- **CourtListener API:** Fallback source for PDF downloads when CAFC website returns 404, also provides `cluster_id` for deduplication.
- **Tavily API:** Web search for discovering relevant case law when local database lacks coverage. Used via `TAVILY_API_KEY` secret.

### Current Database State (as of January 2026)
- **Total Documents:** 5,079 precedential CAFC opinions
- **Ingested (Searchable):** 4,419 documents (87%) with 41,735 text chunks
- **Failed:** 257 documents (PDFs no longer available on any source)
- **Duplicates:** 403 documents (same case ingested under different name/source)
- **OCR Recovered:** 3 documents (scanned PDFs processed via tesseract)
- **HTML Ingestion:** Older cases (pre-2000s) where PDFs are unavailable can be ingested from law.resource.org HTML versions (e.g., Vitronics v. Conceptronic, Superguide v. DirecTV)

### Hybrid Web Search Integration
- **Search-to-Ingest Pipeline:** When local FTS returns no results or user asks about a specific case not in database, automatically:
  1. Search Tavily for relevant case citations (with domain filtering for legal sources)
  2. Extract case names from web results using improved regex patterns
  3. Look up cases in CourtListener by name to get cluster_id
  4. Auto-ingest new cases (download PDF, extract text, create FTS chunks)
  5. Re-query with enriched local context
- **NewCaseDigest Component:** Frontend component showing recently ingested cases from web search (GET /api/digest/recent)
- **Specific Case Detection:** When query contains "X v. Y" pattern and that case isn't in results, triggers web search even if other results exist
- **Fuzzy Name Matching:** Handles plurals (Technologies → Technology) and stem matching for case name verification
- **web_search_ingests Table:** Tracks cases discovered and ingested via web search

### Key Libraries
- **`pdf-parse`:** For PDF text extraction.
- **`axios`:** For HTTP requests (PDF downloads, API calls).
- **`drizzle-orm` / `drizzle-kit`:** For database ORM and migrations.
- **`@tanstack/react-query`:** For server state management in the frontend.
- **`openai`:** OpenAI SDK for chat completions.