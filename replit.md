# CAFC Opinion Assistant

## Overview

A full-stack legal research application that enables natural-language conversations with precedential CAFC (Court of Appeals for the Federal Circuit) opinions. The system scrapes, ingests, and indexes federal court opinions, then uses RAG (Retrieval-Augmented Generation) to provide citation-backed answers from the actual opinion text.

**Core Purpose:** Allow legal practitioners to query CAFC precedent with strict source verification - every claim must be supported by verbatim quotes from ingested PDFs with proper citations.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend (React + Vite)
- **Framework:** React with TypeScript, built using Vite
- **UI Components:** shadcn/ui component library with Radix UI primitives
- **Styling:** Tailwind CSS with custom theme variables for light/dark modes
- **State Management:** React Query for server state, React Context for app state
- **Routing:** Wouter (lightweight router)
- **Layout:** Three-panel resizable interface (sidebar, chat, sources panel)

### Backend (Python FastAPI)
- **Framework:** Python FastAPI
- **API Pattern:** RESTful endpoints under `/api/`
- **Key Endpoints:**
  - `POST /api/opinions/sync` - Scrapes CAFC website for new opinions
  - `POST /api/opinions/:id/ingest` - Downloads PDF, extracts text, creates chunks
  - `POST /api/opinions/batch-ingest` - Batch ingest multiple opinions with retry/validation
  - `GET /api/ingestion/status` - Check ingestion progress (total/ingested/pending)
  - `GET /api/integrity/check` - Verify data integrity and FTS5 index health
  - `POST /api/chat` - Sends message and generates RAG response with citations
  - `GET /api/conversations` - Lists chat sessions

### Data Layer
- **Database:** PostgreSQL with Drizzle ORM
- **Schema:** Four main tables - opinions, chunks, conversations, messages
- **Text Search:** Full-text search on chunked opinion text (not vector embeddings currently)
- **PDF Processing:** pdf-parse library for text extraction

### AI Integration
- **Provider:** OpenAI via Replit AI Integrations (managed API keys)
- **Model:** GPT-4o for chat completions
- **RAG Pattern:** Retrieved chunks are injected into system prompt with strict citation requirements
- **Guardrails:** System prompt enforces verbatim quotes and "NOT FOUND IN PROVIDED OPINIONS" for unsupported claims

### Key Design Decisions

1. **Strict Citation Requirement:** The LLM must cite verbatim quotes from opinion text - no training data assertions allowed
2. **Page-Based Retrieval:** PDFs are stored per-page with FTS5 full-text search
3. **Precedential Only:** System filters for CAFC precedential opinions (status="Precedential", documentType="OPINION")
4. **Session Storage:** SQLite stores conversation history for multi-turn chat
5. **Memory Efficient:** Python FastAPI + SQLite uses ~76MB vs Node.js 2GB+ for PDF processing

### Production Database Strategy

**Database Architecture (PostgreSQL):**
- `documents` - Opinion metadata with pdf_url, case_name, appeal_number, ingested status
- `document_pages` - Per-page text extraction (one row per PDF page)
- `document_chunks` - 2-page chunks for RAG retrieval with tsvector FTS
- Full-text search using PostgreSQL GIN index on tsvector columns

**Ingestion Robustness (Jan 2026):**
- **Retry Logic:** Exponential backoff (3 retries, 2s→4s→8s) for PDF downloads
- **Validation:** Checks for empty/corrupt PDFs with min text length requirements
- **SHA256 Tracking:** Avoids re-processing unchanged PDFs
- **Batch Processing:** `POST /api/opinions/batch-ingest` with configurable batch size
- **Integrity Checks:** FTS index health verification, page/chunk counts

**Full Corpus Backfill Strategy (~28,000 opinions):**

**Source: CourtListener API (Primary)**
The system now uses CourtListener as the source of truth for CAFC precedential opinions. This approach provides:
- Access to the complete historical corpus (~28,000 precedential opinions)
- Stable API with cluster_id for deduplication
- No browser automation required (no Playwright/Selenium)
- Direct PDF URLs for reliable downloads

**Steps:**
1. Build manifest from CourtListener API:
   ```bash
   python scripts/build_manifest_courtlistener.py          # Fetch all opinions
   python scripts/build_manifest_courtlistener.py -n 100   # Fetch first 100
   ```
   - Outputs to `data/manifest.ndjson` (NDJSON format)
   - Logs: total_rows_fetched, total_unique_written, duplicates_skipped

2. Import manifest into database:
   ```bash
   curl -X POST http://localhost:8000/api/admin/load_manifest_file
   ```
   - Uses cluster_id-based deduplication
   - Fallback: (appeal_number, pdf_url) if cluster_id missing

3. Run batch ingestion (two options):

   **Option A: Background script (continuous processing)**
   ```bash
   python scripts/background_ingest.py
   ```
   - Processes all pending documents continuously
   - Automatic CourtListener fallback when CAFC URLs return 404
   - Handles batch processing with logging

   **Option B: API batch (single batch)**
   ```bash
   curl -X POST "http://localhost:8000/api/admin/ingest_batch?limit=50"
   ```

4. Monitor progress:
   ```bash
   curl http://localhost:8000/api/admin/ingest_status
   ```

5. Smoke test (builds 100, imports, ingests 5):
   ```bash
   python scripts/smoke_test.py
   ```

**PDF Download Fallback (Jan 2026):**
- CAFC website PDFs often return 404 for historical documents
- Ingestion automatically falls back to CourtListener storage (`storage.courtlistener.com`)
- Uses `local_path` from CourtListener API to fetch cached PDFs
- Status code-based error detection (4xx triggers fallback)

**DEPRECATED: CAFC Website Scraping**
The Playwright-based manifest builder (`scripts/build_manifest.py`) and direct CAFC scraper are deprecated. Use CourtListener for all new backfills.

**Admin Endpoints:**
- `POST /api/admin/build_manifest` - Instructions for manifest build
- `POST /api/admin/ingest_batch?limit=N` - Ingest next N pending documents
- `GET /api/admin/ingest_status` - Total/ingested/pending/failed counts
- `GET /api/search?q=...` - Full-text search across all ingested opinions

### Pending Integrations
- **Email Notifications:** Resend integration was declined. To add email alerts for ingestion errors/completion in the future, either set up the Resend connector or provide a RESEND_API_KEY secret manually.

### Recent Changes (Jan 2026)

- **CourtListener Integration:** Switched from CAFC website scraping to CourtListener API as the source of truth
  - `scripts/build_manifest_courtlistener.py` - Manifest builder using CourtListener Search API
  - Added `courtlistener_cluster_id` and `courtlistener_url` columns for deduplication
  - Deprecated CAFC wpDataTables scraping approach
- **Smoke Test:** Added `scripts/smoke_test.py` for end-to-end pipeline verification
- **PostgreSQL Migration:** Full migration from SQLite to PostgreSQL for production scale
- **Resumable Ingester:** CLI tool with retry logic, SHA256 tracking, and per-page storage
- **Admin API:** Endpoints for batch ingestion control and status monitoring
- **Full-Text Search:** PostgreSQL tsvector/GIN index for fast corpus-wide search
- Fixed conversation endpoint to include messages array for frontend rendering
- Added proxy timeout (120s) for AI-powered chat responses
- Fixed useSendMessage hook to pass conversationId as parameter
- **Patent Litigator Persona:**
  - Natural language output styled as Federal Circuit practitioner briefing
  - Sections: **Bottom Line**, **What the Court Held**, **Practice Note** (optional)
  - No [Claim 1/2] labels in user-facing text - verification kept internal
  - Inline [S1], [S2] markers replace verbose citation blocks
  - Sources panel with: case_name, appeal_no, release_date, page_number, quote
  - Two links per source: "View in app" (viewer_url) and "Open on CAFC" (pdf_url)
  - Backend returns: answer_markdown, sources[], debug{claims, support_audit}
  - STRICT quote verification: quotes must be exact substrings (NFKC normalized)
  - NOT FOUND responses have no sources and no inline markers
- **UX Improvements (Latest):**
  - Auto-open sources panel when clicking [S#] markers
  - Multi-stage loading indicator: Finding precedent → Analyzing → Verifying → Preparing
  - Onboarding banner shows "X of Y opinions indexed" linking to Opinion Library
  - Mobile slide-out drawer for conversations
  - Expandable quotes with "Show more" for long citations (>200 chars)
- **Party-Only Search (Jan 2026):**
  - Toggle between "All Text" and "Parties Only" search modes
  - "Parties Only" searches ONLY case names, not full opinion text
  - Solves problem of finding cases that merely cite a party vs cases where party is a litigant
  - Search mode toggle visible on both welcome screen and conversation views
  - API parameters: `search_mode` (frontend) / `party_only` (backend)
- **Smart Disambiguation & Context Resolution (Jan 2026):**
  - When multiple cases match a query, LLM returns AMBIGUOUS QUERY response with numbered options
  - Frontend displays clickable action buttons for each case option
  - Users can type "1", "the first one", "option 2", "second", etc. to select a case
  - Backend resolves natural language references using word-boundary regex (avoids false positives like "firstly")
  - Action items include opinion_id for direct case lookup without re-searching
  - Helper functions: `detect_option_reference()`, `get_previous_action_items()` in backend/chat.py
  - **Robust Resolution Flow (Latest):**
    - Pending disambiguation stored in `conversations.pending_disambiguation` JSONB column
    - When non-indexed case selected, pending state is preserved so user can select another option
    - Response shows "Available indexed options:" for easy recovery
    - Resolved queries include "(Specifically: [case name])" to prevent LLM re-triggering ambiguity
    - State is only cleared after successful resolution to an indexed case
- **API Response Schema Consistency (Jan 2026):**
  - `standardize_response()` helper promotes debug fields to top-level for all `/api/chat` responses
  - Top-level fields: `return_branch`, `markers_count`, `sources_count`
  - All 11+ return paths in `generate_chat_response()` use consistent schema
  - Regression tests in `tests/test_disambiguation.py` prevent schema drift

## External Dependencies

### Database
- **PostgreSQL:** Primary data store via `DATABASE_URL` environment variable
- **Python psycopg2:** Direct PostgreSQL access with connection pooling
- **Tables:** documents, document_pages, document_chunks, conversations, messages

### AI Services
- **OpenAI API:** Accessed through Replit AI Integrations
  - `AI_INTEGRATIONS_OPENAI_API_KEY` - Managed by Replit
  - `AI_INTEGRATIONS_OPENAI_BASE_URL` - Replit proxy endpoint

### External Data Sources
- **CourtListener API (Primary):** `https://www.courtlistener.com/api/rest/v4/`
  - REST API for fetching CAFC precedential opinions
  - Provides cluster_id for deduplication, PDF download URLs
  - Script: `scripts/build_manifest_courtlistener.py`
- **CAFC Website (DEPRECATED):** `https://www.cafc.uscourts.gov/home/case-information/opinions-orders/`
  - Legacy scraping approach - no longer used for backfill

### Key NPM Packages
- `pdf-parse` - PDF text extraction
- `cheerio` - HTML parsing for web scraping
- `axios` - HTTP client for PDF downloads and API calls
- `drizzle-orm` / `drizzle-kit` - Database ORM and migrations
- `@tanstack/react-query` - Server state management
- `openai` - OpenAI SDK for chat completions