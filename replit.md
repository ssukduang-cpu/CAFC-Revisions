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

### Backend (Express + Node.js)
- **Framework:** Express.js with TypeScript
- **API Pattern:** RESTful endpoints under `/api/`
- **Key Endpoints:**
  - `POST /api/opinions/sync` - Scrapes CAFC website for new opinions
  - `POST /api/opinions/:id/ingest` - Downloads PDF, extracts text, creates chunks
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

### Recent Changes (Jan 2026)

- Migrated from Node.js/PostgreSQL to Python FastAPI/SQLite for memory efficiency
- Fixed FTS5 query escaping to handle special characters (?, ., +, etc.)
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
- **Drizzle ORM:** Type-safe database operations with schema in `shared/schema.ts`

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