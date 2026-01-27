# CAFC Opinion Assistant

## Overview
The CAFC Opinion Assistant is a full-stack legal research application designed to provide natural-language conversations with precedential opinions from the Court of Appeals for the Federal Circuit (CAFC). It scrapes, ingests, and indexes federal court opinions, utilizing Retrieval-Augmented Generation (RAG) to deliver citation-backed answers directly from the opinion text. Its primary purpose is to empower legal professionals to query CAFC precedent with strict source verification, ensuring all claims are supported by verbatim quotes from ingested PDFs with proper citations. The project aims to streamline legal research, enhance accuracy, and provide instant, verifiable insights into CAFC case law.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend
- **Framework & UI:** React with TypeScript (Vite), shadcn/ui (Radix UI primitives), Tailwind CSS (light/dark modes).
- **State Management:** React Query for server state, React Context for application state.
- **Routing:** Wouter.
- **Layout:** Three-panel resizable interface (sidebar, chat, sources panel) with mobile-friendly design.
- **Chat Enhancements:** Server-Sent Events (SSE) for real-time token streaming, conversation context summarization, suggested next steps, LRU cache for legal definitions, parallel processing for context building.
- **Named Case Priority:** A multi-stage search process for specific case names, including regex-based extraction, normalization, flexible matching, fallback page retrieval, topic mismatch handling, and context merge persistence. Named case pages are always prioritized and preserved in search results.

### Backend
- **Framework:** Python FastAPI with RESTful endpoints.
- **Core Features:** Opinion syncing and ingestion, batch processing with retry/validation, ingestion status checks, RAG-powered chat, conversation history, admin tools, and secure PDF serving.
- **Core Logic:** Strict citation enforcement, page-based retrieval, filtering for precedential opinions, smart disambiguation, consistent API responses.
- **Citation & Source Generation:** Automatic generation of sources from RAG context pages when AI responses lack explicit citation markers, ensuring all answers are verifiable.
- **Smart NOT FOUND Detection:** Triggers web search fallback only when responses are primarily "NOT FOUND".
- **Advanced FTS Queries:** Uses OR-based `to_tsquery` for long queries, extracting up to 12 key legal terms for flexible matching.

### Data Layer
- **Database:** PostgreSQL with Drizzle ORM.
- **Schema:** Tables for opinions, chunks, conversations, and messages.
- **Text Search:** PostgreSQL GIN index for full-text search.
- **PDF Processing:** `pdf-parse` for text extraction, `cleanup_hyphenated_text()` for hyphenation cleanup.
- **Ingestion Robustness:** Retry logic, validation for corrupt PDFs, SHA256 tracking, batch processing, and a fallback PDF download mechanism.
- **Hollow PDF Validation:** Blocks ingestion of low-quality PDFs based on character density per page.
- **OCR Recovery:** System for recovering text from scanned/image PDFs using `pytesseract` and `pdf2image`, prioritizing landmark cases.
- **Document Classification:** Automatic classification during ingestion (`completed`, `errata`, `summary_affirmance`, `order`, `duplicate`) to prevent searching in non-substantive documents.

### Advanced Search Features
- **Hybrid Ranking:** Combines `ts_rank` with recency for boosted results.
- **Phrase Search:** Supports exact phrase matching for quoted terms.
- **Fuzzy Matching:** Uses `pg_trgm` for typo-tolerant case name search.
- **Pagination:** Keyset pagination with a base64-encoded cursor.
- **Filters:** Includes `author_judge`, `originating_forum`, and `exclude_r36`.
- **Rate Limiting:** Leaky bucket algorithm for API requests.

### AI Integration
- **Provider:** OpenAI (via Replit AI Integrations) using GPT-4o.
- **RAG Pattern:** Injects retrieved chunks into system prompts, enforces verbatim quotes, and explicitly states "NOT FOUND IN PROVIDED OPINIONS" for unsupported claims.
- **Token Safety:** `tiktoken`-based counting, 80k token limit, 2000-character search result limit, 3-turn conversation history.
- **Persona:** Patent Litigator, styling output with legal sections and inline citations.
- **Landmark Case System:** Curated list of 94 landmark cases with citation discovery.
- **Domain-Specific Search Enhancement:** Expands patent law queries with relevant domain terms for improved recall.
- **AI-Powered Query Expansion:** Generates related legal keywords for database search when initial FTS yields insufficient results.
- **Agentic Reasoning & Reflection:** Internal reasoning loop before every response, including query classification, search strategy, Chain-of-Verification (CoVe) for relevance and quality, re-ranking logic, and dynamic synthesis of legal principles.

## External Dependencies

### Database
- **PostgreSQL:** Primary data store.

### AI Services
- **OpenAI API:** For AI model interactions.

### External Data Sources
- **Harvard Iowa Dataset (v7.1):** Used for the initial manifest of CAFC precedential opinions.
- **CAFC Website:** Primary source for PDF downloads.
- **CourtListener API:** Fallback for PDF downloads and provides `cluster_id` for deduplication.
- **Tavily API:** For web search to discover new case law and aid in ingestion when local database lacks coverage.

### Hybrid Web Search Integration
- **Search-to-Ingest Pipeline:** Automatically searches Tavily, extracts case names, looks up cases in CourtListener, and ingests new cases to enrich local context.
- **Specific Case Detection:** Triggers web search for "X v. Y" patterns not found locally.

### Key Libraries
- **`pdf-parse`:** PDF text extraction.
- **`axios`:** HTTP requests.
- **`drizzle-orm` / `drizzle-kit`:** Database ORM and migrations.
- **`@tanstack/react-query`:** Frontend server state management.
- **`openai`:** OpenAI SDK.