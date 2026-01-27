#!/usr/bin/env python3
"""
Batch OCR Recovery Script for Hollow PDFs.

This script:
1. Reads hollow document IDs from failed_ingestion_report or database
2. Re-downloads and processes PDFs with OCR using pytesseract + pdf2image
3. Upserts OCR-extracted text into existing document records
4. Prioritizes the Big 5 landmark cases (Markman, Phillips, Vitronics, Alice, KSR)
5. Marks successfully recovered documents as 'RECOVERED'
"""

import argparse
import asyncio
import os
import sys
import time
import logging
import tempfile
from typing import List, Dict, Any, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.ingest.run import download_pdf_with_retry, cleanup_hyphenated_text

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "pdfs")

BIG_5_LANDMARK_CASES = [
    "Markman",      # Claim construction precedent
    "Phillips",     # Claim construction en banc 
    "Vitronics",    # Intrinsic evidence priority
    "Alice",        # Patent eligibility (§101)
    "KSR"           # Obviousness (§103)
]

MIN_RECOVERED_CHARS = 5000
DPI_FOR_OCR = 300


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def get_hollow_documents(limit: int = 1000, priority_only: bool = False) -> List[Dict]:
    """
    Get list of hollow documents to process.
    Prioritizes Big 5 landmark cases if priority_only=True.
    """
    conn = get_connection()
    cur = conn.cursor()
    
    if priority_only:
        conditions = " OR ".join([f"d.case_name ILIKE '%{case}%'" for case in BIG_5_LANDMARK_CASES])
        query = f"""
            SELECT 
                d.id, d.case_name, d.pdf_url, d.total_pages, d.status,
                d.courtlistener_cluster_id,
                COALESCE(SUM(LENGTH(dp.text)), 0) as total_chars
            FROM documents d
            LEFT JOIN document_pages dp ON d.id = dp.document_id
            WHERE ({conditions})
            GROUP BY d.id
            HAVING COALESCE(SUM(LENGTH(dp.text)), 0) < 1000
            ORDER BY d.case_name
            LIMIT {limit}
        """
    else:
        query = f"""
            SELECT 
                d.id, d.case_name, d.pdf_url, d.total_pages, d.status,
                d.courtlistener_cluster_id,
                COALESCE(SUM(LENGTH(dp.text)), 0) as total_chars
            FROM documents d
            LEFT JOIN document_pages dp ON d.id = dp.document_id
            WHERE d.status IN ('completed', 'ingestion_failed')
            GROUP BY d.id
            HAVING COALESCE(SUM(LENGTH(dp.text)), 0) < 1000
            ORDER BY total_chars ASC
            LIMIT {limit}
        """
    
    cur.execute(query)
    docs = cur.fetchall()
    conn.close()
    
    return [dict(d) for d in docs]


def ocr_pdf_to_pages(pdf_path: str) -> List[str]:
    """
    Convert PDF to images and extract text using OCR.
    Uses hi_res strategy with configurable DPI.
    """
    logger.info(f"Running OCR on: {pdf_path}")
    
    try:
        images = convert_from_path(pdf_path, dpi=DPI_FOR_OCR)
        logger.info(f"Converted {len(images)} pages to images")
        
        pages = []
        for i, img in enumerate(images, 1):
            text = pytesseract.image_to_string(img, lang='eng')
            text = cleanup_hyphenated_text(text)
            pages.append(text)
            logger.debug(f"Page {i}: {len(text)} chars extracted")
        
        return pages
        
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        return []


def upsert_document_pages(doc_id: str, pages: List[str]) -> Dict[str, Any]:
    """
    Upsert OCR-extracted pages into the database.
    Clears existing pages and inserts new ones.
    """
    conn = get_connection()
    cur = conn.cursor()
    
    total_chars = sum(len(p) for p in pages)
    num_pages = len(pages)
    
    try:
        cur.execute("DELETE FROM document_pages WHERE document_id = %s::uuid", (doc_id,))
        cur.execute("DELETE FROM document_chunks WHERE document_id = %s::uuid", (doc_id,))
        
        for page_num, text in enumerate(pages, 1):
            cur.execute("""
                INSERT INTO document_pages (document_id, page_number, text)
                VALUES (%s::uuid, %s, %s)
            """, (doc_id, page_num, text))
        
        chunk_index = 0
        for i in range(0, len(pages), 2):
            page_start = i + 1
            page_end = min(i + 2, len(pages))
            chunk_text = "\n\n".join(pages[i:i + 2])
            
            if len(chunk_text.strip()) > 50:
                cur.execute("""
                    INSERT INTO document_chunks (document_id, chunk_index, page_start, page_end, text)
                    VALUES (%s::uuid, %s, %s, %s, %s)
                """, (doc_id, chunk_index, page_start, page_end, chunk_text))
                chunk_index += 1
        
        status = 'recovered' if total_chars >= MIN_RECOVERED_CHARS else 'ocr_partial'
        cur.execute("""
            UPDATE documents 
            SET total_pages = %s,
                status = %s,
                updated_at = NOW()
            WHERE id = %s::uuid
        """, (num_pages, status, doc_id))
        
        conn.commit()
        logger.info(f"Upserted {num_pages} pages, {total_chars} chars - Status: {status}")
        
        return {
            'success': True,
            'pages': num_pages,
            'chars': total_chars,
            'status': status
        }
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Database upsert failed: {e}")
        return {'success': False, 'error': str(e)}
        
    finally:
        conn.close()


async def recover_document(doc: Dict, force_redownload: bool = False) -> Dict[str, Any]:
    """
    Attempt to recover a hollow document using OCR.
    """
    doc_id = str(doc['id'])
    case_name = doc.get('case_name', 'Unknown')[:60]
    pdf_url = doc.get('pdf_url')
    cluster_id = doc.get('courtlistener_cluster_id')
    
    logger.info(f"Processing: {case_name}")
    
    os.makedirs(PDF_DIR, exist_ok=True)
    pdf_path = os.path.join(PDF_DIR, f"{doc_id}.pdf")
    
    need_download = force_redownload or not os.path.exists(pdf_path)
    
    if need_download and pdf_url:
        download_result = await download_pdf_with_retry(
            pdf_url, pdf_path, 
            cluster_id=cluster_id,
            max_retries=2
        )
        if not download_result.get('success'):
            logger.warning(f"Download failed: {download_result.get('error')}")
            return {'success': False, 'error': 'download_failed', 'doc_id': doc_id}
    
    if not os.path.exists(pdf_path):
        logger.warning(f"PDF not found: {pdf_path}")
        return {'success': False, 'error': 'pdf_not_found', 'doc_id': doc_id}
    
    pages = ocr_pdf_to_pages(pdf_path)
    
    if not pages:
        return {'success': False, 'error': 'ocr_failed', 'doc_id': doc_id}
    
    total_chars = sum(len(p) for p in pages)
    
    if total_chars < 100:
        logger.warning(f"OCR extracted very little text: {total_chars} chars")
        return {
            'success': False, 
            'error': 'insufficient_ocr_text', 
            'doc_id': doc_id,
            'chars': total_chars
        }
    
    result = upsert_document_pages(doc_id, pages)
    result['doc_id'] = doc_id
    result['case_name'] = case_name
    
    return result


async def batch_recover(
    limit: int = 10,
    priority_only: bool = True,
    force_redownload: bool = False
) -> Dict[str, Any]:
    """
    Batch recover hollow documents.
    """
    logger.info("=" * 60)
    logger.info("BATCH OCR RECOVERY")
    logger.info("=" * 60)
    
    docs = get_hollow_documents(limit=limit, priority_only=priority_only)
    logger.info(f"Found {len(docs)} hollow documents to process")
    
    stats = {
        'total': len(docs),
        'recovered': 0,
        'partial': 0,
        'failed': 0,
        'results': []
    }
    
    for doc in docs:
        result = await recover_document(doc, force_redownload=force_redownload)
        stats['results'].append(result)
        
        if result.get('success'):
            if result.get('status') == 'recovered':
                stats['recovered'] += 1
            else:
                stats['partial'] += 1
        else:
            stats['failed'] += 1
        
        await asyncio.sleep(0.5)
    
    logger.info("=" * 60)
    logger.info("RECOVERY COMPLETE")
    logger.info(f"Recovered: {stats['recovered']}")
    logger.info(f"Partial: {stats['partial']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info("=" * 60)
    
    return stats


def verify_recovery(doc_id: str) -> Dict[str, Any]:
    """
    Verify a document's recovery status with density check.
    """
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT 
            d.id, d.case_name, d.total_pages, d.status,
            COALESCE(SUM(LENGTH(dp.text)), 0) as total_chars
        FROM documents d
        LEFT JOIN document_pages dp ON d.id = dp.document_id
        WHERE d.id = %s::uuid
        GROUP BY d.id
    """, (doc_id,))
    
    result = cur.fetchone()
    conn.close()
    
    if not result:
        return {'found': False}
    
    total_chars = result['total_chars'] or 0
    total_pages = result['total_pages'] or 0
    chars_per_page = total_chars / total_pages if total_pages > 0 else 0
    
    is_recovered = total_chars >= MIN_RECOVERED_CHARS
    
    return {
        'found': True,
        'doc_id': str(result['id']),
        'case_name': result['case_name'],
        'status': result['status'],
        'total_chars': total_chars,
        'total_pages': total_pages,
        'chars_per_page': round(chars_per_page, 1),
        'is_recovered': is_recovered
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch OCR Recovery for Hollow PDFs")
    parser.add_argument("--limit", type=int, default=10, help="Maximum documents to process")
    parser.add_argument("--priority-only", action="store_true", default=True,
                        help="Only process Big 5 landmark cases first")
    parser.add_argument("--all", action="store_true", help="Process all hollow documents")
    parser.add_argument("--force-redownload", action="store_true", 
                        help="Force re-download of PDFs even if they exist")
    parser.add_argument("--verify", type=str, help="Verify recovery status for a document ID")
    
    args = parser.parse_args()
    
    if args.verify:
        result = verify_recovery(args.verify)
        print(f"Verification: {result}")
    else:
        priority_only = not args.all
        asyncio.run(batch_recover(
            limit=args.limit,
            priority_only=priority_only,
            force_redownload=args.force_redownload
        ))
