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

### AI Integration
- **Provider:** OpenAI via Replit AI Integrations.
- **Model:** GPT-4o for chat completions.
- **RAG Pattern:** Retrieved chunks injected into system prompt, enforcing verbatim quotes and "NOT FOUND IN PROVIDED OPINIONS" for unsupported claims.
- **Persona:** Patent Litigator, styling natural language output as Federal Circuit practitioner briefing with sections like "Bottom Line", "What the Court Held", and "Practice Note". Inline markers like `[S1]` for citations.
- **Landmark Case System:** Curated list of 94 landmark cases organized by doctrine, with citation discovery features.

## External Dependencies

### Database
- **PostgreSQL:** Primary data store, accessed via `DATABASE_URL` and `psycopg2`.

### AI Services
- **OpenAI API:** Accessed through Replit AI Integrations using `AI_INTEGRATIONS_OPENAI_API_KEY` and `AI_INTEGRATIONS_OPENAI_BASE_URL`.

### External Data Sources
- **CourtListener API:** Primary source for fetching CAFC precedential opinions, providing `cluster_id` for deduplication and PDF download URLs.

### Key Libraries
- **`pdf-parse`:** For PDF text extraction.
- **`axios`:** For HTTP requests (PDF downloads, API calls).
- **`drizzle-orm` / `drizzle-kit`:** For database ORM and migrations.
- **`@tanstack/react-query`:** For server state management in the frontend.
- **`openai`:** OpenAI SDK for chat completions.