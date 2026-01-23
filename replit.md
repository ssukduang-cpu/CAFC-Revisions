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

**Full Corpus Backfill Strategy (~4,000 opinions):**
1. Run Playwright manifest builder to extract all opinion URLs:
   - `python scripts/build_manifest.py` (requires Playwright chromium)
   - Paginates through CAFC table with Precedential+OPINION filters
   - Saves to `data/manifest.ndjson` with progress resume
2. Load manifest into database: `python scripts/build_manifest.py --load-to-db`
3. Run batch ingestion in chunks:
   - `python -m backend.ingest.run --limit 50`
   - Or via API: `POST /api/admin/ingest_batch?limit=50`
4. Monitor progress: `GET /api/admin/ingest_status`
5. Verify integrity: `GET /api/integrity/check`

**Admin Endpoints:**
- `POST /api/admin/build_manifest` - Instructions for manifest build
- `POST /api/admin/ingest_batch?limit=N` - Ingest next N pending documents
- `GET /api/admin/ingest_status` - Total/ingested/pending/failed counts
- `GET /api/search?q=...` - Full-text search across all ingested opinions

### Recent Changes (Jan 2026)

- **PostgreSQL Migration:** Full migration from SQLite to PostgreSQL for production scale
- **Playwright Manifest Builder:** Script to extract all ~4,000 precedential opinions from CAFC
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
- **CAFC Website:** `https://www.cafc.uscourts.gov/home/case-information/opinions-orders/`
  - Scraped using axios and cheerio for opinion metadata and PDF URLs

### Key NPM Packages
- `pdf-parse` - PDF text extraction
- `cheerio` - HTML parsing for web scraping
- `axios` - HTTP client for PDF downloads and API calls
- `drizzle-orm` / `drizzle-kit` - Database ORM and migrations
- `@tanstack/react-query` - Server state management
- `openai` - OpenAI SDK for chat completions