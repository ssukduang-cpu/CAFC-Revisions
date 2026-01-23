import httpx
import os
from pypdf import PdfReader
from typing import Dict, Any
import traceback
import sys

from backend import database as db

PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "pdfs")

def log_memory(label: str):
    import resource
    usage = resource.getrusage(resource.RUSAGE_SELF)
    mem_mb = usage.ru_maxrss / 1024
    print(f"[memory] {label}: {mem_mb:.1f}MB", file=sys.stderr)

async def ingest_opinion(opinion_id: str) -> Dict[str, Any]:
    os.makedirs(PDF_DIR, exist_ok=True)
    pdf_path = os.path.join(PDF_DIR, f"{opinion_id}.pdf")
    
    try:
        log_memory("start")
        
        opinion = db.get_opinion(opinion_id)
        if not opinion:
            return {"success": False, "error": "Opinion not found"}
        
        if opinion["ingested"]:
            return {"success": True, "message": "Already ingested", "num_pages": 0, "inserted_pages": 0}
        
        print(f"Downloading: {opinion['case_name']}", file=sys.stderr)
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(opinion["pdf_url"])
            response.raise_for_status()
            
            with open(pdf_path, "wb") as f:
                f.write(response.content)
        
        log_memory("after-download")
        
        reader = PdfReader(pdf_path)
        num_pages = len(reader.pages)
        print(f"Processing {num_pages} pages...", file=sys.stderr)
        
        inserted_pages = 0
        page1_preview = ""
        
        for page_num in range(num_pages):
            page = reader.pages[page_num]
            text = page.extract_text() or ""
            
            if page_num == 0:
                page1_preview = text[:500].replace("\n", " ").strip()
            
            db.insert_page(opinion_id, page_num + 1, text)
            inserted_pages += 1
            
            if (page_num + 1) % 10 == 0:
                log_memory(f"page-{page_num + 1}")
                print(f"Processed page {page_num + 1}/{num_pages}", file=sys.stderr)
        
        db.mark_opinion_ingested(opinion_id)
        log_memory("complete")
        
        return {
            "success": True,
            "num_pages": num_pages,
            "inserted_pages": inserted_pages,
            "page1_preview": page1_preview[:200],
        }
        
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    
    finally:
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except:
                pass
