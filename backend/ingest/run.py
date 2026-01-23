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

async def download_pdf_with_retry(
    url: str,
    pdf_path: str,
    max_retries: int = MAX_RETRIES,
    initial_backoff: float = INITIAL_BACKOFF
) -> Dict[str, Any]:
    last_error = None
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True, verify=False) as client:
                response = await client.get(url)
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
    
    log(f"Starting ingestion: {case_name[:50]}")
    
    os.makedirs(PDF_DIR, exist_ok=True)
    pdf_path = os.path.join(PDF_DIR, f"{doc_id}.pdf")
    
    try:
        if doc.get("ingested"):
            log(f"Already ingested: {case_name[:50]}")
            return {"success": True, "status": "already_ingested", "doc_id": doc_id}
        
        download_result = await download_pdf_with_retry(pdf_url, pdf_path)
        
        if not download_result["success"]:
            error_msg = f"Download failed: {download_result.get('error', 'Unknown')}"
            db.mark_document_error(doc_id, error_msg)
            return {"success": False, "status": "download_failed", "doc_id": doc_id, "error": error_msg}
        
        sha256 = download_result.get("sha256")
        
        if doc.get("pdf_sha256") == sha256 and doc.get("ingested"):
            log(f"PDF unchanged, skipping: {case_name[:50]}")
            return {"success": True, "status": "unchanged", "doc_id": doc_id}
        
        log(f"Extracting text from {download_result['size_bytes']} bytes...")
        pages = extract_pages(pdf_path)
        num_pages = len(pages)
        log(f"Extracted {num_pages} pages")
        
        for page_num, text in enumerate(pages, 1):
            db.insert_page(doc_id, page_num, text)
        
        chunks = create_chunks(pages)
        log(f"Created {len(chunks)} chunks")
        
        for chunk in chunks:
            db.insert_chunk(
                doc_id,
                chunk["chunk_index"],
                chunk["page_start"],
                chunk["page_end"],
                chunk["text"]
            )
        
        db.mark_document_ingested(doc_id, sha256)
        
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
