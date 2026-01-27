#!/usr/bin/env python3
"""
Recovery Script for Failed Documents

Uses Iowa manifest to find correct CAFC PDF URLs and re-ingests failed documents.
"""

import os
import sys
import json
import logging
import psycopg2
import requests
import fitz  # PyMuPDF
from typing import List, Dict, Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
MIN_CHARS_PER_PAGE = 200
MIN_TOTAL_CHARS = 500
CHUNK_SIZE_PAGES = 2

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def load_iowa_manifest() -> Dict[str, Dict]:
    """Load Iowa manifest into lookup by appeal number."""
    iowa_lookup = {}
    manifest_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'manifest_iowa.ndjson')
    
    with open(manifest_path, 'r') as f:
        for line in f:
            case = json.loads(line)
            appeal = case.get('appeal_number', '').replace('No. ', '').strip()
            if appeal:
                iowa_lookup[appeal] = case
    
    log.info(f"Loaded {len(iowa_lookup)} cases from Iowa manifest")
    return iowa_lookup

def get_courtlistener_pdf_url(case_name: str, appeal_number: str) -> Optional[str]:
    """Look up PDF URL from CourtListener API."""
    api_key = os.environ.get('COURTLISTENER_API_TOKEN')
    headers = {"Authorization": f"Token {api_key}"} if api_key else {}
    
    try:
        # Search for the case
        search_url = "https://www.courtlistener.com/api/rest/v4/search/"
        params = {
            "q": case_name[:100],
            "court": "cafc",
            "type": "o"
        }
        
        response = requests.get(search_url, params=params, headers=headers, timeout=30)
        if response.status_code != 200:
            return None
        
        data = response.json()
        if not data.get('results'):
            return None
        
        # Get cluster ID from first result
        cluster_id = data['results'][0].get('cluster_id')
        if not cluster_id:
            return None
        
        # Get opinions from cluster to get local_path
        opinions_url = "https://www.courtlistener.com/api/rest/v4/opinions/"
        params = {"cluster": cluster_id}
        response = requests.get(opinions_url, params=params, headers=headers, timeout=30)
        
        if response.status_code != 200:
            return None
        
        data = response.json()
        for op in data.get('results', []):
            local_path = op.get('local_path')
            if local_path:
                return f"https://storage.courtlistener.com/{local_path}"
        
        return None
    except Exception as e:
        log.debug(f"CourtListener API error: {e}")
        return None

def cleanup_hyphenated_text(text: str) -> str:
    import re
    return re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)

def download_pdf(url: str, timeout: int = 30) -> Optional[bytes]:
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            return response.content
        log.debug(f"Failed to download: HTTP {response.status_code}")
        return None
    except Exception as e:
        log.debug(f"Error downloading: {e}")
        return None

def extract_pages(pdf_bytes: bytes) -> Dict[str, Any]:
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
        
        is_hollow = False
        if page_count > 1 and chars_per_page < MIN_CHARS_PER_PAGE:
            is_hollow = True
        elif total_chars < MIN_TOTAL_CHARS:
            is_hollow = True
        
        return {
            "pages": pages,
            "total_chars": total_chars,
            "page_count": page_count,
            "chars_per_page": chars_per_page,
            "is_hollow": is_hollow
        }
    except Exception as e:
        log.error(f"Error extracting pages: {e}")
        return {"pages": [], "total_chars": 0, "page_count": 0, "is_hollow": True}

def create_chunks(pages: List[str], chunk_size: int = CHUNK_SIZE_PAGES) -> List[Dict]:
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
    if not chunks:
        return 0
    
    cursor = conn.cursor()
    cursor.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_id,))
    
    for chunk in chunks:
        cursor.execute("""
            INSERT INTO document_chunks (document_id, chunk_index, page_start, page_end, text)
            VALUES (%s, %s, %s, %s, %s)
        """, (document_id, chunk['chunk_index'], chunk['page_start'], chunk['page_end'], chunk['text']))
    
    conn.commit()
    cursor.close()
    return len(chunks)

def update_document(conn, document_id: str, status: str, pdf_url: str = None, 
                   total_pages: int = None, error_msg: str = None):
    cursor = conn.cursor()
    
    updates = ["status = %s", "updated_at = NOW()"]
    params = [status]
    
    if pdf_url:
        updates.append("pdf_url = %s")
        params.append(pdf_url)
    if total_pages:
        updates.append("total_pages = %s")
        params.append(total_pages)
    if error_msg:
        updates.append("error_message = %s")
        params.append(error_msg)
    else:
        updates.append("error_message = NULL")
    
    params.append(document_id)
    
    cursor.execute(f"UPDATE documents SET {', '.join(updates)} WHERE id = %s", params)
    conn.commit()
    cursor.close()

def check_url_exists(conn, pdf_url: str) -> bool:
    """Check if URL already exists in database."""
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM documents WHERE pdf_url = %s", (pdf_url,))
    exists = cursor.fetchone() is not None
    cursor.close()
    return exists

def recover_failed_documents(limit: int = None, dry_run: bool = False):
    """Main recovery function using CourtListener API."""
    conn = get_db_connection()
    
    # Get failed documents
    cursor = conn.cursor()
    query = """
        SELECT id, case_name, appeal_number, pdf_url
        FROM documents
        WHERE status = 'failed'
        ORDER BY release_date DESC NULLS LAST
    """
    if limit:
        query += f" LIMIT {limit}"
    
    cursor.execute(query)
    failed_docs = cursor.fetchall()
    cursor.close()
    
    log.info(f"Found {len(failed_docs)} failed documents to recover")
    
    recovered = 0
    still_failed = 0
    hollow = 0
    duplicates = 0
    
    for doc_id, case_name, appeal_num, old_url in failed_docs:
        log.info(f"Recovering: {case_name[:50]}")
        
        # Try CourtListener API lookup
        new_url = get_courtlistener_pdf_url(case_name, appeal_num)
        
        if not new_url:
            log.warning(f"  -> No CourtListener entry found")
            still_failed += 1
            continue
        
        log.info(f"  URL: {new_url}")
        
        # Check if URL already exists (duplicate)
        if check_url_exists(conn, new_url):
            log.info(f"  -> URL already exists, marking as duplicate")
            update_document(conn, doc_id, 'duplicate', None, None, 'Duplicate of existing document')
            duplicates += 1
            continue
        
        if dry_run:
            recovered += 1
            continue
        
        # Download PDF
        pdf_bytes = download_pdf(new_url)
        if not pdf_bytes:
            log.warning(f"  -> Still failed to download")
            still_failed += 1
            continue
        
        # Extract and validate
        result = extract_pages(pdf_bytes)
        
        if result['is_hollow']:
            log.warning(f"  -> Hollow PDF ({result['chars_per_page']:.0f} chars/page)")
            hollow += 1
            update_document(conn, doc_id, 'hollow', new_url, result['page_count'], 
                           f"Hollow PDF: {result['chars_per_page']:.0f} chars/page - needs OCR")
            continue
        
        # Create chunks
        chunks = create_chunks(result['pages'])
        if not chunks:
            log.warning(f"  -> No valid chunks created")
            still_failed += 1
            continue
        
        # Insert chunks and update status
        chunk_count = insert_chunks(conn, doc_id, chunks)
        update_document(conn, doc_id, 'completed', new_url, result['page_count'])
        
        log.info(f"  -> Recovered: {chunk_count} chunks, {result['page_count']} pages")
        recovered += 1
    
    conn.close()
    
    log.info(f"\n{'='*60}")
    log.info(f"Recovery Summary:")
    log.info(f"  Recovered: {recovered}")
    log.info(f"  Duplicates: {duplicates}")
    log.info(f"  Hollow (need OCR): {hollow}")
    log.info(f"  Still failed: {still_failed}")
    log.info(f"{'='*60}")
    
    return recovered, duplicates, hollow, still_failed

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Recover failed documents using Iowa manifest")
    parser.add_argument("--limit", type=int, help="Limit number of documents to process")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually download/ingest")
    args = parser.parse_args()
    
    recover_failed_documents(limit=args.limit, dry_run=args.dry_run)
