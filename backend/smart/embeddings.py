"""
Embeddings Fallback Module

Provides semantic recall when FTS results are thin.
Uses OpenAI embeddings and pgvector for similarity search.

This module is:
- Additive only (does not replace FTS retrieval)
- Fail-soft (returns empty list on any error)
- Bounded (max candidates, time budget)
- Requires offline embedding build (not computed on-demand)
"""

import os
import logging
import time
from typing import List, Dict, Optional, Any
import hashlib

from backend.smart.config import (
    MAX_EMBED_CANDIDATES,
    EMBEDDING_MODEL,
    EMBEDDING_DIMENSIONS,
    PHASE1_BUDGET_MS
)

logger = logging.getLogger(__name__)

_openai_client = None


def get_openai_client():
    """Lazily initialize OpenAI client."""
    global _openai_client
    if _openai_client is None:
        try:
            from openai import OpenAI
            _openai_client = OpenAI()
        except Exception as e:
            logger.warning(f"Failed to initialize OpenAI client: {e}")
            return None
    return _openai_client


def embed_text(text: str) -> Optional[List[float]]:
    """
    Generate embedding for text using OpenAI.
    
    Returns:
        Embedding vector or None on error
    """
    try:
        client = get_openai_client()
        if not client:
            return None
        
        text = text[:8000]
        
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
            dimensions=EMBEDDING_DIMENSIONS
        )
        
        return response.data[0].embedding
        
    except Exception as e:
        logger.warning(f"Embedding generation failed: {e}")
        return None


def check_embeddings_available() -> Dict[str, Any]:
    """Check if embeddings are available and ready for use."""
    try:
        from backend import db_postgres as db
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'page_embeddings'
                )
            """)
            table_exists = cursor.fetchone()[0]
            
            if not table_exists:
                return {
                    "available": False,
                    "reason": "page_embeddings table does not exist",
                    "count": 0
                }
            
            cursor.execute("SELECT COUNT(*) FROM page_embeddings")
            count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM document_pages")
            total_pages = cursor.fetchone()[0]
            
            coverage = count / total_pages if total_pages > 0 else 0
            
            return {
                "available": count > 1000,
                "reason": f"Found {count} embeddings ({coverage:.1%} coverage)",
                "count": count,
                "total_pages": total_pages,
                "coverage": coverage
            }
            
    except Exception as e:
        return {
            "available": False,
            "reason": f"Error checking embeddings: {e}",
            "count": 0
        }


def semantic_recall(query: str, k: int = MAX_EMBED_CANDIDATES, exclude_ids: Optional[List[str]] = None) -> List[Dict]:
    """
    Retrieve semantically similar pages using embeddings.
    
    Args:
        query: Search query
        k: Maximum candidates to return
        exclude_ids: Page IDs to exclude (already in baseline results)
    
    Returns:
        List of page records (same format as FTS results)
    """
    start_time = time.time()
    exclude_ids = exclude_ids or []
    
    try:
        status = check_embeddings_available()
        if not status["available"]:
            logger.debug(f"Embeddings not available: {status['reason']}")
            return []
        
        query_embedding = embed_text(query)
        if not query_embedding:
            return []
        
        elapsed_ms = (time.time() - start_time) * 1000
        if elapsed_ms > PHASE1_BUDGET_MS * 0.8:
            logger.debug(f"Embedding took too long ({elapsed_ms:.0f}ms), skipping recall")
            return []
        
        from backend import db_postgres as db
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            
            embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
            
            exclude_clause = ""
            params = [embedding_str, k + len(exclude_ids)]
            
            if exclude_ids:
                placeholders = ",".join(["%s"] * len(exclude_ids))
                exclude_clause = f"AND pe.page_id NOT IN ({placeholders})"
                params = [embedding_str] + list(exclude_ids) + [k]
            
            cursor.execute(f"""
                SELECT 
                    pe.page_id,
                    dp.document_id,
                    dp.page_number,
                    dp.text,
                    d.case_name,
                    d.appeal_number,
                    d.release_date,
                    d.pdf_url,
                    d.author_judge,
                    1 - (pe.embedding <=> %s::vector) as similarity
                FROM page_embeddings pe
                JOIN document_pages dp ON pe.page_id = dp.id
                JOIN documents d ON dp.document_id = d.id
                WHERE d.is_precedential = TRUE
                {exclude_clause}
                ORDER BY pe.embedding <=> %s::vector
                LIMIT %s
            """, params + [embedding_str, k])
            
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                results.append({
                    "id": row["page_id"],
                    "document_id": row["document_id"],
                    "page_number": row["page_number"],
                    "text": row["text"][:2000] if row["text"] else "",
                    "case_name": row["case_name"],
                    "appeal_number": row["appeal_number"],
                    "release_date": row["release_date"],
                    "pdf_url": row["pdf_url"],
                    "author_judge": row["author_judge"],
                    "score": row["similarity"],
                    "source": "embedding"
                })
            
            logger.debug(f"Semantic recall returned {len(results)} candidates in {(time.time() - start_time)*1000:.0f}ms")
            return results
            
    except Exception as e:
        logger.warning(f"Semantic recall failed: {e}")
        return []


def get_embedding_stats() -> Dict[str, Any]:
    """Get statistics about the embeddings table."""
    return check_embeddings_available()
