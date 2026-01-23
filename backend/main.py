from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
import json
import asyncio
import subprocess

from backend import db_postgres as db
from backend.scraper import scrape_opinions
from backend.chat import generate_chat_response

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
    ingested: Optional[bool] = None
):
    documents = db.get_documents(q=q, origin=origin, ingested=ingested)
    documents = serialize_for_json(documents)
    total = len(documents)
    ingested_count = sum(1 for d in documents if d.get("ingested"))
    
    camel_docs = []
    for doc in documents:
        camel_doc = convert_keys_to_camel(doc)
        camel_doc["isIngested"] = doc.get("ingested", False)
        camel_doc["appealNo"] = doc.get("appeal_number", "")
        camel_docs.append(camel_doc)
    
    return {
        "opinions": camel_docs,
        "total": total,
        "ingested": ingested_count
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
    q: str,
    limit: int = 20,
    mode: str = "all"  # "all" = full text + case names, "parties" = case names only
):
    if not q or len(q.strip()) < 2:
        return {"results": [], "query": q, "mode": mode}
    
    party_only = mode == "parties"
    results = db.search_chunks(q, limit=limit, party_only=party_only)
    results = serialize_for_json(results)
    
    formatted_results = []
    for r in results:
        formatted_results.append({
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
    
    return {
        "query": q,
        "results": formatted_results,
        "count": len(formatted_results)
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

@app.get("/api/admin/ingest_status")
async def admin_ingest_status():
    return db.get_ingestion_stats()

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
        "assistantMessage": assistant_response
    }

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
        "debug": result.get("debug", {})
    }

CLIENT_BUILD_DIR = os.path.join(os.path.dirname(__file__), "..", "client", "dist")

if os.path.exists(CLIENT_BUILD_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(CLIENT_BUILD_DIR, "assets")), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        return FileResponse(os.path.join(CLIENT_BUILD_DIR, "index.html"))
