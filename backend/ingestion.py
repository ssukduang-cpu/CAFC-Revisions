import httpx
import os
import asyncio
from pypdf import PdfReader
from typing import Dict, Any, List, Optional
import traceback
import sys
import time

from backend import database as db

PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "pdfs")

MIN_TEXT_LENGTH = 100
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0

def log_memory(label: str):
    import resource
    usage = resource.getrusage(resource.RUSAGE_SELF)
    mem_mb = usage.ru_maxrss / 1024
    print(f"[memory] {label}: {mem_mb:.1f}MB", file=sys.stderr)

def log_progress(opinion_id: str, status: str, details: Optional[Dict] = None):
    log_entry = {
        "opinion_id": opinion_id,
        "status": status,
        "timestamp": time.time(),
        "details": details or {}
    }
    print(f"[ingestion] {opinion_id}: {status} {details or ''}", file=sys.stderr)
    return log_entry

async def download_pdf_with_retry(
    url: str, 
    pdf_path: str, 
    max_retries: int = MAX_RETRIES,
    initial_backoff: float = INITIAL_BACKOFF
) -> Dict[str, Any]:
    last_error = None
    
    # Add CourtListener authentication if downloading from their domain
    headers = {
        'User-Agent': 'Federal-Circuit-AI-Research/1.0 (legal research tool)',
    }
    if 'courtlistener.com' in url:
        api_token = os.environ.get('COURTLISTENER_API_TOKEN')
        if api_token:
            headers['Authorization'] = f'Token {api_token}'
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                
                content_length = len(response.content)
                if content_length < 1000:
                    raise ValueError(f"PDF too small ({content_length} bytes) - likely corrupt or error page")
                
                with open(pdf_path, "wb") as f:
                    f.write(response.content)
                
                return {
                    "success": True,
                    "attempts": attempt + 1,
                    "size_bytes": content_length
                }
                
        except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                backoff = initial_backoff * (2 ** attempt)
                print(f"[retry] Attempt {attempt + 1} failed: {e}. Retrying in {backoff}s...", file=sys.stderr)
                await asyncio.sleep(backoff)
            else:
                print(f"[error] All {max_retries} attempts failed for download", file=sys.stderr)
    
    return {
        "success": False,
        "attempts": max_retries,
        "error": last_error
    }

def validate_extracted_text(pages_text: List[str], opinion_id: str) -> Dict[str, Any]:
    total_chars = sum(len(text) for text in pages_text)
    non_empty_pages = sum(1 for text in pages_text if len(text.strip()) > MIN_TEXT_LENGTH)
    empty_pages = len(pages_text) - non_empty_pages
    
    issues = []
    
    if total_chars < MIN_TEXT_LENGTH:
        issues.append(f"Total text too short: {total_chars} chars")
    
    if len(pages_text) > 0 and non_empty_pages == 0:
        issues.append("All pages are empty - PDF may be image-only or corrupt")
    
    empty_ratio = empty_pages / len(pages_text) if pages_text else 1
    if empty_ratio > 0.5 and len(pages_text) > 2:
        issues.append(f"{empty_pages}/{len(pages_text)} pages are empty ({empty_ratio:.0%})")
    
    return {
        "valid": len(issues) == 0,
        "total_chars": total_chars,
        "total_pages": len(pages_text),
        "non_empty_pages": non_empty_pages,
        "empty_pages": empty_pages,
        "issues": issues
    }

import re

def classify_document(pages_text: List[str], case_name: str) -> str:
    """
    Classify document type based on content and case name.
    Returns appropriate status: 'completed', 'errata', 'summary_affirmance', or 'order'
    """
    if not pages_text:
        return 'completed'
    
    full_text = ' '.join(pages_text)
    text_upper = full_text.upper()
    case_upper = case_name.upper() if case_name else ''
    num_pages = len(pages_text)
    
    if num_pages <= 2:
        if 'ERRATA' in text_upper or 'ERRATUM' in text_upper or '[ERRATA]' in case_upper or 'ERRAT' in case_upper:
            print(f"[classify] Document classified as ERRATA", file=sys.stderr)
            return 'errata'
        
        if 'RULE 36' in text_upper or 'RULE 36' in case_upper:
            print(f"[classify] Document classified as SUMMARY_AFFIRMANCE (Rule 36)", file=sys.stderr)
            return 'summary_affirmance'
        
        if 'SUMMARY AFFIRMANCE' in text_upper:
            print(f"[classify] Document classified as SUMMARY_AFFIRMANCE", file=sys.stderr)
            return 'summary_affirmance'
        
        if re.search(r'AFFIRMED\s*(UNDER|PURSUANT|PER)', text_upper) and num_pages == 1:
            print(f"[classify] Document classified as SUMMARY_AFFIRMANCE (affirmed)", file=sys.stderr)
            return 'summary_affirmance'
        
        if '[ORDER]' in case_upper:
            print(f"[classify] Document classified as ORDER", file=sys.stderr)
            return 'order'
    
    return 'completed'

async def ingest_opinion(opinion_id: str) -> Dict[str, Any]:
    os.makedirs(PDF_DIR, exist_ok=True)
    pdf_path = os.path.join(PDF_DIR, f"{opinion_id}.pdf")
    
    try:
        log_memory("start")
        log_progress(opinion_id, "starting")
        
        opinion = db.get_opinion(opinion_id)
        if not opinion:
            return {"success": False, "error": "Opinion not found", "status": "not_found"}
        
        if opinion["ingested"]:
            log_progress(opinion_id, "skipped", {"reason": "already_ingested"})
            return {"success": True, "message": "Already ingested", "num_pages": 0, "inserted_pages": 0, "status": "already_ingested"}
        
        log_progress(opinion_id, "downloading", {"case_name": opinion['case_name']})
        download_result = await download_pdf_with_retry(opinion["pdf_url"], pdf_path)
        
        if not download_result["success"]:
            log_progress(opinion_id, "download_failed", download_result)
            return {
                "success": False, 
                "error": f"Download failed after {download_result['attempts']} attempts: {download_result.get('error', 'Unknown')}",
                "status": "download_failed",
                "attempts": download_result["attempts"]
            }
        
        log_progress(opinion_id, "downloaded", {"size_bytes": download_result.get("size_bytes", 0), "attempts": download_result["attempts"]})
        log_memory("after-download")
        
        log_progress(opinion_id, "extracting")
        reader = PdfReader(pdf_path)
        num_pages = len(reader.pages)
        
        pages_text = []
        for page_num in range(num_pages):
            page = reader.pages[page_num]
            text = page.extract_text() or ""
            pages_text.append(text)
        
        validation = validate_extracted_text(pages_text, opinion_id)
        log_progress(opinion_id, "validated", validation)
        
        if not validation["valid"]:
            log_progress(opinion_id, "validation_warning", {"issues": validation["issues"]})
        
        log_progress(opinion_id, "inserting", {"pages": num_pages})
        inserted_pages = 0
        page1_preview = ""
        
        for page_num, text in enumerate(pages_text):
            if page_num == 0:
                page1_preview = text[:500].replace("\n", " ").strip()
            
            db.insert_page(opinion_id, page_num + 1, text)
            inserted_pages += 1
            
            if (page_num + 1) % 10 == 0:
                log_memory(f"page-{page_num + 1}")
        
        doc_status = classify_document(pages_text, opinion.get('case_name', ''))
        db.mark_opinion_ingested(opinion_id, status=doc_status)
        log_memory("complete")
        log_progress(opinion_id, doc_status, {
            "num_pages": num_pages,
            "inserted_pages": inserted_pages,
            "total_chars": validation["total_chars"],
            "classification": doc_status
        })
        
        return {
            "success": True,
            "status": doc_status,
            "num_pages": num_pages,
            "inserted_pages": inserted_pages,
            "page1_preview": page1_preview[:200],
            "validation": validation,
            "download_attempts": download_result.get("attempts", 1)
        }
        
    except Exception as e:
        traceback.print_exc()
        log_progress(opinion_id, "error", {"error": str(e)})
        return {"success": False, "error": str(e), "status": "error"}
    
    finally:
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except:
                pass

async def batch_ingest_opinions(
    opinion_ids: Optional[List[str]] = None,
    batch_size: int = 5,
    skip_ingested: bool = True
) -> Dict[str, Any]:
    if opinion_ids is None:
        opinions = db.get_opinions()
        if skip_ingested:
            opinions = [o for o in opinions if not o.get("ingested")]
        opinion_ids = [o["id"] for o in opinions[:batch_size]]
    else:
        opinion_ids = opinion_ids[:batch_size]
    
    if not opinion_ids:
        return {
            "success": True,
            "message": "No opinions to ingest",
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "results": []
        }
    
    results = []
    succeeded = 0
    failed = 0
    
    for opinion_id in opinion_ids:
        result = await ingest_opinion(opinion_id)
        result["opinion_id"] = opinion_id
        results.append(result)
        
        if result.get("success"):
            succeeded += 1
        else:
            failed += 1
    
    return {
        "success": failed == 0,
        "message": f"Batch complete: {succeeded} succeeded, {failed} failed",
        "processed": len(opinion_ids),
        "succeeded": succeeded,
        "failed": failed,
        "results": results
    }

def get_ingestion_status() -> Dict[str, Any]:
    opinions = db.get_opinions()
    total = len(opinions)
    ingested = sum(1 for o in opinions if o.get("ingested"))
    pending = total - ingested
    
    pending_opinions = [
        {"id": o["id"], "case_name": o["case_name"]}
        for o in opinions if not o.get("ingested")
    ][:10]
    
    return {
        "total_opinions": total,
        "ingested": ingested,
        "pending": pending,
        "percent_complete": round(ingested / total * 100, 1) if total > 0 else 0,
        "next_pending": pending_opinions
    }
