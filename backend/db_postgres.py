import os
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from typing import Optional, List, Dict, Any
from datetime import datetime
import hashlib

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                pdf_url TEXT UNIQUE NOT NULL,
                case_name TEXT,
                appeal_number TEXT,
                release_date DATE,
                origin TEXT,
                document_type TEXT,
                status TEXT,
                file_path TEXT,
                ingested BOOLEAN DEFAULT FALSE,
                pdf_sha256 TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                last_error TEXT,
                courtlistener_cluster_id INTEGER,
                courtlistener_url TEXT
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_cluster_id 
            ON documents(courtlistener_cluster_id) WHERE courtlistener_cluster_id IS NOT NULL
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_pages (
                id BIGSERIAL PRIMARY KEY,
                document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                page_number INTEGER NOT NULL,
                text TEXT,
                UNIQUE(document_id, page_number)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id BIGSERIAL PRIMARY KEY,
                document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                page_start INTEGER,
                page_end INTEGER,
                text TEXT,
                text_search_vector TSVECTOR
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_document_chunks_fts 
            ON document_chunks USING GIN(text_search_vector)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_ingested 
            ON documents(ingested)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_document_pages_document_id 
            ON document_pages(document_id)
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                title TEXT DEFAULT 'New Research',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                citations TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conversation_id 
            ON messages(conversation_id)
        """)
        
        conn.commit()

def get_status() -> Dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM documents")
        total = cursor.fetchone()["total"]
        cursor.execute("SELECT COUNT(*) as ingested FROM documents WHERE ingested = TRUE")
        ingested = cursor.fetchone()["ingested"]
        return {"status": "ok", "opinions": {"total": total, "ingested": ingested}}

def upsert_document(data: Dict) -> str:
    with get_db() as conn:
        cursor = conn.cursor()
        doc_id = data.get("id") or str(uuid.uuid4())
        
        release_date = data.get("release_date")
        if release_date and isinstance(release_date, str):
            try:
                from dateutil import parser
                release_date = parser.parse(release_date).date()
            except:
                release_date = None
        
        cursor.execute("""
            INSERT INTO documents (
                id, pdf_url, case_name, appeal_number, release_date, 
                origin, document_type, status, file_path, courtlistener_cluster_id, courtlistener_url
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (pdf_url) DO UPDATE SET
                case_name = EXCLUDED.case_name,
                appeal_number = EXCLUDED.appeal_number,
                release_date = EXCLUDED.release_date,
                origin = EXCLUDED.origin,
                document_type = EXCLUDED.document_type,
                status = EXCLUDED.status,
                file_path = EXCLUDED.file_path,
                courtlistener_cluster_id = EXCLUDED.courtlistener_cluster_id,
                courtlistener_url = EXCLUDED.courtlistener_url,
                updated_at = NOW()
            RETURNING id
        """, (
            doc_id, data["pdf_url"], data.get("case_name"), data.get("appeal_number"),
            release_date, data.get("origin"), data.get("document_type"),
            data.get("status"), data.get("file_path"), data.get("courtlistener_cluster_id"),
            data.get("courtlistener_url")
        ))
        result = cursor.fetchone()
        return str(result["id"])

def get_documents(
    q: Optional[str] = None,
    origin: Optional[str] = None,
    ingested: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0
) -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM documents WHERE 1=1"
        params = []
        
        if q:
            query += " AND case_name ILIKE %s"
            params.append(f"%{q}%")
        if origin:
            query += " AND origin = %s"
            params.append(origin)
        if ingested is not None:
            query += " AND ingested = %s"
            params.append(ingested)
        
        query += " ORDER BY release_date DESC NULLS LAST LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

def get_document(doc_id: str) -> Optional[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE id = %s", (doc_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_document_by_url(pdf_url: str) -> Optional[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE pdf_url = %s", (pdf_url,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_document_by_cluster_id(cluster_id: int) -> Optional[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE courtlistener_cluster_id = %s", (cluster_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def document_exists_by_dedupe_key(cluster_id: Optional[int], appeal_number: Optional[str], pdf_url: Optional[str]) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        if cluster_id:
            cursor.execute("SELECT 1 FROM documents WHERE courtlistener_cluster_id = %s LIMIT 1", (cluster_id,))
            if cursor.fetchone():
                return True
        if appeal_number and pdf_url:
            cursor.execute("SELECT 1 FROM documents WHERE appeal_number = %s AND pdf_url = %s LIMIT 1", (appeal_number, pdf_url))
            if cursor.fetchone():
                return True
        return False

def insert_page(doc_id: str, page_number: int, text: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO document_pages (document_id, page_number, text)
            VALUES (%s, %s, %s)
            ON CONFLICT (document_id, page_number) DO UPDATE SET text = EXCLUDED.text
        """, (doc_id, page_number, text))

def insert_chunk(doc_id: str, chunk_index: int, page_start: int, page_end: int, text: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO document_chunks (document_id, chunk_index, page_start, page_end, text, text_search_vector)
            VALUES (%s, %s, %s, %s, %s, to_tsvector('english', %s))
        """, (doc_id, chunk_index, page_start, page_end, text, text))

def mark_document_ingested(doc_id: str, pdf_sha256: Optional[str] = None):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE documents SET ingested = TRUE, pdf_sha256 = %s, updated_at = NOW(), last_error = NULL
            WHERE id = %s
        """, (pdf_sha256, doc_id))

def mark_document_error(doc_id: str, error: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE documents SET last_error = %s, updated_at = NOW()
            WHERE id = %s
        """, (error, doc_id))

def get_pages_for_document(doc_id: str) -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM document_pages WHERE document_id = %s ORDER BY page_number
        """, (doc_id,))
        return [dict(row) for row in cursor.fetchall()]

def search_chunks(query: str, limit: int = 20) -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                c.id, c.document_id, c.chunk_index, c.page_start, c.page_end, c.text,
                d.case_name, d.appeal_number, d.release_date, d.pdf_url,
                ts_rank(c.text_search_vector, plainto_tsquery('english', %s)) as rank
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE d.ingested = TRUE 
              AND c.text_search_vector @@ plainto_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT %s
        """, (query, query, limit))
        return [dict(row) for row in cursor.fetchall()]

def search_pages(query: str, opinion_ids: Optional[List[str]] = None, limit: int = 20) -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        
        if not query.strip():
            return []
        
        if opinion_ids:
            cursor.execute("""
                SELECT 
                    p.document_id as opinion_id, p.page_number, p.text,
                    d.case_name, d.appeal_number as appeal_no, 
                    to_char(d.release_date, 'YYYY-MM-DD') as release_date, d.pdf_url,
                    ts_rank(to_tsvector('english', p.text), plainto_tsquery('english', %s)) as rank
                FROM document_pages p
                JOIN documents d ON p.document_id = d.id
                WHERE d.id = ANY(%s)
                  AND to_tsvector('english', p.text) @@ plainto_tsquery('english', %s)
                ORDER BY rank DESC
                LIMIT %s
            """, (query, opinion_ids, query, limit))
        else:
            cursor.execute("""
                SELECT 
                    p.document_id as opinion_id, p.page_number, p.text,
                    d.case_name, d.appeal_number as appeal_no, 
                    to_char(d.release_date, 'YYYY-MM-DD') as release_date, d.pdf_url,
                    ts_rank(to_tsvector('english', p.text), plainto_tsquery('english', %s)) as rank
                FROM document_pages p
                JOIN documents d ON p.document_id = d.id
                WHERE d.ingested = TRUE 
                  AND to_tsvector('english', p.text) @@ plainto_tsquery('english', %s)
                ORDER BY rank DESC
                LIMIT %s
            """, (query, query, limit))
        
        return [dict(row) for row in cursor.fetchall()]

def create_conversation(title: str = "New Research") -> str:
    with get_db() as conn:
        cursor = conn.cursor()
        conv_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO conversations (id, title) VALUES (%s, %s)",
            (conv_id, title)
        )
        return conv_id

def get_conversations() -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM conversations ORDER BY updated_at DESC")
        return [dict(row) for row in cursor.fetchall()]

def get_conversation(conv_id: str) -> Optional[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM conversations WHERE id = %s", (conv_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def add_message(conv_id: str, role: str, content: str, citations: Optional[str] = None) -> str:
    with get_db() as conn:
        cursor = conn.cursor()
        msg_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO messages (id, conversation_id, role, content, citations) VALUES (%s, %s, %s, %s, %s)",
            (msg_id, conv_id, role, content, citations)
        )
        cursor.execute("UPDATE conversations SET updated_at = NOW() WHERE id = %s", (conv_id,))
        return msg_id

def get_messages(conv_id: str) -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE conversation_id = %s ORDER BY created_at", (conv_id,))
        return [dict(row) for row in cursor.fetchall()]

def get_ingestion_stats() -> Dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM documents")
        total = cursor.fetchone()["total"]
        cursor.execute("SELECT COUNT(*) as ingested FROM documents WHERE ingested = TRUE")
        ingested = cursor.fetchone()["ingested"]
        cursor.execute("SELECT COUNT(*) as failed FROM documents WHERE last_error IS NOT NULL")
        failed = cursor.fetchone()["failed"]
        cursor.execute("SELECT SUM(page_count) as total_pages FROM (SELECT COUNT(*) as page_count FROM document_pages GROUP BY document_id) sub")
        total_pages_result = cursor.fetchone()
        total_pages = total_pages_result["total_pages"] or 0
        
        return {
            "total_documents": total,
            "ingested": ingested,
            "pending": total - ingested,
            "failed": failed,
            "total_pages": total_pages,
            "percent_complete": round(ingested / total * 100, 1) if total > 0 else 0
        }

def get_pending_documents(limit: int = 10) -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM documents 
            WHERE ingested = FALSE AND (last_error IS NULL OR last_error = '')
            ORDER BY release_date DESC NULLS LAST
            LIMIT %s
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

def check_fts_health() -> Dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) as count FROM document_pages")
            pages_count = cursor.fetchone()["count"]
            
            cursor.execute("SELECT COUNT(*) as count FROM document_chunks")
            chunks_count = cursor.fetchone()["count"]
            
            cursor.execute("SELECT COUNT(*) as count FROM document_chunks WHERE text_search_vector IS NOT NULL")
            indexed_count = cursor.fetchone()["count"]
            
            return {
                "healthy": indexed_count == chunks_count,
                "pages_count": pages_count,
                "chunks_count": chunks_count,
                "indexed_count": indexed_count,
                "message": "FTS index is healthy" if indexed_count == chunks_count else f"FTS index mismatch: {indexed_count}/{chunks_count} indexed"
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "message": f"FTS health check failed: {e}"
            }

def get_opinions(q: Optional[str] = None, origin: Optional[str] = None, ingested: Optional[bool] = None) -> List[Dict]:
    return get_documents(q=q, origin=origin, ingested=ingested)

def get_opinion(opinion_id: str) -> Optional[Dict]:
    return get_document(opinion_id)

def upsert_opinion(data: Dict) -> str:
    return upsert_document(data)

def get_pages_for_opinion(opinion_id: str) -> List[Dict]:
    return get_pages_for_document(opinion_id)
