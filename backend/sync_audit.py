#!/usr/bin/env python3
"""
Global Indexing Sync & Audit Script

Finds documents marked as 'completed' or 'pending' that have ZERO chunks in the database,
and attempts to re-index them using the existing ingestion pipeline.
"""

import os
import sys
import logging
import psycopg2
import requests
import tempfile
import fitz  # PyMuPDF
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# Database connection
DATABASE_URL = os.environ.get("DATABASE_URL")

# Constants
MIN_CHARS_PER_PAGE = 200  # Hollow PDF validation gate
MIN_TOTAL_CHARS = 500
CHUNK_SIZE_PAGES = 2

def get_db_connection():
    """Get database connection."""
    return psycopg2.connect(DATABASE_URL)

def cleanup_hyphenated_text(text: str) -> str:
    """Clean up hyphenated words that are split across lines."""
    import re
    return re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)

def get_zero_chunk_documents(conn, limit: int = 100, priority_cases: Optional[List[str]] = None) -> List[Dict]:
    """
    Find all documents that have zero chunks but are marked as completed.
    Priority cases are returned first.
    """
    cursor = conn.cursor()
    
    query = """
    SELECT 
        d.id,
        d.case_name,
        d.pdf_url,
        d.file_path,
        d.status,
        d.release_date,
        d.appeal_number,
        COALESCE(c.chunk_count, 0) as chunk_count
    FROM documents d
    LEFT JOIN (
        SELECT document_id, COUNT(*) as chunk_count 
        FROM document_chunks 
        GROUP BY document_id
    ) c ON d.id = c.document_id
    WHERE COALESCE(c.chunk_count, 0) = 0
      AND d.status NOT IN ('failed', 'duplicate')
    ORDER BY 
        CASE WHEN d.case_name ILIKE ANY(%s) THEN 0 ELSE 1 END,
        d.release_date DESC NULLS LAST
    LIMIT %s
    """
    
    priority_patterns = priority_cases or ['%Raytheon%', '%Honeywell%']
    cursor.execute(query, (priority_patterns, limit))
    
    columns = ['id', 'case_name', 'pdf_url', 'file_path', 'status', 'release_date', 'appeal_number', 'chunk_count']
    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    cursor.close()
    
    return results

def get_total_zero_chunk_count(conn) -> int:
    """Get total count of documents with zero chunks."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*)
        FROM documents d
        LEFT JOIN (
            SELECT document_id, COUNT(*) as chunk_count 
            FROM document_chunks 
            GROUP BY document_id
        ) c ON d.id = c.document_id
        WHERE COALESCE(c.chunk_count, 0) = 0
          AND d.status NOT IN ('failed', 'duplicate')
    """)
    count = cursor.fetchone()[0]
    cursor.close()
    return count

def download_pdf(url: str, timeout: int = 30) -> Optional[bytes]:
    """Download PDF from URL."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            return response.content
        log.debug(f"Failed to download PDF: HTTP {response.status_code}")
        return None
    except Exception as e:
        log.debug(f"Error downloading PDF: {e}")
        return None

def construct_cafc_url(appeal_number: str, release_date) -> Optional[str]:
    """Construct a CAFC.gov URL from appeal number and release date."""
    if not appeal_number:
        return None
    
    # Clean up appeal number (remove spaces, normalize)
    appeal_clean = appeal_number.strip().replace(' ', '')
    
    if release_date:
        # Format: https://cafc.uscourts.gov/opinions-orders/XX-XXXX.OPINION.M-D-YYYY_XXXXXXX.pdf
        # We don't know the random suffix, so try common patterns
        date_str = release_date.strftime("%-m-%-d-%Y") if hasattr(release_date, 'strftime') else str(release_date)
        
        # Try multiple patterns
        patterns = [
            f"https://cafc.uscourts.gov/opinions-orders/{appeal_clean}.OPINION.{date_str}.pdf",
            f"https://cafc.uscourts.gov/opinions-orders/{appeal_clean}.Opinion.{date_str}.pdf",
            f"http://www.cafc.uscourts.gov/sites/default/files/opinions-orders/{appeal_clean}.OPINION.{date_str}.pdf",
        ]
        return patterns
    
    return None

def download_pdf_with_fallback(pdf_url: str, appeal_number: str, release_date) -> Optional[bytes]:
    """Download PDF, trying CAFC.gov fallback if primary URL fails."""
    # Try primary URL first
    pdf_bytes = download_pdf(pdf_url)
    if pdf_bytes:
        return pdf_bytes
    
    # Try constructing CAFC URL patterns
    cafc_patterns = construct_cafc_url(appeal_number, release_date)
    if cafc_patterns:
        for pattern_url in cafc_patterns:
            pdf_bytes = download_pdf(pattern_url)
            if pdf_bytes:
                log.info(f"  -> Found PDF at CAFC.gov fallback")
                return pdf_bytes
    
    return None

def extract_pages(pdf_bytes: bytes) -> Dict[str, Any]:
    """
    Extract text from PDF pages using PyMuPDF.
    Returns dict with pages list, ocr_required flag, and density stats.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for page in doc:
            text = page.get_text("text") or ""
            text = cleanup_hyphenated_text(text)
            pages.append(text)
        doc.close()
        
        total_chars = sum(len(p) for p in pages)
        page_count = len(pages)
        chars_per_page = total_chars / page_count if page_count > 0 else 0
        
        # Hollow PDF validation gate
        is_hollow = False
        if page_count > 1 and chars_per_page < MIN_CHARS_PER_PAGE:
            is_hollow = True
            log.info(f"Text Density Score: {total_chars} chars, {page_count} pages, {chars_per_page:.0f} chars/page - HOLLOW")
        elif total_chars < MIN_TOTAL_CHARS:
            is_hollow = True
            log.info(f"Text Density Score: {total_chars} chars - TOO SHORT")
        else:
            log.debug(f"Text Density Score: {total_chars} chars, {page_count} pages, {chars_per_page:.0f} chars/page - OK")
        
        return {
            "pages": pages,
            "total_chars": total_chars,
            "page_count": page_count,
            "chars_per_page": chars_per_page,
            "ocr_required": is_hollow,
            "is_hollow": is_hollow
        }
    except Exception as e:
        log.error(f"Error extracting pages: {e}")
        return {"pages": [], "total_chars": 0, "page_count": 0, "ocr_required": True, "is_hollow": True}

def create_chunks(pages: List[str], chunk_size: int = CHUNK_SIZE_PAGES) -> List[Dict]:
    """Create chunks from pages."""
    chunks = []
    chunk_index = 0
    
    for i in range(0, len(pages), chunk_size):
        page_start = i + 1
        page_end = min(i + chunk_size, len(pages))
        
        chunk_pages = pages[i:i + chunk_size]
        chunk_text = "\n\n".join(chunk_pages)
        
        if len(chunk_text.strip()) > 100:
            chunks.append({
                "chunk_index": chunk_index,
                "page_start": page_start,
                "page_end": page_end,
                "text": chunk_text
            })
            chunk_index += 1
    
    return chunks

def insert_chunks(conn, document_id: str, chunks: List[Dict]) -> int:
    """Insert chunks into the database."""
    if not chunks:
        return 0
    
    cursor = conn.cursor()
    
    # First, delete any existing chunks for this document (shouldn't be any, but safety first)
    cursor.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_id,))
    
    # Insert new chunks
    for chunk in chunks:
        cursor.execute("""
            INSERT INTO document_chunks (document_id, chunk_index, page_start, page_end, text)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            document_id,
            chunk['chunk_index'],
            chunk['page_start'],
            chunk['page_end'],
            chunk['text']
        ))
    
    conn.commit()
    cursor.close()
    return len(chunks)

def update_document_status(conn, document_id: str, status: str, error_msg: Optional[str] = None, total_pages: Optional[int] = None):
    """Update document status."""
    cursor = conn.cursor()
    
    if error_msg:
        cursor.execute("""
            UPDATE documents 
            SET status = %s, error_message = %s, updated_at = NOW()
            WHERE id = %s
        """, (status, error_msg, document_id))
    elif total_pages:
        cursor.execute("""
            UPDATE documents 
            SET status = %s, total_pages = %s, updated_at = NOW()
            WHERE id = %s
        """, (status, total_pages, document_id))
    else:
        cursor.execute("""
            UPDATE documents 
            SET status = %s, updated_at = NOW()
            WHERE id = %s
        """, (status, document_id))
    
    conn.commit()
    cursor.close()

def process_document(conn, doc: Dict) -> Tuple[str, Optional[str]]:
    """
    Process a single document: download PDF, extract text, create chunks.
    Returns (status, error_message).
    """
    doc_id = doc['id']
    case_name = doc['case_name']
    pdf_url = doc['pdf_url']
    appeal_number = doc.get('appeal_number')
    release_date = doc.get('release_date')
    
    log.info(f"Processing: {case_name[:60]}...")
    
    if not pdf_url:
        return ('failed', 'No PDF URL available')
    
    # Download PDF with fallback to CAFC.gov
    pdf_bytes = download_pdf_with_fallback(pdf_url, appeal_number, release_date)
    if not pdf_bytes:
        return ('failed', f'PDF not available (tried primary + CAFC fallback)')
    
    # Extract pages
    result = extract_pages(pdf_bytes)
    
    if result['is_hollow']:
        return ('ocr_pending', f"Hollow PDF - {result['total_chars']} chars, needs OCR")
    
    if not result['pages']:
        return ('failed', 'No pages extracted')
    
    # Create chunks
    chunks = create_chunks(result['pages'])
    
    if not chunks:
        return ('failed', 'No valid chunks created')
    
    # Insert chunks
    chunks_inserted = insert_chunks(conn, doc_id, chunks)
    log.info(f"  -> Inserted {chunks_inserted} chunks for {case_name[:40]}")
    
    # Update document
    update_document_status(conn, doc_id, 'completed', total_pages=result['page_count'])
    
    return ('indexed', None)

def run_sync_audit(batch_size: int = 50, priority_only: bool = False):
    """
    Run the global indexing sync & audit.
    """
    log.info("=" * 60)
    log.info("GLOBAL INDEXING SYNC & AUDIT")
    log.info("=" * 60)
    
    conn = get_db_connection()
    
    # Get total count
    total_zero_chunk = get_total_zero_chunk_count(conn)
    log.info(f"Total documents with zero chunks: {total_zero_chunk}")
    
    # Get documents to process
    priority_cases = ['%Raytheon%', '%Honeywell%', '%Phytelligence%', '%Dakocytomation%']
    docs = get_zero_chunk_documents(conn, limit=batch_size, priority_cases=priority_cases)
    
    if not docs:
        log.info("No documents need syncing!")
        conn.close()
        return
    
    log.info(f"Processing {len(docs)} documents...")
    log.info("-" * 60)
    
    # Process each document
    stats = {
        'indexed': 0,
        'failed': 0,
        'ocr_pending': 0
    }
    
    for doc in docs:
        try:
            status, error = process_document(conn, doc)
            stats[status] = stats.get(status, 0) + 1
            
            if error:
                log.warning(f"  -> {status}: {error[:80]}")
                update_document_status(conn, doc['id'], status, error)
                
        except Exception as e:
            log.error(f"Error processing {doc['case_name']}: {e}")
            stats['failed'] += 1
    
    conn.close()
    
    # Final report
    log.info("=" * 60)
    log.info("SYNC REPORT")
    log.info("=" * 60)
    log.info(f"Total Documents with Zero Chunks: {total_zero_chunk}")
    log.info(f"Processed This Run: {len(docs)}")
    log.info(f"Successfully Indexed: {stats['indexed']}")
    log.info(f"Failed/Not Available: {stats['failed']}")
    log.info(f"Needs OCR: {stats['ocr_pending']}")
    log.info(f"Remaining: {total_zero_chunk - len(docs)}")
    log.info("=" * 60)

def check_priority_cases():
    """Check the status of priority cases."""
    log.info("Checking priority cases...")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            d.case_name,
            d.status,
            d.release_date,
            COALESCE(c.chunk_count, 0) as chunk_count
        FROM documents d
        LEFT JOIN (
            SELECT document_id, COUNT(*) as chunk_count 
            FROM document_chunks 
            GROUP BY document_id
        ) c ON d.id = c.document_id
        WHERE d.case_name ILIKE '%raytheon%' 
           OR d.case_name ILIKE '%honeywell%'
           OR d.case_name ILIKE '%phytelligence%'
           OR d.case_name ILIKE '%dakocytomation%'
        ORDER BY d.release_date DESC NULLS LAST
    """)
    
    rows = cursor.fetchall()
    log.info(f"\nPriority Cases Status ({len(rows)} found):")
    log.info("-" * 80)
    for row in rows:
        case_name, status, release_date, chunk_count = row
        date_str = str(release_date) if release_date else "N/A"
        status_indicator = "✓" if chunk_count > 0 else "✗"
        log.info(f"{status_indicator} {case_name[:50]:50} | {date_str:10} | {chunk_count:3} chunks | {status}")
    
    cursor.close()
    conn.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Global Indexing Sync & Audit")
    parser.add_argument('--batch', type=int, default=50, help='Batch size to process')
    parser.add_argument('--priority-only', action='store_true', help='Only check priority cases')
    parser.add_argument('--check', action='store_true', help='Only check status, no processing')
    args = parser.parse_args()
    
    if args.check or args.priority_only:
        check_priority_cases()
    else:
        run_sync_audit(batch_size=args.batch)
