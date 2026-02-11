# Merge Resolution Review (Current Branch)

This review confirms that key merge fixes remain in place and documents additional cleanup needed to remove legacy strict-mode UX remnants.

## What was verified

1. **Disambiguation helpers exist and are wired into chat flow**
   - `backend/disambiguation.py` exports:
     - `detect_option_reference`
     - `resolve_candidate_reference`
     - `is_probable_disambiguation_followup`
   - `backend/chat.py` imports and uses those helpers.

2. **Disambiguation return path is preserved**
   - `backend/chat.py` still stores pending candidates and returns the `disambiguation` branch payload.

3. **Query canonicalization is still active**
   - `backend/smart/query_decompose.py` still calls `canonicalize_legal_query` before decomposition/routing.

4. **Release gate scope still targets the intended guarded tests**
   - `scripts/ci_release_gate.sh` still runs the ranking, canonicalization, and disambiguation checks.

## Additional fixes required (and now applied)

1. **Eliminate remaining citation-guide surface area**
   - Removed `/citation-guide` route from `client/src/App.tsx`.
   - Removed legacy `client/src/pages/CitationGuide.tsx` page.

2. **Align all attorney-mode defaults to opt-in**
   - Confirmed API request models default to `False`.
   - Updated chat entry points in `backend/chat.py` (`generate_chat_response`, `generate_chat_response_stream`) to default `attorney_mode=False`.

3. **Remove manual requirement phrasing from help copy**
   - Reworded unverified citation text to avoid “manual verification required” language.

4. **Harden the merge verification script against regressions**
   - `scripts/verify_merge_resolutions.py` now checks both presence of required merge fixes and absence of removed legacy citation-guide route/page.

## Commands used

- `python scripts/verify_merge_resolutions.py`
- `npm run check`
- `pytest -q backend/tests/test_query_canonicalization.py backend/tests/test_ranking_scorer.py tests/test_disambiguation.py`

## Current caveat

`ci_release_gate.sh` fails in this environment due missing optional runtime dependencies (`httpx`, `psycopg2`), which cause skipped tests and trigger the gate's env-parity failure condition.
