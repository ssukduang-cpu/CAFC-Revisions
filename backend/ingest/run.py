#!/usr/bin/env python3
"""
Resumable Python ingester for CAFC precedential opinions.
Downloads PDFs, extracts per-page text, creates chunks, and indexes for FTS.
"""
import argparse
import asyncio
import hashlib
import os
import sys
import time
import traceback
from typing import Dict, Any, List, Optional

import httpx
from pypdf import PdfReader

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backend import db_postgres as db

PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "pdfs")

MAX_RETRIES = 3
INITIAL_BACKOFF = 2.0
MIN_TEXT_LENGTH = 50
CHUNK_SIZE_PAGES = 2

def log(message: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", file=sys.stderr)

async def get_actual_pdf_url(cluster_id: str) -> Optional[str]:
    """
    Fetch the actual PDF download URL from CourtListener API.
    Prioritizes local_path (CourtListener's storage) over download_url (original source).
    """
    api_token = os.environ.get('COURTLISTENER_API_TOKEN')
    if not api_token:
        return None
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                'Authorization': f'Token {api_token}',
                'User-Agent': 'Federal-Circuit-AI-Research/1.0'
            }
            # Fetch opinions for this cluster
            url = f"https://www.courtlistener.com/api/rest/v4/opinions/?cluster={cluster_id}"
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('results'):
                    opinion = data['results'][0]
                    # Prioritize local_path - this is CourtListener's cached copy
                    local_path = opinion.get('local_path')
                    if local_path:
                        return f"https://storage.courtlistener.com/{local_path}"
                    # Fallback to download_url (original source)
                    download_url = opinion.get('download_url')
                    if download_url:
                        return download_url
    except Exception as e:
        log(f"Error fetching actual PDF URL for cluster {cluster_id}: {e}")
    
    return None

async def download_pdf_with_retry(
    url: str,
    pdf_path: str,
    cluster_id: Optional[str] = None,
    max_retries: int = MAX_RETRIES,
    initial_backoff: float = INITIAL_BACKOFF
) -> Dict[str, Any]:
    last_error = None
    actual_url = url
    tried_courtlistener = False
    
    # If we have a cluster_id, always try to get the storage URL first
    # This avoids the 202 "PDF generation in progress" from /pdf/ endpoint
    if cluster_id:
        real_url = await get_actual_pdf_url(str(cluster_id))
        if real_url:
            log(f"Using CourtListener storage URL for cluster {cluster_id}")
            actual_url = real_url
            tried_courtlistener = True
    # Fallback: For CourtListener /pdf/ URLs without cluster_id, extract it from URL
    elif 'courtlistener.com/pdf/' in url:
        import re
        match = re.search(r'/pdf/(\d+)/', url)
        if match:
            extracted_cluster_id = match.group(1)
            real_url = await get_actual_pdf_url(extracted_cluster_id)
            if real_url:
                log(f"Using actual PDF URL: {real_url}")
                actual_url = real_url
                tried_courtlistener = True
    
    # Add CourtListener authentication if downloading from their domain
    headers = {
        'User-Agent': 'Federal-Circuit-AI-Research/1.0 (legal research tool)',
    }
    if 'courtlistener.com' in actual_url:
        api_token = os.environ.get('COURTLISTENER_API_TOKEN')
        if api_token:
            headers['Authorization'] = f'Token {api_token}'
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                response = await client.get(actual_url, headers=headers)
                status_code = response.status_code
                
                # CourtListener returns 202 when PDF is being generated - skip and retry later
                if status_code == 202:
                    return {
                        "success": False,
                        "attempts": attempt + 1,
                        "error": "PDF_GENERATION_PENDING",
                        "retry_later": True
                    }
                
                # On 4xx errors from CAFC, try CourtListener as fallback if we have cluster_id
                if status_code >= 400 and cluster_id and not tried_courtlistener:
                    log(f"CAFC {status_code}, trying CourtListener for cluster {cluster_id}...")
                    cl_url = await get_actual_pdf_url(cluster_id)
                    if cl_url:
                        actual_url = cl_url
                        tried_courtlistener = True
                        # Update headers for CourtListener
                        api_token = os.environ.get('COURTLISTENER_API_TOKEN')
                        if api_token:
                            headers['Authorization'] = f'Token {api_token}'
                        log(f"Using CourtListener URL: {cl_url}")
                        continue  # Retry with new URL
                
                response.raise_for_status()
                
                content_length = len(response.content)
                if content_length < 1000:
                    raise ValueError(f"PDF too small ({content_length} bytes)")
                
                with open(pdf_path, "wb") as f:
                    f.write(response.content)
                
                sha256 = hashlib.sha256(response.content).hexdigest()
                
                return {
                    "success": True,
                    "attempts": attempt + 1,
                    "size_bytes": content_length,
                    "sha256": sha256
                }
                
        except Exception as e:
            last_error = str(e)
            
            if attempt < max_retries - 1:
                backoff = initial_backoff * (2 ** attempt)
                log(f"Attempt {attempt + 1} failed: {e}. Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
    
    return {
        "success": False,
        "attempts": max_retries,
        "error": last_error
    }

def extract_pages(pdf_path: str) -> List[str]:
    reader = PdfReader(pdf_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
    return pages

def create_chunks(pages: List[str], chunk_size: int = CHUNK_SIZE_PAGES) -> List[Dict]:
    chunks = []
    chunk_index = 0
    
    for i in range(0, len(pages), chunk_size):
        page_start = i + 1
        page_end = min(i + chunk_size, len(pages))
        
        chunk_pages = pages[i:i + chunk_size]
        chunk_text = "\n\n".join(chunk_pages)
        
        if len(chunk_text.strip()) > MIN_TEXT_LENGTH:
            chunks.append({
                "chunk_index": chunk_index,
                "page_start": page_start,
                "page_end": page_end,
                "text": chunk_text
            })
            chunk_index += 1
    
    return chunks

async def ingest_document(doc: Dict) -> Dict[str, Any]:
    doc_id = str(doc["id"])
    pdf_url = doc["pdf_url"]
    case_name = doc.get("case_name", "Unknown")
    cluster_id = doc.get("courtlistener_cluster_id")
    
    log(f"Starting ingestion: {case_name[:50]}")
    
    os.makedirs(PDF_DIR, exist_ok=True)
    pdf_path = os.path.join(PDF_DIR, f"{doc_id}.pdf")
    
    try:
        if doc.get("ingested"):
            log(f"Already ingested: {case_name[:50]}")
            return {"success": True, "status": "already_ingested", "doc_id": doc_id}
        
        download_result = await download_pdf_with_retry(pdf_url, pdf_path, cluster_id=cluster_id)
        
        if not download_result["success"]:
            error_msg = download_result.get('error', 'Unknown')
            # For 202 (PDF generation pending), don't mark as error - just skip for now
            if download_result.get("retry_later"):
                log(f"Skipping (PDF pending): {case_name[:50]}")
                return {"success": False, "status": "retry_later", "doc_id": doc_id, "error": error_msg}
            db.mark_document_error(doc_id, f"Download failed: {error_msg}")
            return {"success": False, "status": "download_failed", "doc_id": doc_id, "error": error_msg}
        
        sha256 = download_result.get("sha256")
        
        if doc.get("pdf_sha256") == sha256 and doc.get("ingested"):
            log(f"PDF unchanged, skipping: {case_name[:50]}")
            return {"success": True, "status": "unchanged", "doc_id": doc_id}
        
        log(f"Extracting text from {download_result['size_bytes']} bytes...")
        pages = extract_pages(pdf_path)
        num_pages = len(pages)
        log(f"Extracted {num_pages} pages")
        
        chunks = create_chunks(pages)
        log(f"Created {len(chunks)} chunks")
        
        db.ingest_document_atomic(doc_id, pages, chunks, sha256)
        
        log(f"Completed: {case_name[:50]} ({num_pages} pages, {len(chunks)} chunks)")
        
        return {
            "success": True,
            "status": "completed",
            "doc_id": doc_id,
            "num_pages": num_pages,
            "num_chunks": len(chunks),
            "sha256": sha256
        }
        
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        traceback.print_exc()
        db.mark_document_error(doc_id, error_msg)
        return {"success": False, "status": "error", "doc_id": doc_id, "error": error_msg}
    
    finally:
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except:
                pass

async def run_batch_ingest(
    limit: int = 10,
    concurrency: int = 1,
    only_not_ingested: bool = True
) -> Dict[str, Any]:
    db.init_db()
    
    documents = db.get_pending_documents(limit=limit)
    
    if not documents:
        log("No pending documents to ingest")
        return {
            "success": True,
            "message": "No pending documents",
            "processed": 0,
            "succeeded": 0,
            "failed": 0
        }
    
    log(f"Found {len(documents)} documents to ingest")
    
    results = []
    succeeded = 0
    failed = 0
    
    for doc in documents:
        result = await ingest_document(doc)
        results.append(result)
        
        if result.get("success"):
            succeeded += 1
        else:
            failed += 1
        
        await asyncio.sleep(0.5)
    
    log(f"\nBatch complete: {succeeded} succeeded, {failed} failed")
    
    return {
        "success": failed == 0,
        "message": f"Batch complete: {succeeded} succeeded, {failed} failed",
        "processed": len(documents),
        "succeeded": succeeded,
        "failed": failed,
        "results": results
    }

def main():
    parser = argparse.ArgumentParser(description="CAFC Opinion Ingester")
    parser.add_argument("--mode", choices=["batch", "sync"], default="batch", help="Ingestion mode")
    parser.add_argument("--limit", type=int, default=10, help="Number of documents to process")
    parser.add_argument("--concurrency", type=int, default=1, help="Concurrent downloads (1-4)")
    parser.add_argument("--only-not-ingested", action="store_true", default=True, help="Only process non-ingested docs")
    
    args = parser.parse_args()
    
    result = asyncio.run(run_batch_ingest(
        limit=args.limit,
        concurrency=min(max(args.concurrency, 1), 4),
        only_not_ingested=args.only_not_ingested
    ))
    
    print(f"\nResult: {result['message']}")
    
    if result.get("failed", 0) > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
