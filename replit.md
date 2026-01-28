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

### Citation Confidence System
- **Case-Quote Binding:** Strict opinion_id binding for citations; fuzzy case-name fallback (when opinion_id unavailable) capped at MODERATE tier.
- **Confidence Tiers:** Four-tier scoring system (STRONG ≥70, MODERATE 50-69, WEAK 30-49, UNVERIFIED <30).
- **Scoring Formula:** binding (strict=40, fuzzy=25) + match (exact=30, partial=15) + section_type (+/-5-15) + recency (+10 for 2020+).
- **Heuristic Detection:** Detects holding/dicta/concurrence/dissent with clearly labeled *_heuristic signals for transparency.
- **No Silent Substitution:** UNVERIFIED citations display binding_failed signal; misattribution is detected and flagged rather than silently corrected.
- **UI Integration:** ConfidenceBadge component with color-coded tiers; SignalsList for detailed signal display; inline citation buttons colored by tier.

### Quote-First Generation & Verification (Step 5)
- **Quote-First Prompt:** Strict system prompt requiring AI to use only pre-extracted QUOTABLE_PASSAGES; warns that all quotes will be verified.
- **Quotable Passage Extraction:** `extract_quotable_passages()` identifies legal holding indicators (~50 passages per context) labeled [Q1], [Q2], etc.
- **Normalized Verification:** `normalize_for_verification()` handles OCR artifacts, hyphenation, Unicode variants, curly quotes; requires exact contiguous substring match after normalization.
- **Per-Statement Provenance Gating:** `apply_per_statement_provenance_gating()` detects case-attributed statements and tags unsupported ones with [UNSUPPORTED].
- **Citation Telemetry:** Logs total_citations, verified_citations, unverified_rate_pct per query; target: >80% verified with strict matching.
- **Litigation-Grade Integrity:** No fuzzy word-overlap matching; only exact normalized substring matches are accepted to prevent false positives.

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

### Precedence-Aware Ranking (Step 2)
- **Composite Scoring:** Formula = relevance_score × authority_boost × gravity_factor × recency_factor × application_signal
- **Authority Hierarchy:** SCOTUS (1.8) > CAFC en banc (1.6) > CAFC precedential (1.3) > nonprecedential (0.8)
- **Application Signal:** Scoring for "applies" vs "mentions" via holding_indicator (0/1/2), analysis_depth, framework_reference detection, proximity_score
- **Two-Pass Retrieval:** Authoritative sources (SCOTUS + en banc) first, then precedential CAFC/PTAB, merged by composite_score with deduplication
- **"Why This Case?" Explanation:** Frontend displays `application_reason` explaining ranking rationale (e.g., "Supreme Court precedent; applies Alice")
- **Explain Metadata:** Each source includes full scoring breakdown (composite_score, authority_boost, application_signal, holding_indicator, frameworks_detected)

### Doctrine-Triggered Authoritative Candidate Injection
- **Doctrine Classification:** `classify_doctrine_tag()` maps queries to doctrine tags: 101, 103, 112, claim_construction, ptab, remedies, doe
- **Controlling SCOTUS Cases:** Each doctrine has mapped controlling SCOTUS cases (e.g., §101 → Alice/Mayo/Bilski/Diamond v. Diehr; §103 → KSR/Graham)
- **Injection Pipeline:** `fetch_controlling_scotus_pages()` injects SCOTUS pages into candidate pool before ranking
- **Supplementary Sources:** Injected controlling pages always appear as supplementary sources even if AI doesn't explicitly cite them
- **Court Normalization:** `normalize_origin_with_signal()` prioritizes origin metadata, uses case-name fallback only when origin missing (with `court_inferred_from_name` signal)
- **10/10 Golden Queries:** All doctrine queries now surface controlling SCOTUS cases in top-5 results

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
- **Supreme Court (SCOTUS):** 15 landmark patent cases ingested with origin="SCOTUS" for cross-court precedent research. Cases include Alice, Bilski, KSR, eBay, Mayo, Markman, and others covering patent eligibility, obviousness, claim construction, and remedies.

### Hybrid Web Search Integration
- **Search-to-Ingest Pipeline:** Automatically searches Tavily, extracts case names, looks up cases in CourtListener, and ingests new cases to enrich local context.
- **Specific Case Detection:** Triggers web search for "X v. Y" patterns not found locally.

### Citation Telemetry Dashboard
- **Metrics Tracking:** PostgreSQL `citation_telemetry` table stores verification metrics per query.
- **Dashboard UI:** `/telemetry` page showing overall verification rate, queries by doctrine, alerts for low-performing doctrines.
- **Doctrine Breakdown:** Table view with verification rates, citation counts, and latency by doctrine family (101, 103, 112, etc.).
- **Alert System:** Triggers warnings when doctrine verification rate falls below 80% threshold.
- **Binding Failure Analysis:** Tracks and displays top reasons for citation binding failures.
- **Internal Recording:** Telemetry is recorded only from the chat pipeline (no public endpoint) to prevent data poisoning.

### Key Libraries
- **`pdf-parse`:** PDF text extraction.
- **`axios`:** HTTP requests.
- **`drizzle-orm` / `drizzle-kit`:** Database ORM and migrations.
- **`@tanstack/react-query`:** Frontend server state management.
- **`openai`:** OpenAI SDK.