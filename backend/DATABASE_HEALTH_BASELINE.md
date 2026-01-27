# CAFC Database Health Baseline Report

**Generated:** 2026-01-27

---

## Executive Summary

| Metric | Count |
|--------|-------|
| **Total Documents** | 5,087 |
| **Searchable (Completed + Recovered)** | 4,159 |
| **Duplicates (Marked)** | 716 |
| **Failed (PDF Unavailable)** | 127 |
| **Errata (Corrections)** | 82 |
| **Summary Affirmance (Rule 36)** | 3 |
| **Orders** | 1 |
| **Total Pages** | 78,792 |
| **Indexed Pages (FTS)** | 78,792 |
| **Total Chunks** | 40,782 |
| **Integrity Issues** | 0 |

---

## Status Definitions

| Status | Description | Searchable |
|--------|-------------|------------|
| completed | Full precedential opinion with extracted text | Yes |
| recovered | OCR-recovered scanned PDF | Yes |
| duplicate | Redundant copy (by appeal number) - kept highest quality version | No |
| failed | PDF no longer available from any source | No |
| errata | Correction/erratum document (not substantive opinion) | No |
| summary_affirmance | Rule 36 judgment (no written opinion) | No |
| order | Procedural court order | No |
| ocr_partial | Partially recovered via OCR | Limited |

---

## Data Integrity Status

**All integrity checks passed.**

- Zero metadata/page count mismatches
- Zero pages missing tsvector index  
- Zero hollow documents (low text density)
- Zero orphaned chunks

---

## Duplicate Documents (716)

All duplicates have been identified by matching appeal_number. The version with the highest page/chunk count was retained, and redundant copies marked as duplicate.

### Deduplication Logic
1. Group documents by appeal_number
2. For each group with multiple entries, keep the one with highest (pages + chunks)
3. Mark all others as status = duplicate
4. Delete their pages and chunks to free storage

### Verification
- Duplicate appeal numbers in active status: **0**
- All 716 duplicates properly marked

---

## Rule 36 / Summary Affirmance Cases (3)

These are summary affirmances issued under FRAP Rule 36 with no written opinion.

| Case Name | Appeal Number | Date |
|-----------|---------------|------|
| In re Honeywell International Inc. | 2016-1839 | 2017-04-06 |
| International Controls & Measurements Corp. v. Honeywell | 2015-1724 | 2016-03-14 |
| Mexichem Amanco Holding v. Honeywell International | 2016-1038, 2016-1041 | 2016-10-11 |

---

## Searchable Document Statistics

- **Total Searchable:** 4,159 documents
- **100% FTS Indexed:** All 78,792 pages have text_search_vector populated
- **Zero Missing Vectors:** No pages with text but missing search index

---

## Landmark Cases Verification

| Case | Appeal | Status | Pages | Chunks |
|------|--------|--------|-------|--------|
| ATHENA DIAGNOSTICS v. MAYO | 17-2508 | completed | 86 | 43 |
| AMGEN INC. v. SANDOZ | 15-1499 | completed | 24 | 12 |
| Honeywell v. 3G Licensing (2025) | 23-1354 | completed | 23 | 12 |
| USAA v. PNC Bank (Obviousness) | 23-2171 | completed | 11 | 13 |
| USAA v. PNC Bank (Section 101) | 23-1639 | completed | 13 | 18 |
| H-W Technology v. Overstock | N/A | completed | 13 | 7 |

---

## Failed Documents (127)

These documents have PDFs that are no longer available from any source (CAFC, CourtListener, Justia).

---

## Errata Documents (82)

Correction notices classified separately to prevent chatbot from searching for substantive holdings.

---

## Data Quality Assurance

### Hollow PDF Detection
All documents pass minimum text density requirements:
- Multi-page documents: >= 200 chars/page average
- All documents: >= 500 total characters

### OCR Recovery
- 2 documents successfully recovered via OCR
- 1 document partially recovered

---

## File Locations

- JSON Report: backend/database_health_baseline.json
- This Report: backend/DATABASE_HEALTH_BASELINE.md

---

*Baseline generated after completing systemic repairs including hard deduplication, metadata synchronization, and FTS index verification.*
