# Zero-Friction UX Program — Execution Board

## Column Definitions

- **Ready**: Scoped, dependencies clear, can start now.
- **In Progress**: Actively being built.
- **Validation**: Coded, needs QA/UAT/metrics verification.
- **Done**: Merged and monitored.

## Ready

### EX-01 Stream-first chat path

- **Owner:** FE + BE
- **Goal:** Route default chat UX through SSE streaming endpoint for TTFT improvements.
- **Current references:**
  - FE currently sends through conversation messages endpoint.
  - Streaming endpoint exists in backend.
- **Acceptance criteria:**
  - First token appears <2s p50 in staging.
  - Fallback to non-stream path if SSE fails.

### EX-02 Stage-based progress UI

- **Owner:** FE
- **Goal:** Replace silent waiting with explicit stage feedback.
- **Stages:** Understanding → Searching corpus → Drafting → Verifying citations.
- **Acceptance criteria:**
  - Stage text updates at least once before first token on slow requests.
  - No regressions to existing search progress behavior.

### EX-03 Auto-mode inference (with override)

- **Owner:** BE + FE
- **Goal:** Infer strict vs exploratory mode automatically while keeping manual override.
- **Acceptance criteria:**
  - Inference metadata is logged.
  - User-selected mode overrides inferred mode.

### EX-04 Answer trust banner

- **Owner:** FE + BE
- **Goal:** Show one-line trust status per answer (mode, doctrine tags, citation mix).
- **Acceptance criteria:**
  - Rendered above every assistant answer.
  - No extra click required.

### EX-05 One-click negative feedback capture

- **Owner:** FE + BE
- **Goal:** Add quick feedback options: "Not helpful" and "Irrelevant citation".
- **Acceptance criteria:**
  - One click emits event with prompt/answer context.
  - No mandatory text form.

## In Progress

### EX-06 Canonicalization v2 + doctrine confidence

- **Owner:** BE Retrieval
- **Goal:** Expand phrase coverage with token-cluster logic and confidence scoring.
- **Acceptance criteria:**
  - 20+ real-world paraphrases map correctly.
  - Confidence emitted for downstream routing.

## Validation

### EX-07 Certificate-correction routing reliability

- **Owner:** QA + BE
- **Goal:** Verify no regressions and eliminate `doe` false positives.
- **Acceptance criteria:**
  - Extended regression suite passes for §§252/254/255 variants.
  - Zero false `doe` hits on "does..." prompts.

### EX-08 First-message continuity UX

- **Owner:** FE QA
- **Goal:** Confirm no disappearing prompt under slow network and first-conversation flows.
- **Acceptance criteria:**
  - Prompt visible immediately in 100% manual QA runs for target browsers.

## Done

### EX-09 Baseline canonicalization + doctrine/correction support

- **Owner:** BE
- **Status:** Shipped.

### EX-10 Doctrine classifier hardening + correction tag

- **Owner:** BE
- **Status:** Shipped.

## Weekly Cadence

- **Monday:** Move top 2 Ready cards to In Progress.
- **Wednesday:** 20-minute blockers review.
- **Friday:** Validation review against:
  1. TTFT p50/p95
  2. Irrelevant citation event rate
  3. Prompt rewrite rate

## Immediate Next Action

Start **EX-01** and **EX-02** first to maximize visible UX impact with low legal risk.


## Release Caveat Gate (Do Not Skip)

- **Gate ID:** ENV-PARITY-DISAMBIGUATION
- **Why:** Current local validation can pass with skips if optional dependencies are unavailable.
- **Production exit criteria:**
  - Run disambiguation + ranking + canonicalization tests in dependency-complete CI/staging.
  - Require no dependency-skipped tests for DB/web-search dependent disambiguation checks.
- **Owner:** QA + Platform
- **Severity:** Release-blocking for production launch.
