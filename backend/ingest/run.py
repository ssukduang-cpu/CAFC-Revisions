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
WEB_SEARCH_MAX_RETRIES = 1  # Faster timeout for web search flow
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
    initial_backoff: float = INITIAL_BACKOFF,
    try_original_first: bool = True
) -> Dict[str, Any]:
    last_error = None
    actual_url = url
    tried_courtlistener = False
    tried_original = False
    
    # Strategy: If we have a non-CourtListener URL (e.g., CAFC), try it first
    # This helps avoid 202 "PDF generation pending" from CourtListener
    is_original_cafc_url = url and 'cafc.uscourts.gov' in url
    
    if try_original_first and is_original_cafc_url:
        # Start with original CAFC URL - CourtListener will be fallback
        actual_url = url
        tried_original = True
        log(f"Trying CAFC URL first: {url[:80]}...")
    elif cluster_id and not is_original_cafc_url:
        # For CourtListener /pdf/ URLs, get the storage URL to avoid 202
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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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
                
                # CourtListener returns 202 when PDF is being generated
                # If we haven't tried the original CAFC URL yet, try that first
                if status_code == 202:
                    if is_original_cafc_url and not tried_original:
                        log(f"CourtListener 202, falling back to CAFC URL: {url[:80]}...")
                        actual_url = url
                        tried_original = True
                        # Remove CourtListener auth for CAFC
                        headers.pop('Authorization', None)
                        continue
                    # Tried both, return pending
                    return {
                        "success": False,
                        "attempts": attempt + 1,
                        "error": "PDF_GENERATION_PENDING_202",
                        "retry_later": True
                    }
                
                # On 4xx errors from CAFC, try CourtListener as fallback if we have cluster_id
                if status_code >= 400 and not tried_courtlistener and cluster_id:
                    log(f"URL returned {status_code}, trying CourtListener for cluster {cluster_id}...")
                    cl_url = await get_actual_pdf_url(str(cluster_id))
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

def cleanup_hyphenated_text(text: str) -> str:
    """
    Fix hyphenated word breaks that occur at line endings in PDFs.
    E.g., "Al- ice" → "Alice", "obvious- ness" → "obviousness"
    
    This is critical for legal text where terms like "Alice", "obviousness",
    "inequitable" are frequently broken across lines in PDFs.
    """
    import re
    # Pattern: word fragment + hyphen + optional whitespace/newline + word fragment
    # This handles cases like "Al-\nice", "Al- ice", "ob-\nvious-\nness"
    pattern = r'(\w+)-\s*\n?\s*(\w+)'
    
    def rejoin_word(match):
        part1 = match.group(1)
        part2 = match.group(2)
        # Only rejoin if it looks like a broken word (lowercase continuation)
        # or if it's a known legal term pattern
        if part2[0].islower() or len(part1) <= 3:
            return part1 + part2
        return match.group(0)  # Keep original if it doesn't look like a word break
    
    # Apply multiple times to handle chained breaks like "ob-\nvious-\nness"
    result = text
    for _ in range(3):
        new_result = re.sub(pattern, rejoin_word, result)
        if new_result == result:
            break
        result = new_result
    
    return result

def extract_pages(pdf_path: str) -> Dict[str, Any]:
    """
    Extract text from PDF pages.
    Returns dict with 'pages' list and 'ocr_required' flag if text is too sparse.
    Applies hyphenation cleanup to fix broken words.
    """
    reader = PdfReader(pdf_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        # Clean up hyphenated word breaks before storing
        text = cleanup_hyphenated_text(text)
        pages.append(text)
    
    # Check if this is a scanned/image PDF (less than 100 chars total)
    total_text = "".join(pages).strip()
    if len(total_text) < 100:
        log(f"WARNING: Scanned/image PDF detected - only {len(total_text)} chars extracted. OCR required.")
        return {"pages": pages, "ocr_required": True, "total_chars": len(total_text)}
    
    return {"pages": pages, "ocr_required": False, "total_chars": len(total_text)}

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

async def ingest_document(doc: Dict, fast_mode: bool = False) -> Dict[str, Any]:
    doc_id = str(doc["id"])
    pdf_url = doc["pdf_url"]
    case_name = doc.get("case_name", "Unknown")
    cluster_id = doc.get("courtlistener_cluster_id")
    
    log(f"Starting ingestion: {case_name[:50]}")
    
    os.makedirs(PDF_DIR, exist_ok=True)
    pdf_path = os.path.join(PDF_DIR, f"{doc_id}.pdf")
    ingestion_success = False
    file_size = 0
    
    # Use fewer retries in fast_mode (for web search) to avoid timeouts
    retries = WEB_SEARCH_MAX_RETRIES if fast_mode else MAX_RETRIES
    
    try:
        if doc.get("ingested"):
            log(f"Already ingested: {case_name[:50]}")
            ingestion_success = True
            return {"success": True, "status": "already_ingested", "doc_id": doc_id}
        
        db.mark_document_processing(doc_id)
        
        download_result = await download_pdf_with_retry(pdf_url, pdf_path, cluster_id=cluster_id, max_retries=retries)
        
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
            ingestion_success = True
            return {"success": True, "status": "unchanged", "doc_id": doc_id}
        
        file_size = download_result.get('size_bytes', 0)
        log(f"Extracting text from {file_size} bytes...")
        extraction_result = extract_pages(pdf_path)
        pages = extraction_result["pages"]
        num_pages = len(pages)
        log(f"Extracted {num_pages} pages")
        
        # Check for scanned/image PDFs that need OCR
        if extraction_result["ocr_required"]:
            db.mark_document_error(doc_id, f"OCR required: only {extraction_result['total_chars']} chars extracted")
            return {
                "success": False,
                "status": "ocr_required",
                "doc_id": doc_id,
                "num_pages": num_pages,
                "total_chars": extraction_result["total_chars"],
                "error": "Scanned/image PDF - OCR required"
            }
        
        chunks = create_chunks(pages)
        log(f"Created {len(chunks)} chunks")
        
        db.ingest_document_atomic(doc_id, pages, chunks, sha256, file_size)
        
        log(f"Completed: {case_name[:50]} ({num_pages} pages, {len(chunks)} chunks)")
        ingestion_success = True
        
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
        # Keep PDFs after successful ingestion for "View in app" functionality
        # Only delete PDFs that failed ingestion to save disk space
        if not ingestion_success and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except:
                pass


async def ingest_document_from_url(
    pdf_url: str,
    case_name: str,
    cluster_id: Optional[int] = None,
    courtlistener_url: Optional[str] = None,
    source: str = "web_search",
    fast_mode: bool = True
) -> Dict[str, Any]:
    """
    Create a new document record and ingest it from a URL.
    Used by the web search pipeline to automatically ingest discovered cases.
    
    Args:
        pdf_url: URL to download the PDF from
        case_name: Case name (e.g., "H-W Technologies v. Overstock.com")
        cluster_id: CourtListener cluster ID for deduplication
        courtlistener_url: URL to the CourtListener opinion page
        source: Source of the document (e.g., "web_search", "manual")
        
    Returns:
        Dict with success status and document_id if successful
    """
    db.init_db()
    
    if cluster_id:
        existing = db.check_document_exists_by_cluster_id(cluster_id)
        if existing:
            if existing.get("ingested"):
                return {
                    "success": True,
                    "status": "already_exists",
                    "document_id": existing.get("id"),
                    "case_name": existing.get("case_name")
                }
            else:
                doc = db.get_document(existing.get("id"))
                if doc:
                    result = await ingest_document(doc)
                    result["document_id"] = existing.get("id")
                    return result
    
    doc_data = {
        "pdf_url": pdf_url,
        "case_name": case_name,
        "courtlistener_cluster_id": cluster_id,
        "courtlistener_url": courtlistener_url,
        "status": "Precedential",
        "document_type": "OPINION",
        "origin": source
    }
    
    try:
        doc_id = db.upsert_document(doc_data)
        log(f"Created document record for: {case_name[:50]} (id={doc_id})")
        
        doc = db.get_document(doc_id)
        if not doc:
            return {"success": False, "error": "Failed to retrieve created document"}
        
        result = await ingest_document(doc, fast_mode=fast_mode)
        result["document_id"] = doc_id
        
        return result
        
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        log(f"Error ingesting from URL: {error_msg}")
        traceback.print_exc()
        return {"success": False, "error": error_msg}


async def run_batch_ingest(
    limit: int = 10,
    concurrency: int = 2,
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
    
    # Use semaphore to limit concurrent processing (2 is safe for Replit memory limits)
    semaphore = asyncio.Semaphore(concurrency)
    
    async def process_with_semaphore(doc: Dict) -> Dict[str, Any]:
        async with semaphore:
            result = await ingest_document(doc)
            # Small delay between completions to avoid overwhelming the database
            await asyncio.sleep(0.2)
            return result
    
    # Create tasks for all documents and run them concurrently with semaphore limiting
    tasks = [process_with_semaphore(doc) for doc in documents]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results, handling any exceptions that were caught
    succeeded = 0
    failed = 0
    processed_results = []
    
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            # Handle any unhandled exceptions from gather
            error_msg = f"{type(result).__name__}: {str(result)}"
            log(f"Task exception: {error_msg}")
            processed_results.append({
                "success": False,
                "status": "exception",
                "doc_id": str(documents[i]["id"]),
                "error": error_msg
            })
            failed += 1
        else:
            processed_results.append(result)
            if result.get("success"):
                succeeded += 1
            else:
                failed += 1
    
    log(f"\nBatch complete: {succeeded} succeeded, {failed} failed")
    
    return {
        "success": failed == 0,
        "message": f"Batch complete: {succeeded} succeeded, {failed} failed",
        "processed": len(documents),
        "succeeded": succeeded,
        "failed": failed,
        "results": processed_results
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
