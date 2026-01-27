#!/usr/bin/env python3
"""
Ingestion Audit Script: Identify and mark hollow PDFs with low text density.

This script:
1. Iterates through the database to find documents with:
   - page_count = 0 or NULL
   - character_count < 1,000
   - text density (chars/pages) < 200
2. Marks these as 'INGESTION_FAILED' or flags for OCR re-ingestion
3. Logs detailed statistics for monitoring
"""

import os
import sys
import logging
import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

# Thresholds
MIN_CHARS_PER_PAGE = 200  # Minimum chars/page for valid text extraction
MIN_TOTAL_CHARS = 1000    # Minimum total characters for a document
MIN_PAGES_EXPECTED = 1    # Minimum expected pages for a valid document


def get_connection():
    """Get database connection."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def audit_hollow_pdfs(dry_run=True):
    """
    Audit the database for hollow PDFs and mark them for re-ingestion.
    
    Args:
        dry_run: If True, only report findings without making changes
    
    Returns:
        dict with audit statistics
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    stats = {
        'total_completed': 0,
        'hollow_no_pages': 0,
        'hollow_low_chars': 0,
        'hollow_low_density': 0,
        'valid': 0,
        'flagged_for_ocr': []
    }
    
    # Query to find hollow PDFs
    query = """
        SELECT 
            d.id,
            d.case_name,
            d.pdf_url,
            d.total_pages,
            d.status,
            COALESCE(SUM(LENGTH(dp.text)), 0) as total_chars,
            CASE 
                WHEN d.total_pages > 0 THEN COALESCE(SUM(LENGTH(dp.text)), 0)::float / d.total_pages 
                ELSE 0 
            END as chars_per_page
        FROM documents d
        LEFT JOIN document_pages dp ON d.id = dp.document_id
        WHERE d.status = 'completed'
        GROUP BY d.id, d.case_name, d.pdf_url, d.total_pages, d.status
        ORDER BY chars_per_page ASC NULLS FIRST
    """
    
    cursor.execute(query)
    documents = cursor.fetchall()
    stats['total_completed'] = len(documents)
    
    hollow_docs = []
    
    for doc in documents:
        doc_id = doc['id']
        case_name = doc['case_name'] or 'Unknown'
        total_pages = doc['total_pages'] or 0
        total_chars = doc['total_chars'] or 0
        chars_per_page = doc['chars_per_page'] or 0
        
        is_hollow = False
        reason = None
        
        # Check 1: No pages
        if total_pages == 0 or total_pages is None:
            # Special case: HTML-ingested docs may have NULL total_pages but have text
            if total_chars < MIN_TOTAL_CHARS:
                is_hollow = True
                reason = 'NO_PAGES_NO_TEXT'
                stats['hollow_no_pages'] += 1
        
        # Check 2: Very low total chars
        elif total_chars < MIN_TOTAL_CHARS:
            is_hollow = True
            reason = 'LOW_TOTAL_CHARS'
            stats['hollow_low_chars'] += 1
        
        # Check 3: Low text density (chars per page)
        elif chars_per_page < MIN_CHARS_PER_PAGE:
            is_hollow = True
            reason = 'LOW_DENSITY'
            stats['hollow_low_density'] += 1
        
        else:
            stats['valid'] += 1
        
        if is_hollow:
            hollow_docs.append({
                'id': str(doc_id),
                'case_name': case_name[:60],
                'total_pages': total_pages,
                'total_chars': total_chars,
                'chars_per_page': round(chars_per_page, 1),
                'reason': reason
            })
            stats['flagged_for_ocr'].append(str(doc_id))
    
    # Log findings
    logger.info("=" * 60)
    logger.info("INGESTION AUDIT RESULTS")
    logger.info("=" * 60)
    logger.info(f"Total completed documents: {stats['total_completed']}")
    logger.info(f"Valid documents: {stats['valid']}")
    logger.info(f"Hollow - No pages/text: {stats['hollow_no_pages']}")
    logger.info(f"Hollow - Low total chars (<{MIN_TOTAL_CHARS}): {stats['hollow_low_chars']}")
    logger.info(f"Hollow - Low density (<{MIN_CHARS_PER_PAGE} chars/page): {stats['hollow_low_density']}")
    logger.info(f"Total hollow documents: {len(hollow_docs)}")
    
    if hollow_docs:
        logger.info("\nHollow PDFs (first 30):")
        for doc in hollow_docs[:30]:
            logger.info(f"  [{doc['reason']}] {doc['case_name']} - {doc['total_pages']}pg, {doc['total_chars']}ch, {doc['chars_per_page']}ch/pg")
    
    # Mark hollow documents if not dry run
    if not dry_run and hollow_docs:
        logger.info("\nMarking hollow documents as INGESTION_FAILED...")
        for doc in hollow_docs:
            cursor.execute("""
                UPDATE documents 
                SET status = 'ingestion_failed',
                    error_message = %s,
                    updated_at = NOW()
                WHERE id = %s::uuid
            """, (f"Hollow PDF: {doc['reason']} - {doc['chars_per_page']} chars/page", doc['id']))
        conn.commit()
        logger.info(f"Marked {len(hollow_docs)} documents as INGESTION_FAILED")
    else:
        logger.info("\n[DRY RUN] No changes made. Run with --apply to mark hollow PDFs.")
    
    cursor.close()
    conn.close()
    
    return stats


def get_text_density_score(document_id):
    """
    Calculate text density score for a document.
    Returns (total_chars, total_pages, chars_per_page)
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            d.total_pages,
            COALESCE(SUM(LENGTH(dp.text)), 0) as total_chars
        FROM documents d
        LEFT JOIN document_pages dp ON d.id = dp.document_id
        WHERE d.id = %s::uuid
        GROUP BY d.id, d.total_pages
    """, (str(document_id),))
    
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not result:
        return 0, 0, 0
    
    total_pages = result['total_pages'] or 0
    total_chars = result['total_chars'] or 0
    chars_per_page = total_chars / total_pages if total_pages > 0 else 0
    
    return total_chars, total_pages, chars_per_page


def validate_ingestion(document_id, total_chars, total_pages):
    """
    Validation gate: Check if ingestion meets quality thresholds.
    Returns (is_valid, reason)
    """
    if total_pages == 0:
        return False, "NO_PAGES"
    
    if total_chars < MIN_TOTAL_CHARS:
        return False, f"LOW_CHARS ({total_chars} < {MIN_TOTAL_CHARS})"
    
    chars_per_page = total_chars / total_pages
    if chars_per_page < MIN_CHARS_PER_PAGE:
        return False, f"LOW_DENSITY ({chars_per_page:.0f} < {MIN_CHARS_PER_PAGE} chars/page)"
    
    return True, "VALID"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Audit database for hollow PDFs")
    parser.add_argument("--apply", action="store_true", help="Actually mark hollow PDFs (default is dry run)")
    args = parser.parse_args()
    
    audit_hollow_pdfs(dry_run=not args.apply)
