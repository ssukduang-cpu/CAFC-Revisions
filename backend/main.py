from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
import json
import re

from backend import database as db
from backend.scraper import scrape_opinions
from backend.ingestion import ingest_opinion
from backend.chat import generate_chat_response

app = FastAPI(title="CAFC Precedential Copilot")

def to_camel_case(snake_str: str) -> str:
    components = snake_str.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])

def convert_keys_to_camel(data: Any) -> Any:
    if isinstance(data, dict):
        return {to_camel_case(k): convert_keys_to_camel(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_keys_to_camel(item) for item in data]
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

@app.get("/api/status")
async def get_status():
    return db.get_status()

@app.post("/api/opinions/sync")
async def sync_opinions():
    try:
        opinions = await scrape_opinions()
        added = 0
        skipped = 0
        
        existing_urls = {op["pdf_url"] for op in db.get_opinions()}
        
        for opinion_data in opinions:
            if opinion_data["pdf_url"] in existing_urls:
                skipped += 1
            else:
                db.upsert_opinion(opinion_data)
                added += 1
        
        all_opinions = db.get_opinions()
        total = len(all_opinions)
        ingested = sum(1 for o in all_opinions if o.get("ingested"))
        
        return {
            "success": True,
            "message": f"Synced {len(opinions)} opinions from CAFC",
            "scraped": len(opinions),
            "added": added,
            "skipped": skipped,
            "total": total,
            "ingested": ingested
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/opinions")
async def list_opinions(
    q: Optional[str] = None,
    origin: Optional[str] = None,
    ingested: Optional[bool] = None
):
    opinions = db.get_opinions(q=q, origin=origin, ingested=ingested)
    total = len(opinions)
    ingested_count = sum(1 for o in opinions if o.get("ingested"))
    
    return {
        "opinions": convert_keys_to_camel(opinions),
        "total": total,
        "ingested": ingested_count
    }

@app.get("/api/opinions/{opinion_id}")
async def get_opinion(opinion_id: str):
    opinion = db.get_opinion(opinion_id)
    if not opinion:
        raise HTTPException(status_code=404, detail="Opinion not found")
    return convert_keys_to_camel(opinion)

@app.post("/api/opinions/{opinion_id}/ingest")
async def ingest_opinion_endpoint(opinion_id: str):
    result = await ingest_opinion(opinion_id)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Ingestion failed"))
    return {
        "success": True,
        "message": result.get("message", "Opinion ingested successfully"),
        "numPages": result.get("num_pages", 0),
        "chunksCreated": result.get("inserted_pages", 0),
        "textLength": len(result.get("page1_preview", ""))
    }

@app.get("/api/conversations")
async def list_conversations():
    return convert_keys_to_camel(db.get_conversations())

@app.post("/api/conversations")
async def create_conversation():
    conv_id = db.create_conversation()
    return convert_keys_to_camel(db.get_conversation(conv_id))

@app.get("/api/conversations/{conversation_id}")
async def get_conversation_endpoint(conversation_id: str):
    conv = db.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = db.get_messages(conversation_id)
    result = convert_keys_to_camel(conv)
    result["messages"] = convert_keys_to_camel(messages)
    return result

@app.get("/api/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str):
    return convert_keys_to_camel(db.get_messages(conversation_id))

class MessageRequest(BaseModel):
    content: str

@app.post("/api/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, request: MessageRequest):
    user_msg_id = db.add_message(conversation_id, "user", request.content)
    
    result = await generate_chat_response(
        message=request.content,
        opinion_ids=None,
        conversation_id=conversation_id
    )
    
    assistant_msg_id = db.add_message(
        conversation_id, 
        "assistant", 
        result["answer"],
        json.dumps(result.get("citations", []))
    )
    
    messages = db.get_messages(conversation_id)
    user_msg = next((m for m in messages if m["id"] == user_msg_id), None)
    assistant_msg = next((m for m in messages if m["id"] == assistant_msg_id), None)
    
    assistant_response = convert_keys_to_camel(assistant_msg) if assistant_msg else {}
    assistant_response["citations"] = result.get("citations", [])
    
    return {
        "userMessage": convert_keys_to_camel(user_msg) if user_msg else {},
        "assistantMessage": assistant_response
    }

@app.post("/api/chat")
async def chat(request: ChatRequest):
    conv_id = request.conversation_id
    if not conv_id:
        conv_id = db.create_conversation()
    
    db.add_message(conv_id, "user", request.message)
    
    result = await generate_chat_response(
        message=request.message,
        opinion_ids=request.selected_opinion_ids,
        conversation_id=conv_id
    )
    
    db.add_message(
        conv_id, 
        "assistant", 
        result["answer"],
        json.dumps(result.get("citations", []))
    )
    
    return {
        "conversation_id": conv_id,
        "answer": result["answer"],
        "citations": result.get("citations", []),
        "support_audit": result.get("support_audit", []),
        "retrieval_only": result.get("retrieval_only", False)
    }

CLIENT_BUILD_DIR = os.path.join(os.path.dirname(__file__), "..", "client", "dist")

if os.path.exists(CLIENT_BUILD_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(CLIENT_BUILD_DIR, "assets")), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        return FileResponse(os.path.join(CLIENT_BUILD_DIR, "index.html"))
