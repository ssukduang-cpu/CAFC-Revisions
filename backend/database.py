import sqlite3
import os
from contextlib import contextmanager
from typing import Optional, List, Dict, Any
import uuid
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cafc.db")

def get_db_path():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return DB_PATH

def init_db():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS opinions (
            id TEXT PRIMARY KEY,
            case_name TEXT NOT NULL,
            appeal_no TEXT NOT NULL,
            release_date TEXT NOT NULL,
            origin TEXT,
            document_type TEXT,
            status TEXT,
            pdf_url TEXT NOT NULL UNIQUE,
            ingested INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS opinion_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opinion_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            text TEXT NOT NULL,
            FOREIGN KEY (opinion_id) REFERENCES opinions(id),
            UNIQUE(opinion_id, page_number)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT DEFAULT 'New Research',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            citations TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='opinion_pages_fts'")
    if not cursor.fetchone():
        cursor.execute("""
            CREATE VIRTUAL TABLE opinion_pages_fts USING fts5(
                text,
                opinion_id UNINDEXED,
                page_number UNINDEXED,
                content='opinion_pages',
                content_rowid='id'
            )
        """)
        
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS opinion_pages_ai AFTER INSERT ON opinion_pages BEGIN
                INSERT INTO opinion_pages_fts(rowid, text, opinion_id, page_number)
                VALUES (new.id, new.text, new.opinion_id, new.page_number);
            END
        """)
        
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS opinion_pages_ad AFTER DELETE ON opinion_pages BEGIN
                INSERT INTO opinion_pages_fts(opinion_pages_fts, rowid, text, opinion_id, page_number)
                VALUES ('delete', old.id, old.text, old.opinion_id, old.page_number);
            END
        """)
        
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS opinion_pages_au AFTER UPDATE ON opinion_pages BEGIN
                INSERT INTO opinion_pages_fts(opinion_pages_fts, rowid, text, opinion_id, page_number)
                VALUES ('delete', old.id, old.text, old.opinion_id, old.page_number);
                INSERT INTO opinion_pages_fts(rowid, text, opinion_id, page_number)
                VALUES (new.id, new.text, new.opinion_id, new.page_number);
            END
        """)
    
    conn.commit()
    conn.close()

@contextmanager
def get_db():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def dict_from_row(row) -> Optional[Dict]:
    if row is None:
        return None
    return dict(row)

def get_status() -> Dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM opinions")
        total = cursor.fetchone()["total"]
        cursor.execute("SELECT COUNT(*) as ingested FROM opinions WHERE ingested = 1")
        ingested = cursor.fetchone()["ingested"]
        return {"status": "ok", "opinions": {"total": total, "ingested": ingested}}

def upsert_opinion(data: Dict) -> str:
    with get_db() as conn:
        cursor = conn.cursor()
        opinion_id = data.get("id") or str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        cursor.execute("SELECT id FROM opinions WHERE pdf_url = ?", (data["pdf_url"],))
        existing = cursor.fetchone()
        
        if existing:
            cursor.execute("""
                UPDATE opinions SET
                    case_name = ?, appeal_no = ?, release_date = ?, origin = ?,
                    document_type = ?, status = ?, updated_at = ?
                WHERE pdf_url = ?
            """, (
                data["case_name"], data["appeal_no"], data["release_date"],
                data.get("origin"), data.get("document_type"), data.get("status"),
                now, data["pdf_url"]
            ))
            opinion_id = existing["id"]
        else:
            cursor.execute("""
                INSERT INTO opinions (id, case_name, appeal_no, release_date, origin, document_type, status, pdf_url, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                opinion_id, data["case_name"], data["appeal_no"], data["release_date"],
                data.get("origin"), data.get("document_type"), data.get("status"),
                data["pdf_url"], now, now
            ))
        
        conn.commit()
        return opinion_id

def get_opinions(q: Optional[str] = None, origin: Optional[str] = None, ingested: Optional[bool] = None) -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM opinions WHERE 1=1"
        params = []
        
        if q:
            query += " AND case_name LIKE ?"
            params.append(f"%{q}%")
        if origin:
            query += " AND origin = ?"
            params.append(origin)
        if ingested is not None:
            query += " AND ingested = ?"
            params.append(1 if ingested else 0)
        
        query += " ORDER BY release_date DESC"
        cursor.execute(query, params)
        return [dict_from_row(row) for row in cursor.fetchall()]

def get_opinion(opinion_id: str) -> Optional[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM opinions WHERE id = ?", (opinion_id,))
        return dict_from_row(cursor.fetchone())

def insert_page(opinion_id: str, page_number: int, text: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO opinion_pages (opinion_id, page_number, text)
            VALUES (?, ?, ?)
        """, (opinion_id, page_number, text))
        conn.commit()

def mark_opinion_ingested(opinion_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("UPDATE opinions SET ingested = 1, updated_at = ? WHERE id = ?", (now, opinion_id))
        conn.commit()

def escape_fts_query(text: str) -> str:
    special_chars = ['?', '*', '+', '-', '(', ')', '{', '}', '[', ']', '^', '"', '~', ':', '\\', '.', ',', ';', '!', '@', '#', '$', '%', '&', '/', "'"]
    for char in special_chars:
        text = text.replace(char, ' ')
    return text

def search_pages(query: str, opinion_ids: Optional[List[str]] = None, limit: int = 20) -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        
        safe_query = escape_fts_query(query)
        words = [w.strip() for w in safe_query.split() if w.strip()]
        if not words:
            return []
        fts_query = " OR ".join(words)
        
        if opinion_ids:
            placeholders = ",".join("?" * len(opinion_ids))
            sql = f"""
                SELECT op.opinion_id, op.page_number, op.text,
                       o.case_name, o.appeal_no, o.release_date, o.pdf_url
                FROM opinion_pages_fts fts
                JOIN opinion_pages op ON fts.rowid = op.id
                JOIN opinions o ON op.opinion_id = o.id
                WHERE opinion_pages_fts MATCH ?
                AND op.opinion_id IN ({placeholders})
                ORDER BY rank
                LIMIT ?
            """
            params = [fts_query] + opinion_ids + [limit]
        else:
            sql = """
                SELECT op.opinion_id, op.page_number, op.text,
                       o.case_name, o.appeal_no, o.release_date, o.pdf_url
                FROM opinion_pages_fts fts
                JOIN opinion_pages op ON fts.rowid = op.id
                JOIN opinions o ON op.opinion_id = o.id
                WHERE o.ingested = 1 AND opinion_pages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """
            params = [fts_query, limit]
        
        cursor.execute(sql, params)
        return [dict_from_row(row) for row in cursor.fetchall()]

def create_conversation(title: str = "New Research") -> str:
    with get_db() as conn:
        cursor = conn.cursor()
        conv_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        cursor.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conv_id, title, now, now)
        )
        conn.commit()
        return conv_id

def get_conversations() -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM conversations ORDER BY updated_at DESC")
        return [dict_from_row(row) for row in cursor.fetchall()]

def get_conversation(conv_id: str) -> Optional[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
        return dict_from_row(cursor.fetchone())

def add_message(conv_id: str, role: str, content: str, citations: Optional[str] = None) -> str:
    with get_db() as conn:
        cursor = conn.cursor()
        msg_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        cursor.execute(
            "INSERT INTO messages (id, conversation_id, role, content, citations, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, conv_id, role, content, citations, now)
        )
        cursor.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))
        conn.commit()
        return msg_id

def get_messages(conv_id: str) -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at", (conv_id,))
        return [dict_from_row(row) for row in cursor.fetchall()]

def get_pages_for_opinion(opinion_id: str) -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM opinion_pages WHERE opinion_id = ? ORDER BY page_number",
            (opinion_id,)
        )
        return [dict_from_row(row) for row in cursor.fetchall()]

def check_fts_health() -> Dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) as count FROM opinion_pages")
            pages_count = cursor.fetchone()["count"]
            
            cursor.execute("SELECT COUNT(*) as count FROM opinion_pages_fts")
            fts_count = cursor.fetchone()["count"]
            
            cursor.execute("INSERT INTO opinion_pages_fts(opinion_pages_fts) VALUES('integrity-check')")
            
            return {
                "healthy": pages_count == fts_count,
                "pages_count": pages_count,
                "fts_count": fts_count,
                "synchronized": pages_count == fts_count,
                "message": "FTS5 index is healthy" if pages_count == fts_count else f"FTS index mismatch: {pages_count} pages vs {fts_count} FTS entries"
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "message": f"FTS5 health check failed: {e}"
            }
