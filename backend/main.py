from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, AsyncGenerator
import os
import json
import asyncio
import subprocess

from backend import db_postgres as db
from backend.scraper import scrape_opinions
from backend.chat import generate_chat_response, generate_chat_response_stream
from backend.web_search import search_tavily

app = FastAPI(title="Federal Circuit AI")

def to_camel_case(snake_str: str) -> str:
    components = snake_str.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])

def convert_keys_to_camel(data: Any) -> Any:
    if isinstance(data, dict):
        return {to_camel_case(k): convert_keys_to_camel(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_keys_to_camel(item) for item in data]
    return data

def serialize_for_json(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: serialize_for_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [serialize_for_json(item) for item in data]
    elif hasattr(data, 'isoformat'):
        return data.isoformat()
    elif hasattr(data, '__str__') and not isinstance(data, (str, int, float, bool, type(None))):
        return str(data)
    return data

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()

class ChatRequest(BaseModel):
    message: str
    selected_opinion_ids: Optional[List[str]] = None
    conversation_id: Optional[str] = None
    search_mode: str = "all"  # "all" = full text + case names, "parties" = case names only

@app.get("/api/status")
async def get_status():
    return db.get_status()

@app.post("/api/opinions/sync")
async def sync_opinions():
    """
    DEPRECATED: Legacy sync endpoint that scraped CAFC website.
    
    For a complete backfill, use:
    1. python scripts/build_manifest_courtlistener.py
    2. POST /api/admin/load_manifest_file
    
    This endpoint now returns instructions instead of scraping.
    """
    stats = db.get_ingestion_stats()
    
    return {
        "success": True,
        "message": "CAFC website scraping is deprecated. Use CourtListener-based manifest import instead.",
        "deprecated": True,
        "instructions": [
            "For a complete backfill of all Federal Circuit precedential opinions:",
            "1. Run: python scripts/build_manifest_courtlistener.py",
            "2. Call: POST /api/admin/load_manifest_file",
            "",
            "Or use the batch ingest endpoint after importing:",
            "  POST /api/admin/ingest_batch?limit=50"
        ],
        "current_status": {
            "total_documents": stats["total_documents"],
            "ingested": stats["ingested"],
            "pending": stats["pending"]
        }
    }

@app.get("/api/opinions")
async def list_opinions(
    q: Optional[str] = None,
    origin: Optional[str] = None,
    ingested: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0
):
    documents = db.get_documents(q=q, origin=origin, ingested=ingested, limit=limit, offset=offset)
    documents = serialize_for_json(documents)
    
    stats = db.get_ingestion_stats()
    total = stats.get('total_documents', 0)
    ingested_count = stats.get('ingested', 0)
    
    camel_docs = []
    for doc in documents:
        camel_doc = convert_keys_to_camel(doc)
        camel_doc["isIngested"] = doc.get("ingested", False)
        camel_doc["appealNo"] = doc.get("appeal_number", "")
        camel_docs.append(camel_doc)
    
    return {
        "opinions": camel_docs,
        "total": total,
        "ingested": ingested_count,
        "limit": limit,
        "offset": offset,
        "hasMore": offset + len(camel_docs) < total
    }

@app.get("/api/opinions/{opinion_id}")
async def get_opinion(opinion_id: str):
    doc = db.get_document(opinion_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Opinion not found")
    doc = serialize_for_json(doc)
    result = convert_keys_to_camel(doc)
    result["isIngested"] = doc.get("ingested", False)
    result["appealNo"] = doc.get("appeal_number", "")
    return result

@app.post("/api/opinions/{opinion_id}/ingest")
async def ingest_opinion_endpoint(opinion_id: str):
    from backend.ingest.run import ingest_document
    
    doc = db.get_document(opinion_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Opinion not found")
    
    result = await ingest_document(doc)
    
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Ingestion failed"))
    
    return {
        "success": True,
        "message": "Opinion ingested successfully",
        "numPages": result.get("num_pages", 0),
        "chunksCreated": result.get("num_chunks", 0),
        "status": result.get("status", "completed")
    }

class BatchIngestRequest(BaseModel):
    opinion_ids: Optional[List[str]] = None
    batch_size: int = 5
    skip_ingested: bool = True

@app.post("/api/opinions/batch-ingest")
async def batch_ingest_endpoint(request: BatchIngestRequest):
    from backend.ingest.run import ingest_document
    
    if request.opinion_ids:
        documents = [db.get_document(oid) for oid in request.opinion_ids if db.get_document(oid)]
    else:
        documents = db.get_pending_documents(limit=request.batch_size)
    
    if not documents:
        return {
            "success": True,
            "message": "No documents to ingest",
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "results": []
        }
    
    results = []
    succeeded = 0
    failed = 0
    
    for doc in documents:
        result = await ingest_document(doc)
        results.append(serialize_for_json(result))
        
        if result.get("success"):
            succeeded += 1
        else:
            failed += 1
    
    return {
        "success": failed == 0,
        "message": f"Batch complete: {succeeded} succeeded, {failed} failed",
        "processed": len(documents),
        "succeeded": succeeded,
        "failed": failed,
        "results": results
    }

@app.get("/api/ingestion/status")
async def ingestion_status_endpoint():
    return db.get_ingestion_stats()

@app.get("/api/integrity/check")
async def integrity_check_endpoint():
    stats = db.get_ingestion_stats()
    fts_health = db.check_fts_health()
    
    return {
        "healthy": fts_health.get("healthy", False),
        "stats": stats,
        "fts_health": fts_health
    }

@app.get("/api/search")
async def search_endpoint(
    q: str = Query(..., min_length=2),
    limit: int = 20,
    mode: str = "all"  # "all" = full text + case names, "parties" = case names only
):
    """Optimized Search: Runs local DB and Web searches concurrently."""
    if not q or len(q.strip()) < 2:
        return {"results": [], "query": q, "mode": mode}
    
    party_only = mode == "parties"
    
    # 1. Prepare tasks for parallel execution
    db_task = asyncio.create_task(
        asyncio.to_thread(db.search_chunks, q, limit=limit, party_only=party_only)
    )
    
    # 2. Trigger web search only if not in 'party_only' mode
    web_task = None
    if not party_only:
        web_task = asyncio.create_task(search_tavily(q, max_results=5))

    # 3. Gather results with error handling
    try:
        if web_task:
            local_results, web_data = await asyncio.wait_for(
                asyncio.gather(db_task, web_task, return_exceptions=True),
                timeout=15.0
            )
            # Handle exceptions from gather
            if isinstance(local_results, Exception):
                local_results = []
            if isinstance(web_data, Exception):
                web_data = {"success": False}
        else:
            local_results = await asyncio.wait_for(db_task, timeout=5.0)
            web_data = {"success": False}
    except asyncio.TimeoutError:
        logger.error("Search orchestration timed out")
        local_results, web_data = [], {"success": False}
    except Exception as e:
        logger.error(f"Search orchestration failed: {e}")
        local_results, web_data = [], {"success": False}

    local_results = serialize_for_json(local_results) if local_results else []
    
    # 4. Format local results
    final_results = []
    for r in local_results:
        final_results.append({
            "source": "library",
            "documentId": str(r.get("document_id", "")),
            "caseName": r.get("case_name", ""),
            "appealNumber": r.get("appeal_number", ""),
            "releaseDate": r.get("release_date", ""),
            "pdfUrl": r.get("pdf_url", ""),
            "pageStart": r.get("page_start", 1),
            "pageEnd": r.get("page_end", 1),
            "snippet": r.get("text", "")[:500],
            "rank": r.get("rank", 0)
        })

    # 5. Add web results as secondary references (avoid duplicates)
    if isinstance(web_data, dict) and web_data.get("success"):
        for case in web_data.get("extracted_cases", []):
            case_name = case.get("case_name", "")
            if case_name and not any(f.get("caseName") == case_name for f in final_results):
                final_results.append({
                    "source": "web",
                    "documentId": "",
                    "caseName": case_name,
                    "appealNumber": "",
                    "releaseDate": "",
                    "pdfUrl": case.get("source_url", ""),
                    "pageStart": 1,
                    "pageEnd": 1,
                    "snippet": f"Web Match: {case.get('citation') or 'Click to view'}",
                    "rank": 0.5
                })
    
    return {
        "query": q,
        "results": final_results[:limit],
        "count": len(final_results)
    }

manifest_build_running = False

@app.post("/api/admin/build_manifest")
async def build_manifest_endpoint(background_tasks: BackgroundTasks):
    global manifest_build_running
    
    if manifest_build_running:
        return {
            "success": False,
            "message": "Manifest build already in progress"
        }
    
    return {
        "success": True,
        "message": "To build the manifest, run the Playwright script locally or use the import endpoint",
        "instructions": [
            "Option A - Run Playwright locally:",
            "  1. Clone the repo locally",
            "  2. pip install playwright && playwright install chromium",
            "  3. python scripts/build_manifest.py",
            "  4. Upload data/manifest.ndjson via POST /api/admin/import_manifest",
            "",
            "Option B - Upload existing manifest:",
            "  POST /api/admin/import_manifest with NDJSON file"
        ]
    }

class ManifestImportRequest(BaseModel):
    opinions: List[Dict[str, Any]]

@app.post("/api/admin/import_manifest")
async def import_manifest_endpoint(request: ManifestImportRequest):
    """
    Import opinions from manifest data.
    Deduplication uses courtlistener_cluster_id as primary key,
    or (appeal_number, pdf_url) as fallback.
    """
    imported = 0
    skipped = 0
    
    for opinion in request.opinions:
        if not opinion.get("pdf_url"):
            skipped += 1
            continue
        
        cluster_id = opinion.get("courtlistener_cluster_id")
        appeal_number = opinion.get("appeal_number")
        pdf_url = opinion.get("pdf_url")
        
        if db.document_exists_by_dedupe_key(cluster_id, appeal_number, pdf_url):
            skipped += 1
            continue
        
        db.upsert_document({
            "pdf_url": pdf_url,
            "case_name": opinion.get("case_name"),
            "appeal_number": appeal_number,
            "release_date": opinion.get("release_date"),
            "origin": opinion.get("origin"),
            "document_type": opinion.get("document_type"),
            "status": opinion.get("status"),
            "file_path": opinion.get("file_path"),
            "courtlistener_cluster_id": cluster_id,
            "courtlistener_url": opinion.get("courtlistener_url")
        })
        imported += 1
    
    stats = db.get_ingestion_stats()
    
    return {
        "success": True,
        "message": f"Imported {imported} documents, skipped {skipped} duplicates",
        "inserted": imported,
        "skipped_duplicates": skipped,
        "total_documents": stats["total_documents"]
    }

@app.post("/api/admin/load_manifest_file")
async def load_manifest_file_endpoint():
    """
    Load manifest from data/manifest.ndjson file.
    Uses cluster_id-based deduplication.
    """
    manifest_path = os.path.join(os.path.dirname(__file__), "..", "data", "manifest.ndjson")
    
    if not os.path.exists(manifest_path):
        raise HTTPException(status_code=404, detail="Manifest file not found. Run scripts/build_manifest_courtlistener.py first or upload via /api/admin/import_manifest")
    
    imported = 0
    skipped = 0
    
    with open(manifest_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            
            try:
                opinion = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            if not opinion.get("pdf_url"):
                skipped += 1
                continue
            
            cluster_id = opinion.get("courtlistener_cluster_id")
            appeal_number = opinion.get("appeal_number")
            pdf_url = opinion.get("pdf_url")
            
            if db.document_exists_by_dedupe_key(cluster_id, appeal_number, pdf_url):
                skipped += 1
                continue
            
            db.upsert_document({
                "pdf_url": pdf_url,
                "case_name": opinion.get("case_name"),
                "appeal_number": appeal_number,
                "release_date": opinion.get("release_date"),
                "origin": opinion.get("origin"),
                "document_type": opinion.get("document_type"),
                "status": opinion.get("status"),
                "file_path": opinion.get("file_path"),
                "courtlistener_cluster_id": cluster_id,
                "courtlistener_url": opinion.get("courtlistener_url")
            })
            imported += 1
    
    stats = db.get_ingestion_stats()
    
    return {
        "success": True,
        "message": f"Loaded {imported} documents from manifest, skipped {skipped}",
        "inserted": imported,
        "skipped_duplicates": skipped,
        "total_documents": stats["total_documents"]
    }

@app.post("/api/admin/ingest_batch")
async def admin_ingest_batch(limit: int = 50):
    from backend.ingest.run import run_batch_ingest
    result = await run_batch_ingest(limit=limit)
    return serialize_for_json(result)

@app.post("/api/admin/build_and_load_manifest")
async def build_and_load_manifest(count: int = 100):
    """
    Build a manifest from CourtListener API and load it directly into the database.
    This is an all-in-one endpoint for production use.
    """
    import httpx
    
    api_token = os.environ.get('COURTLISTENER_API_TOKEN')
    if not api_token:
        raise HTTPException(status_code=500, detail="COURTLISTENER_API_TOKEN not configured")
    
    headers = {
        'Authorization': f'Token {api_token}',
        'User-Agent': 'Federal-Circuit-AI-Research/1.0'
    }
    
    imported = 0
    skipped = 0
    fetched = 0
    
    next_url = None
    base_url = "https://www.courtlistener.com/api/rest/v4/search/"
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        while imported < count:
            if next_url:
                response = await client.get(next_url, headers=headers)
            else:
                params = {
                    'type': 'o',
                    'court': 'cafc',
                    'stat_Published': 'on',
                    'order_by': 'dateFiled desc',
                }
                response = await client.get(base_url, params=params, headers=headers)
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=f"CourtListener API error: {response.text[:200]}")
            
            data = response.json()
            results = data.get('results', [])
            
            if not results:
                break
            
            for result in results:
                if imported >= count:
                    break
                
                cluster_id = result.get('cluster_id')
                case_name = result.get('caseName', '')
                appeal_number = result.get('docketNumber', '')
                date_filed = result.get('dateFiled')
                
                fetched += 1
                
                # Check if already exists using cluster_id
                if db.document_exists_by_dedupe_key(cluster_id, appeal_number, None):
                    skipped += 1
                    continue
                
                # Fetch actual PDF URL from opinions endpoint
                pdf_url = None
                try:
                    opinions_url = f"https://www.courtlistener.com/api/rest/v4/opinions/?cluster={cluster_id}"
                    op_response = await client.get(opinions_url, headers=headers)
                    if op_response.status_code == 200:
                        op_data = op_response.json()
                        op_results = op_data.get('results', [])
                        for op in op_results:
                            dl_url = op.get('download_url')
                            if dl_url:
                                pdf_url = dl_url
                                break
                except Exception as e:
                    pass
                
                # Fallback to the /pdf/ URL if we couldn't get the actual download_url
                if not pdf_url:
                    pdf_url = f"https://www.courtlistener.com/pdf/{cluster_id}/"
                
                db.upsert_document({
                    "pdf_url": pdf_url,
                    "case_name": case_name,
                    "appeal_number": appeal_number,
                    "release_date": date_filed,
                    "origin": "courtlistener_api",
                    "document_type": "OPINION",
                    "status": "Precedential",
                    "courtlistener_cluster_id": cluster_id,
                    "courtlistener_url": f"https://www.courtlistener.com/opinion/{cluster_id}/"
                })
                imported += 1
                fetched += 1
            
            next_url = data.get('next')
            if not next_url:
                break
    
    stats = db.get_ingestion_stats()
    
    return {
        "success": True,
        "message": f"Loaded {imported} documents from CourtListener, skipped {skipped} duplicates",
        "imported": imported,
        "skipped": skipped,
        "total_documents": stats["total_documents"]
    }

@app.get("/api/admin/ingest_status")
async def admin_ingest_status():
    return db.get_ingestion_stats()

@app.post("/api/admin/reset_failed")
async def admin_reset_failed(error_pattern: str = "202"):
    """
    Reset documents with matching error pattern so they can be retried.
    Default resets the '202 PDF generation in progress' errors.
    """
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE documents 
            SET last_error = NULL, ingested = FALSE
            WHERE last_error LIKE %s
            RETURNING id
        """, (f"%{error_pattern}%",))
        reset_ids = [row["id"] for row in cursor.fetchall()]
        conn.commit()
    
    return {
        "success": True,
        "reset_count": len(reset_ids),
        "pattern_matched": error_pattern,
        "message": f"Reset {len(reset_ids)} documents for retry"
    }

@app.get("/api/admin/error_summary")
async def admin_error_summary():
    """Get a summary of ingestion errors by category."""
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                CASE 
                    WHEN last_error LIKE '%202%' THEN 'PDF generation pending (202)'
                    WHEN last_error LIKE '%404%' THEN 'Not found (404)'
                    WHEN last_error LIKE '%OCR%' THEN 'OCR required'
                    WHEN last_error LIKE '%None%' THEN 'Download returned None'
                    ELSE 'Other'
                END as error_category,
                COUNT(*) as count
            FROM documents 
            WHERE last_error IS NOT NULL
            GROUP BY error_category
            ORDER BY count DESC
        """)
        rows = cursor.fetchall()
    
    return {
        "error_categories": [{"category": r["error_category"], "count": r["count"]} for r in rows],
        "total_failed": sum(r["count"] for r in rows)
    }

@app.get("/api/admin/diagnostics")
async def admin_diagnostics():
    """Detailed diagnostics for troubleshooting production issues."""
    import os
    
    # Check if COURTLISTENER_API_TOKEN is available
    has_token = bool(os.environ.get('COURTLISTENER_API_TOKEN'))
    
    # Check database state
    stats = db.get_ingestion_stats()
    
    # Check if constraint exists
    constraint_exists = False
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM pg_constraint WHERE conname = 'document_chunks_document_id_chunk_index_key'
            """)
            constraint_exists = cursor.fetchone() is not None
    except Exception as e:
        constraint_exists = f"Error checking: {str(e)}"
    
    return {
        "courtlistener_token_available": has_token,
        "database_stats": stats,
        "chunk_constraint_exists": constraint_exists,
        "environment": os.environ.get('NODE_ENV', 'unknown'),
        "database_url_set": bool(os.environ.get('DATABASE_URL'))
    }

# PDF serving routes
PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "pdfs")

@app.get("/pdf/{opinion_id}")
async def serve_pdf_by_id(opinion_id: str, page: int = 1):
    """
    Serve PDF files by opinion ID.
    Returns custom JSON error if file is missing.
    """
    import uuid
    
    # Validate UUID format to prevent path traversal attacks
    try:
        validated_uuid = uuid.UUID(opinion_id)
        safe_opinion_id = str(validated_uuid)
    except (ValueError, AttributeError):
        return JSONResponse(
            status_code=400,
            content={
                "error": "Invalid opinion ID format",
                "status": "invalid_id",
                "opinion_id": opinion_id[:50] if opinion_id else None
            }
        )
    
    pdf_filename = f"{safe_opinion_id}.pdf"
    pdf_path = os.path.join(PDF_DIR, pdf_filename)
    
    # Try to look up the document for fallback URL
    doc = None
    try:
        doc = db.get_document(safe_opinion_id)
    except Exception:
        # DB error - continue without doc metadata
        pass
    
    if not os.path.exists(pdf_path):
        # Return custom JSON error with fallback URL information
        fallback_url = None
        if doc:
            # Prefer CourtListener URL, then original PDF URL
            fallback_url = doc.get('courtlistener_url') or doc.get('pdf_url')
        
        return JSONResponse(
            status_code=404,
            content={
                "error": "PDF not yet downloaded",
                "status": "retry_later",
                "opinion_id": opinion_id,
                "fallback_url": fallback_url
            }
        )
    
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=pdf_filename,
        headers={"Content-Disposition": f"inline; filename={pdf_filename}"}
    )

@app.get("/pdfs/{filename:path}")
async def serve_pdf(filename: str):
    """
    Serve PDF files from the data/pdfs directory by filename.
    Returns custom JSON error if file is missing.
    """
    # Sanitize filename to prevent directory traversal
    safe_filename = os.path.basename(filename)
    if not safe_filename.endswith('.pdf'):
        safe_filename += '.pdf'
    
    pdf_path = os.path.join(PDF_DIR, safe_filename)
    
    if not os.path.exists(pdf_path):
        # Return custom JSON error instead of generic 404
        return JSONResponse(
            status_code=404,
            content={
                "error": "PDF not yet downloaded",
                "status": "retry_later",
                "filename": safe_filename
            }
        )
    
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=safe_filename
    )

@app.get("/api/conversations")
async def list_conversations():
    convs = db.get_conversations()
    return serialize_for_json(convert_keys_to_camel(convs))

@app.post("/api/conversations")
async def create_conversation():
    conv_id = db.create_conversation()
    conv = db.get_conversation(conv_id)
    return serialize_for_json(convert_keys_to_camel(conv))

@app.get("/api/conversations/{conversation_id}")
async def get_conversation_endpoint(conversation_id: str):
    conv = db.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = db.get_messages(conversation_id)
    result = serialize_for_json(convert_keys_to_camel(conv))
    result["messages"] = serialize_for_json(convert_keys_to_camel(messages))
    return result

@app.get("/api/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str):
    messages = db.get_messages(conversation_id)
    return serialize_for_json(convert_keys_to_camel(messages))

class MessageRequest(BaseModel):
    content: str
    searchMode: str = "all"  # "all" = full text + case names, "parties" = case names only

@app.post("/api/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, request: MessageRequest):
    user_msg_id = db.add_message(conversation_id, "user", request.content)
    
    party_only = request.searchMode == "parties"
    result = await generate_chat_response(
        message=request.content,
        opinion_ids=None,
        conversation_id=conversation_id,
        party_only=party_only
    )
    
    citation_data = {
        "answer_markdown": result.get("answer_markdown", ""),
        "sources": result.get("sources", []),
        "debug": result.get("debug", {})
    }
    
    answer_text = result.get("answer_markdown", "No response generated.")
    
    assistant_msg_id = db.add_message(
        conversation_id,
        "assistant",
        answer_text,
        json.dumps(citation_data)
    )
    
    messages = db.get_messages(conversation_id)
    user_msg = next((m for m in messages if str(m["id"]) == user_msg_id), None)
    assistant_msg = next((m for m in messages if str(m["id"]) == assistant_msg_id), None)
    
    assistant_response = serialize_for_json(convert_keys_to_camel(assistant_msg)) if assistant_msg else {}
    
    return {
        "userMessage": serialize_for_json(convert_keys_to_camel(user_msg)) if user_msg else {},
        "assistantMessage": assistant_response,
        "webSearchTriggered": result.get("web_search_triggered", False),
        "webSearchCases": result.get("web_search_cases", [])
    }

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE streaming endpoint for real-time chat responses."""
    conv_id = request.conversation_id
    if not conv_id:
        title = request.message[:60].strip()
        if len(request.message) > 60:
            title += "..."
        conv_id = db.create_conversation(title)
    
    db.add_message(conv_id, "user", request.message)
    
    party_only = request.search_mode == "parties"
    
    async def generate():
        full_response = ""
        sources = []
        
        # First yield the conversation ID
        yield f'data: {{"type": "conversation_id", "conversation_id": "{conv_id}"}}\n\n'
        
        async for chunk in generate_chat_response_stream(
            message=request.message,
            opinion_ids=request.selected_opinion_ids,
            conversation_id=conv_id,
            party_only=party_only
        ):
            # Accumulate full response for saving
            if '"type": "token"' in chunk:
                try:
                    data = json.loads(chunk.replace('data: ', '').strip())
                    if data.get('type') == 'token':
                        full_response += data.get('content', '')
                except:
                    pass
            elif '"type": "sources"' in chunk:
                try:
                    data = json.loads(chunk.replace('data: ', '').strip())
                    if data.get('type') == 'sources':
                        sources = data.get('sources', [])
                except:
                    pass
            yield chunk
        
        # Save the complete message to conversation history
        if full_response:
            citation_data = {
                "answer_markdown": full_response,
                "sources": sources,
                "action_items": [],
                "debug": {}
            }
            db.add_message(
                conv_id,
                "assistant",
                full_response,
                json.dumps(citation_data)
            )
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.get("/api/digest/recent")
async def get_recent_digest():
    """Get recently ingested cases discovered via web search."""
    try:
        recent = db.get_recent_web_search_ingests(limit=10)
        return {
            "success": True,
            "recent_ingests": [
                {
                    "id": r.get("id"),
                    "case_name": r.get("case_name") or r.get("full_case_name"),
                    "cluster_id": r.get("cluster_id"),
                    "search_query": r.get("search_query"),
                    "ingested_at": r.get("ingested_at").isoformat() if r.get("ingested_at") else None,
                    "document_id": str(r.get("document_id")) if r.get("document_id") else None
                }
                for r in recent
            ]
        }
    except Exception as e:
        return {"success": False, "error": str(e), "recent_ingests": []}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    conv_id = request.conversation_id
    if not conv_id:
        # Create conversation with title based on first message (truncated to 60 chars)
        title = request.message[:60].strip()
        if len(request.message) > 60:
            title += "..."
        conv_id = db.create_conversation(title)
    
    db.add_message(conv_id, "user", request.message)
    
    party_only = request.search_mode == "parties"
    result = await generate_chat_response(
        message=request.message,
        opinion_ids=request.selected_opinion_ids,
        conversation_id=conv_id,
        party_only=party_only
    )
    
    citation_data = {
        "answer_markdown": result.get("answer_markdown", ""),
        "sources": result.get("sources", []),
        "action_items": result.get("action_items", []),
        "debug": result.get("debug", {})
    }
    
    db.add_message(
        conv_id,
        "assistant",
        result.get("answer_markdown", ""),
        json.dumps(citation_data)
    )
    
    return {
        "conversation_id": conv_id,
        "answer_markdown": result.get("answer_markdown", ""),
        "sources": result.get("sources", []),
        "action_items": result.get("action_items", []),
        "debug": result.get("debug", {}),
        "return_branch": result.get("return_branch", "unknown"),
        "markers_count": result.get("markers_count", 0),
        "sources_count": result.get("sources_count", 0),
        "web_search_triggered": result.get("web_search_triggered", False),
        "newly_ingested_cases": result.get("newly_ingested_cases", [])
    }

CLIENT_BUILD_DIR = os.path.join(os.path.dirname(__file__), "..", "client", "dist")

if os.path.exists(CLIENT_BUILD_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(CLIENT_BUILD_DIR, "assets")), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        return FileResponse(os.path.join(CLIENT_BUILD_DIR, "index.html"))
