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
  1. Regex extracts case name from query with stop-word filtering
  2. `find_documents_by_name()` locates matching document IDs with case name normalization (Corp./Corporation, Inc./Incorporated)
  3. FTS search within matched documents using extracted legal terms (claim construction, intrinsic evidence, obviousness, etc.)
  4. Merged results prioritize named case pages before general FTS results

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
- **Total Documents:** 5,968 precedential CAFC opinions
- **Ingested (Searchable):** 5,595 documents (93.8%)
- **Total Pages:** 82,154 pages of full-text searchable content
- **Failed:** 115 documents (PDFs no longer available on any source)
- **Duplicates:** 258 documents (same case ingested under different name/source)

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