# CAFC Opinion Assistant

## Overview
The CAFC Opinion Assistant is a full-stack legal research application designed for natural-language conversations with precedential opinions from the Court of Appeals for the Federal Circuit (CAFC). It scrapes, ingests, and indexes federal court opinions, using Retrieval-Augmented Generation (RAG) to provide citation-backed answers directly from opinion text. The project aims to streamline legal research, enhance accuracy, and offer instant, verifiable insights into CAFC case law for legal professionals, ensuring all claims are supported by verbatim quotes with proper citations.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend
- **Framework & UI:** React with TypeScript (Vite), shadcn/ui, Tailwind CSS (light/dark modes).
- **State Management:** React Query for server state, React Context for application state.
- **Layout:** Three-panel resizable interface (sidebar, chat, sources panel) with mobile-friendly design.
- **Chat Enhancements:** Server-Sent Events (SSE) for real-time token streaming, conversation context summarization, suggested next steps, LRU cache for legal definitions, and parallel processing.
- **Named Case Priority:** Multi-stage search for specific case names with regex extraction, normalization, flexible matching, and context merge persistence.

### Backend
- **Framework:** Python FastAPI with RESTful endpoints.
- **Core Features:** Opinion syncing and ingestion, RAG-powered chat, conversation history, admin tools, and secure PDF serving.
- **Core Logic:** Strict citation enforcement, page-based retrieval, filtering for precedential opinions, smart disambiguation, and consistent API responses.
- **Citation & Source Generation:** Automatic generation of sources from RAG context pages to ensure all answers are verifiable.
- **Smart NOT FOUND Detection:** Triggers web search fallback only when responses are primarily "NOT FOUND".
- **Advanced FTS Queries:** Uses OR-based `to_tsquery` for long queries, extracting up to 12 key legal terms.

### Citation Confidence System
- **Case-Quote Binding:** Strict `opinion_id` binding for citations with fuzzy case-name fallback.
- **Confidence Tiers:** Four-tier scoring system (STRONG, MODERATE, WEAK, UNVERIFIED).
- **Scoring Formula:** Combines binding type, match type, section type, and recency.
- **Heuristic Detection:** Detects holding/dicta/concurrence/dissent with `*_heuristic` signals.
- **No Silent Substitution:** UNVERIFIED citations display `binding_failed` signal.

### Quote-First Generation & Verification
- **Quote-First Prompt:** Streamlined system prompt requiring AI to use only pre-extracted `QUOTABLE_PASSAGES`, with mandatory failure modes and no-inference rule.
- **Quotable Passage Extraction:** Identifies legal holding indicators labeled [Q1], [Q2], etc., with GPT-4o-mini fallback for low heuristic yield.
- **Normalized Verification:** Handles OCR artifacts, hyphenation, and Unicode variants, requiring exact contiguous substring matches.
- **Per-Statement Provenance Gating:** Detects case-attributed statements and flags unsupported ones, with frontend warnings for Attorney Mode.
- **Litigation-Grade Integrity:** Employs exact normalized substring matches to prevent false positives.

### Anti-Hallucination Optimizations
- **Temperature:** Reduced to 0.1 for deterministic outputs.
- **Dynamic `max_tokens`:** Scales with query complexity.
- **Score-Based Pruning:** Prioritizes highest-scoring pages during context building.
- **LLM-Assisted Quote Extraction:** GPT-4o-mini fallback with guardrails for heuristic failures.

### Data Layer
- **Database:** PostgreSQL with Drizzle ORM.
- **Text Search:** PostgreSQL GIN index for full-text search.
- **PDF Processing:** `pdf-parse` for text extraction and hyphenation cleanup.
- **Ingestion Robustness:** Retry logic, validation, SHA256 tracking, batch processing, and fallback PDF download.
- **OCR Recovery:** System for recovering text from scanned PDFs using `pytesseract` and `pdf2image`.
- **Document Classification:** Automatic classification (`completed`, `errata`, `summary_affirmance`, `order`, `duplicate`) to prevent searching in non-substantive documents.

### Advanced Search Features
- **Hybrid Ranking:** Combines `ts_rank` with recency.
- **Phrase Search:** Supports exact phrase matching.
- **Fuzzy Matching:** Uses `pg_trgm` for typo-tolerant case name search.
- **Filters:** Includes `author_judge`, `originating_forum`, and `exclude_r36`.

### Precedence-Aware Ranking
- **Composite Scoring:** Formula combines relevance, authority, gravity, recency, and application signals.
- **Authority Hierarchy:** Ranks SCOTUS, CAFC en banc, CAFC precedential, and nonprecedential opinions.
- **Application Signal:** Scores for "applies" vs "mentions" via holding indicators and analysis depth.
- **Two-Pass Retrieval:** Authoritative sources (SCOTUS + en banc) first, then precedential CAFC/PTAB.
- **"Why This Case?" Explanation:** Frontend explains ranking rationale.

### Doctrine-Triggered Authoritative Candidate Injection
- **Doctrine Classification:** Maps queries to doctrine tags (e.g., 101, 103, 112).
- **Controlling SCOTUS Cases:** Injects mapped controlling SCOTUS cases into candidate pool.
- **Supplementary Sources:** Injected controlling pages always appear as supplementary sources.

### AI Integration
- **Provider:** OpenAI (via Replit AI Integrations) using GPT-4o.
- **RAG Pattern:** Injects retrieved chunks into system prompts, enforces verbatim quotes, and states "NOT FOUND" for unsupported claims.
- **Token Safety:** `tiktoken`-based counting with an 80k token limit and 3-turn conversation history.
- **Persona:** Patent Litigator, styling output with legal sections and inline citations.
- **Domain-Specific Search Enhancement:** Expands patent law queries with relevant domain terms.
- **AI-Powered Query Expansion:** Generates related legal keywords when initial FTS is insufficient.
- **Agentic Reasoning & Reflection:** Internal reasoning loop for query classification, search strategy, Chain-of-Verification (CoVe), and dynamic synthesis of legal principles.

### Query Classification & Routing (Phase 1+2)
- **Query Classification:** Classifies queries into 5 types: DOCTRINAL, PROCEDURAL, CASE_SPECIFIC, SYNTHESIS, FACT_DEPENDENT.
- **Routing Rules:**
  - DOCTRINAL/PROCEDURAL/SYNTHESIS → doctrine-first approach, retrieval optional
  - CASE_SPECIFIC → retrieval required, grounding mandatory
  - FACT_DEPENDENT → provide legal framework + request missing facts from user
- **Doctrine Mode Fallback:** For doctrinal/procedural queries when retrieval fails, LLM answers from legal training knowledge instead of refusing.
- **Retrieval Confidence:** Scores retrieval quality as HIGH, MODERATE, LOW, or NONE based on page count and ranks.
- **Decision-Path Logging:** Logs query_type, retrieval_confidence, pages_count, doctrine_mode, refusal_detected, ambiguity_detected, freshness_sensitive, validator_triggered, final_response_path for each query.

### Authoritative Post-Response Validator
- **Validator Logic:** Detects invalid refusals for answerable query types and triggers auto-regeneration.
- **Override Triggers:** Refusal on doctrinal/procedural/synthesis when answer is possible, ambiguity requests for clear queries.
- **Correction Instructions:** Provides specific guidance for regeneration based on override reason.
- **Decision Path Authority:** Validator decisions override earlier routing logic.

### Freshness Awareness
- **Temporal Detection:** Detects freshness-sensitive queries via keywords ("latest", "recent", "updated", "2023", "2024", etc.).
- **Fast-Evolving Doctrines:** Auto-flags queries in rapidly changing areas (101 eligibility, PTAB, venue, remedies, claim construction, obviousness).
- **Response Annotation:** Freshness-sensitive responses can include caveats about potential newer developments.

### Authority Reconciliation Pipeline
- **DISCOVER → RECONCILE → SERVE:** Three-stage pipeline for external authority validation.
- **Case Status Types:** PRESENT (fully indexed), PARTIAL (metadata only), ABSENT (mention only).
- **Citation Authority:** Only PRESENT cases can be cited as controlling authority; PARTIAL/ABSENT trigger web search or disclaimers.

### Voyager AI Observability Layer
- **Purpose:** Non-invasive observability, governance, and audit replay layer.
- **Corpus Versioning:** SHA256-based deterministic version IDs.
- **Audit Replay Logging:** Captures complete query provenance for every run via `query_runs` table.
- **Policy Manifest:** `/api/policy` endpoint returns machine-readable governance metadata.
- **Circuit Breaker:** Protects against cascading DB failures (5 failures threshold, 5-min cooldown), states: CLOSED → OPEN → HALF_OPEN.
- **Retention Policy:** Redacts `final_answer` after 90 days, deletes rows after 365 days. Cleanup via `backend/maintenance/cleanup_query_runs.py`.
- **Replay Packet:** `/api/voyager/replay-packet/{run_id}` returns full audit record with size limits (1MB max).
- **Production Tests:** Unit tests in `backend/tests/test_voyager_hardening.py` cover circuit breaker, retention, and replay packet.

## External Dependencies

### Database
- **PostgreSQL:** Primary data store.

### AI Services
- **OpenAI API:** For AI model interactions.

### External Data Sources
- **Harvard Iowa Dataset (v7.1):** Initial manifest of CAFC precedential opinions.
- **CAFC Website:** Primary source for PDF downloads.
- **CourtListener API:** Fallback for PDF downloads and `cluster_id` for deduplication.
- **Tavily API:** For web search to discover new case law and aid in ingestion.
- **Supreme Court (SCOTUS):** 15 landmark patent cases ingested for cross-court precedent research.

### Hybrid Web Search Integration
- **Search-to-Ingest Pipeline:** Automatically searches Tavily, extracts case names, looks up cases in CourtListener, and ingests new cases.

### Citation Telemetry Dashboard
- **Metrics Tracking:** PostgreSQL `citation_telemetry` table stores verification metrics per query.
- **Dashboard UI:** `/telemetry` page with mode toggle (STRICT/RESEARCH), verified rate cards, and per-doctrine drill-down.

### Internal Eval Runner
- **Purpose:** Batch prompt evaluation system for validating verification rates and system performance.
- **Database:** `eval_runs` and `eval_results` tables store run metadata and results.
- **Prompt Bank:** 200 prompts organized by 10 doctrine families.