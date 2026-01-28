import os
import re
import uuid
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from typing import Optional, List, Dict, Any
from datetime import datetime
import hashlib

DATABASE_URL = os.environ.get("DATABASE_URL")

# Legal stop words that add noise to FTS queries
LEGAL_STOP_WORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
    'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been', 'be', 'have', 'has', 'had',
    'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must',
    'this', 'that', 'these', 'those', 'it', 'its', 'they', 'their', 'what', 'which',
    'who', 'whom', 'how', 'when', 'where', 'why', 'if', 'then', 'so', 'than', 'such',
    'can', 'only', 'other', 'into', 'over', 'under', 'between', 'through', 'during',
    'before', 'after', 'above', 'below', 'up', 'down', 'out', 'off', 'about', 'each',
    'explain', 'specifically', 'contrast', 'compare', 'describe', 'current', 'legal'
}

# High-value legal terms to prioritize in search
LEGAL_KEY_TERMS = {
    # Patent doctrines
    'enablement', 'obviousness', 'anticipation', 'infringement', 'claim', 'claims',
    'construction', 'patent', 'patentability', 'novelty', 'scope', 'prior', 'art',
    'specification', 'prosecution', 'estoppel', 'doctrine', 'equivalents', 'literal',
    'written', 'description', 'indefiniteness', 'abstract', 'idea', 'eligibility',
    # Key tests and factors
    'wands', 'factors', 'alice', 'mayo', 'ksr', 'phillips', 'markman', 'nautilus',
    'experimentation', 'undue', 'genus', 'species', 'functional', 'structural',
    # Case names (important landmarks)
    'amgen', 'sanofi', 'honeywell', 'athena', 'diagnostics', 'berkheimer',
    'enfish', 'bilski', 'electric', 'ddr', 'ariosa', 'myriad',
    # Obviousness specific
    'desirable', 'optimal', 'modification', 'motivation', 'combine', 'teaching',
    'suggestion', 'rationale', 'predictable', 'reasonable', 'expectation',
    # Alice/101 specific
    'inventive', 'concept', 'preemption', 'significantly', 'conventional', 'routine',
    'improvement', 'technical', 'computer', 'software', 'implementation'
}


def extract_search_terms(query: str, max_terms: int = 8) -> List[str]:
    """Extract key legal terms from a complex query.
    
    For long queries (>100 chars), extracts the most relevant legal terms.
    
    Args:
        query: Original search query
        max_terms: Maximum number of terms to include
        
    Returns:
        List of extracted key terms
    """
    # Tokenize and clean
    words = re.findall(r'[a-zA-Z]+', query.lower())
    
    if len(query) < 100:
        # For short queries, just filter stop words
        terms = [w for w in words if w not in LEGAL_STOP_WORDS and len(w) > 2]
        return terms[:max_terms]
    
    # Prioritize legal key terms for long queries
    key_matches = [w for w in words if w in LEGAL_KEY_TERMS]
    other_words = [w for w in words if w not in LEGAL_STOP_WORDS and w not in LEGAL_KEY_TERMS and len(w) > 2]
    
    # Combine: key terms first, then other significant words
    terms = key_matches[:max_terms]
    remaining_slots = max_terms - len(terms)
    if remaining_slots > 0:
        terms.extend(other_words[:remaining_slots])
    
    logging.debug(f"[FTS] Query extraction: {len(query)} chars -> {terms}")
    return terms[:max_terms]


def build_or_tsquery(terms: List[str]) -> str:
    """Build an OR-based tsquery string from a list of terms.
    
    Creates a query like: enablement | obviousness | amgen
    This matches pages containing ANY of the terms, not ALL.
    """
    if not terms:
        return ""
    # Escape any special characters and join with OR
    clean_terms = [re.sub(r'[^\w]', '', t) for t in terms if t.strip()]
    return ' | '.join(clean_terms)

# Global connection pool (initialize once, reuse connections)
_pool = None

def get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL environment variable is not set")
        _pool = ThreadedConnectionPool(1, 10, DATABASE_URL, cursor_factory=RealDictCursor)
    return _pool

@contextmanager
def get_db():
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

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
                status TEXT DEFAULT 'pending',
                file_path TEXT,
                ingested BOOLEAN DEFAULT FALSE,
                pdf_sha256 TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                last_error TEXT,
                courtlistener_cluster_id INTEGER,
                courtlistener_url TEXT,
                error_message TEXT,
                total_pages INTEGER,
                file_size INTEGER
            )
        """)
        
        cursor.execute("""
            ALTER TABLE documents 
            ADD COLUMN IF NOT EXISTS error_message TEXT,
            ADD COLUMN IF NOT EXISTS total_pages INTEGER,
            ADD COLUMN IF NOT EXISTS file_size INTEGER
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_cluster_id 
            ON documents(courtlistener_cluster_id) WHERE courtlistener_cluster_id IS NOT NULL
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_status 
            ON documents(status)
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
        
        # Add unique constraint for ON CONFLICT to work
        # First remove any duplicate rows that would prevent constraint creation
        cursor.execute("""
            DELETE FROM document_chunks a USING (
                SELECT document_id, chunk_index, MAX(id) as max_id
                FROM document_chunks 
                GROUP BY document_id, chunk_index 
                HAVING COUNT(*) > 1
            ) b
            WHERE a.document_id = b.document_id 
              AND a.chunk_index = b.chunk_index 
              AND a.id < b.max_id
        """)
        
        cursor.execute("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'document_chunks_document_id_chunk_index_key'
                ) THEN
                    ALTER TABLE document_chunks ADD CONSTRAINT document_chunks_document_id_chunk_index_key 
                    UNIQUE (document_id, chunk_index);
                END IF;
            END $$;
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_ingested 
            ON documents(ingested)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_document_pages_document_id 
            ON document_pages(document_id)
        """)
        
        # Trigram extension and index for fast case name searches
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_case_name_trgm 
            ON documents USING gin (case_name gin_trgm_ops)
        """)
        
        # Add generated tsvector column to document_pages for fast full-text search
        cursor.execute("""
            ALTER TABLE document_pages 
            ADD COLUMN IF NOT EXISTS text_search_vector TSVECTOR 
            GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED
        """)
        
        # GIN index on the pages vector for fast searches
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_document_pages_fts_vector 
            ON document_pages USING GIN(text_search_vector)
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                title TEXT DEFAULT 'New Research',
                pending_disambiguation JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cursor.execute("""
            ALTER TABLE conversations 
            ADD COLUMN IF NOT EXISTS pending_disambiguation JSONB
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
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS web_search_ingests (
                id BIGSERIAL PRIMARY KEY,
                document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
                case_name TEXT,
                cluster_id INTEGER,
                search_query TEXT,
                ingested_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_web_search_ingests_ingested_at 
            ON web_search_ingests(ingested_at DESC)
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
    offset: int = 0,
    author: Optional[str] = None,
    include_r36: bool = True,
    year: Optional[int] = None
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
        if author:
            query += " AND author_judge = %s"
            params.append(author)
        if not include_r36:
            query += " AND (is_rule_36 = FALSE OR is_rule_36 IS NULL)"
        if year:
            query += " AND EXTRACT(YEAR FROM release_date) = %s"
            params.append(year)
        
        query += " ORDER BY release_date DESC NULLS LAST LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

def get_documents_count(
    q: Optional[str] = None,
    origin: Optional[str] = None,
    ingested: Optional[bool] = None,
    author: Optional[str] = None,
    include_r36: bool = True,
    year: Optional[int] = None
) -> int:
    """Get count of documents matching the given filters."""
    with get_db() as conn:
        cursor = conn.cursor()
        query = "SELECT COUNT(*) as count FROM documents WHERE 1=1"
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
        if author:
            query += " AND author_judge = %s"
            params.append(author)
        if not include_r36:
            query += " AND (is_rule_36 = FALSE OR is_rule_36 IS NULL)"
        if year:
            query += " AND EXTRACT(YEAR FROM release_date) = %s"
            params.append(year)
        
        cursor.execute(query, params)
        return cursor.fetchone()["count"]

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

def insert_page(doc_id: str, page_number: int, text: str, cursor=None):
    if cursor:
        cursor.execute("""
            INSERT INTO document_pages (document_id, page_number, text)
            VALUES (%s, %s, %s)
            ON CONFLICT (document_id, page_number) DO UPDATE SET text = EXCLUDED.text
        """, (doc_id, page_number, text))
    else:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO document_pages (document_id, page_number, text)
                VALUES (%s, %s, %s)
                ON CONFLICT (document_id, page_number) DO UPDATE SET text = EXCLUDED.text
            """, (doc_id, page_number, text))

def insert_chunk(doc_id: str, chunk_index: int, page_start: int, page_end: int, text: str, cursor=None):
    if cursor:
        cursor.execute("""
            INSERT INTO document_chunks (document_id, chunk_index, page_start, page_end, text, text_search_vector)
            VALUES (%s, %s, %s, %s, %s, to_tsvector('english', %s))
            ON CONFLICT (document_id, chunk_index) DO UPDATE SET 
                page_start = EXCLUDED.page_start, page_end = EXCLUDED.page_end, 
                text = EXCLUDED.text, text_search_vector = EXCLUDED.text_search_vector
        """, (doc_id, chunk_index, page_start, page_end, text, text))
    else:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO document_chunks (document_id, chunk_index, page_start, page_end, text, text_search_vector)
                VALUES (%s, %s, %s, %s, %s, to_tsvector('english', %s))
                ON CONFLICT (document_id, chunk_index) DO UPDATE SET 
                    page_start = EXCLUDED.page_start, page_end = EXCLUDED.page_end, 
                    text = EXCLUDED.text, text_search_vector = EXCLUDED.text_search_vector
            """, (doc_id, chunk_index, page_start, page_end, text, text))

def clear_document_content(doc_id: str, cursor=None):
    if cursor:
        cursor.execute("DELETE FROM document_pages WHERE document_id = %s", (doc_id,))
        cursor.execute("DELETE FROM document_chunks WHERE document_id = %s", (doc_id,))
    else:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM document_pages WHERE document_id = %s", (doc_id,))
            cur.execute("DELETE FROM document_chunks WHERE document_id = %s", (doc_id,))

def count_document_chunks(doc_id: str) -> int:
    """Count the number of chunks for a document by ID. Returns 0 if none."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM document_chunks WHERE document_id = %s", (doc_id,))
        row = cur.fetchone()
        return row[0] if row else 0

def save_page_immediately(doc_id: str, page_number: int, text: str):
    """Insert a page and commit immediately. Resilient to Replit throttling."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO document_pages (document_id, page_number, text)
            VALUES (%s, %s, %s)
            ON CONFLICT (document_id, page_number) DO UPDATE SET text = EXCLUDED.text
        """, (doc_id, page_number, text))
        conn.commit()

def save_chunk_immediately(doc_id: str, chunk_index: int, page_start: int, page_end: int, text: str):
    """Insert a chunk and commit immediately. Resilient to Replit throttling."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO document_chunks (document_id, chunk_index, page_start, page_end, text, text_search_vector)
            VALUES (%s, %s, %s, %s, %s, to_tsvector('english', %s))
            ON CONFLICT (document_id, chunk_index) DO UPDATE SET 
                page_start = EXCLUDED.page_start, page_end = EXCLUDED.page_end, 
                text = EXCLUDED.text, text_search_vector = EXCLUDED.text_search_vector
        """, (doc_id, chunk_index, page_start, page_end, text, text))
        conn.commit()

def ingest_document_atomic(doc_id: str, pages: list, chunks: list, pdf_sha256: Optional[str] = None, file_size: int = 0):
    """
    Optimized for Replit: Saves each page and chunk immediately.
    If the process is throttled or killed, progress is preserved.
    """
    try:
        # 1. Clear previous attempts to ensure a clean slate for this specific ID
        clear_document_content(doc_id)
        
        # 2. Save each page as a discrete, committed transaction
        for page_num, text in enumerate(pages, 1):
            save_page_immediately(doc_id, page_num, text)
            
        # 3. Save each chunk as a discrete, committed transaction
        for chunk in chunks:
            save_chunk_immediately(
                doc_id, 
                chunk["chunk_index"], 
                chunk["page_start"], 
                chunk["page_end"], 
                chunk["text"]
            )
            
        # 4. Finalize the document record only after content is verified
        mark_document_ingested(doc_id, pdf_sha256, len(pages), file_size)
        
    except Exception as e:
        # Log the error but don't rollback—pages already saved stay saved
        mark_document_error(doc_id, f"Incremental ingestion failed: {str(e)}")
        raise e

def mark_document_ingested(doc_id: str, pdf_sha256: Optional[str] = None, total_pages: int = 0, file_size: int = 0, status: str = 'completed'):
    """
    Mark a document as ingested with a specific status.
    
    Statuses:
    - 'completed': Full precedential opinion
    - 'errata': Errata/erratum correction document
    - 'summary_affirmance': Rule 36 or summary affirmance (no substantive opinion)
    - 'order': Court order (not an opinion)
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE documents SET 
                ingested = TRUE, 
                pdf_sha256 = %s, 
                updated_at = NOW(), 
                last_error = NULL,
                status = %s,
                error_message = NULL,
                total_pages = %s,
                file_size = %s
            WHERE id = %s
        """, (pdf_sha256, status, total_pages, file_size, doc_id))

def fetch_controlling_scotus_pages(case_name_patterns: List[str], pages_per_case: int = 3) -> List[Dict]:
    """Fetch representative pages from controlling SCOTUS cases for candidate injection.
    
    This ensures controlling SCOTUS cases are included in the candidate pool for
    doctrine-tagged queries, even if their text doesn't match lexically.
    
    Args:
        case_name_patterns: List of case name patterns (e.g., ["Alice Corp. v. CLS Bank"])
        pages_per_case: Number of pages to fetch per case (default 3 for key reasoning)
    
    Returns:
        List of page dicts with document metadata
    """
    if not case_name_patterns:
        return []
    
    results = []
    with get_db() as conn:
        cursor = conn.cursor()
        
        for pattern in case_name_patterns:
            # Use ILIKE for case-insensitive partial matching
            pattern_lower = pattern.lower()
            
            # First, find the document
            cursor.execute("""
                SELECT d.id, d.case_name, d.appeal_number, d.release_date, d.origin
                FROM documents d
                WHERE d.ingested = TRUE
                  AND LOWER(d.case_name) LIKE %s
                ORDER BY d.release_date DESC
                LIMIT 1
            """, (f"%{pattern_lower}%",))
            
            doc_row = cursor.fetchone()
            if not doc_row:
                continue
            
            doc_id = doc_row["id"]
            
            # Fetch representative pages - skip slip opinion formatting and get content pages
            # SCOTUS slip opinions often have 10+ pages of whitespace, so get pages 10-12
            # which typically contain the core analysis (Mayo framework, etc.)
            cursor.execute("""
                SELECT dp.id, dp.document_id, dp.page_number, dp.text
                FROM document_pages dp
                WHERE dp.document_id = %s
                  AND dp.page_number >= 10
                ORDER BY dp.page_number
                LIMIT %s
            """, (doc_id, pages_per_case))
            
            pages = cursor.fetchall()
            
            for page in pages:
                results.append({
                    "opinion_id": str(doc_id),
                    "case_name": doc_row["case_name"],
                    "appeal_no": doc_row["appeal_number"],  # Match expected field name
                    "release_date": str(doc_row["release_date"]) if doc_row["release_date"] else None,
                    "origin": doc_row["origin"],
                    "page_number": page["page_number"],
                    "text": page["text"],
                    "rank": 1.0,  # High rank for injected controlling cases
                    "injected_as_controlling": True  # Signal that this was injected
                })
    
    return results


def mark_document_error(doc_id: str, error: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE documents SET 
                last_error = %s, 
                updated_at = NOW(),
                status = 'failed',
                error_message = %s
            WHERE id = %s
        """, (error, error, doc_id))

def mark_document_processing(doc_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE documents SET 
                status = 'processing',
                updated_at = NOW()
            WHERE id = %s
        """, (doc_id,))

def cleanup_stale_processing(timeout_minutes: int = 20) -> int:
    """Reset documents stuck in 'processing' for longer than timeout_minutes."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE documents 
            SET status = 'failed', error_message = 'Ingestion timed out or process killed'
            WHERE status = 'processing' 
              AND updated_at < NOW() - INTERVAL '%s minutes'
        """, (timeout_minutes,))
        count = cursor.rowcount
        conn.commit()
        return count

def get_pages_for_document(doc_id: str) -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM document_pages
            WHERE document_id = %s
            ORDER BY page_number
        """, (doc_id,))
        return [dict(row) for row in cursor.fetchall()]


def get_page_text(opinion_id: str, page_number: int) -> Optional[Dict]:
    """Fetch a single page and its document metadata by opinion_id and page_number."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                p.document_id as opinion_id,
                p.page_number,
                p.text,
                d.case_name,
                d.appeal_number as appeal_no,
                to_char(d.release_date, 'YYYY-MM-DD') as release_date,
                d.pdf_url,
                d.courtlistener_url
            FROM document_pages p
            JOIN documents d ON p.document_id = d.id
            WHERE p.document_id = %s AND p.page_number = %s
            LIMIT 1
        """, (opinion_id, page_number))
        row = cursor.fetchone()
        return dict(row) if row else None

def search_chunks(
    query: str, 
    limit: int = 20, 
    party_only: bool = False,
    author: Optional[str] = None,
    include_r36: bool = True
) -> List[Dict]:
    """Search chunks with case name boosting and optional filters.
    
    Args:
        query: Search query
        limit: Max results
        party_only: If True, only search case names (not full text)
        author: Filter by author judge name
        include_r36: If False, exclude Rule 36 judgments
    """
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Build dynamic filter conditions
        extra_filters = ""
        extra_params = []
        
        if author:
            extra_filters += " AND d.author_judge = %s"
            extra_params.append(author)
        
        if not include_r36:
            extra_filters += " AND (d.is_rule_36 = FALSE OR d.is_rule_36 IS NULL)"
        
        if party_only:
            # Party-only search: only match case names, not full opinion text
            sql = f"""
                SELECT DISTINCT ON (d.id)
                    c.id, c.document_id, c.chunk_index, c.page_start, c.page_end, c.text,
                    d.case_name, d.appeal_number, d.release_date, d.pdf_url,
                    d.author_judge, d.is_rule_36,
                    1.0 as rank
                FROM document_chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE d.ingested = TRUE 
                  AND d.case_name ILIKE '%%' || %s || '%%'
                  {extra_filters}
                ORDER BY d.id, c.chunk_index
                LIMIT %s
            """
            cursor.execute(sql, (query, *extra_params, limit))
        else:
            # Full text search with case name boosting
            sql = f"""
                SELECT 
                    c.id, c.document_id, c.chunk_index, c.page_start, c.page_end, c.text,
                    d.case_name, d.appeal_number, d.release_date, d.pdf_url,
                    d.author_judge, d.is_rule_36,
                    (
                        ts_rank(c.text_search_vector, plainto_tsquery('english', %s)) +
                        CASE WHEN d.case_name ILIKE '%%' || %s || '%%' THEN 10.0 ELSE 0.0 END
                    ) as rank
                FROM document_chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE d.ingested = TRUE 
                  AND (
                    c.text_search_vector @@ plainto_tsquery('english', %s)
                    OR d.case_name ILIKE '%%' || %s || '%%'
                  )
                  {extra_filters}
                ORDER BY rank DESC
                LIMIT %s
            """
            cursor.execute(sql, (query, query, query, query, *extra_params, limit))
        
        return [dict(row) for row in cursor.fetchall()]


def advanced_search(
    query: str,
    author: Optional[str] = None,
    forum: Optional[str] = None,
    exclude_r36: bool = False,
    cursor_token: Optional[str] = None,
    limit: int = 20
) -> Dict[str, Any]:
    """Advanced search with hybrid ranking, phrase/fuzzy support, and cursor pagination.
    
    Implements:
    - Hybrid ranking: ts_rank * recency_boost
    - Phrase search: quoted terms use phraseto_tsquery
    - Fuzzy matching: pg_trgm similarity on case_name
    - Keyset pagination: base64-encoded (timestamp, uuid) cursor
    
    Args:
        query: Search query (supports quoted phrases)
        author: Filter by author_judge
        forum: Filter by originating_forum
        exclude_r36: If True, exclude Rule 36 judgments
        cursor_token: Base64-encoded cursor for pagination
        limit: Max results per page
        
    Returns:
        Dict with results list and next_cursor
    """
    import base64
    import json
    import re
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Detect phrase queries (quoted strings)
        phrase_matches = re.findall(r'"([^"]+)"', query)
        clean_query = re.sub(r'"[^"]*"', '', query).strip()
        
        # Require at least one search condition
        if not clean_query and not phrase_matches:
            return {'results': [], 'next_cursor': None}
        
        # Build filter conditions
        filters = []
        params = []
        
        if author:
            filters.append("d.author_judge = %s")
            params.append(author)
        
        if forum:
            filters.append("d.originating_forum = %s")
            params.append(forum)
        
        if exclude_r36:
            filters.append("(d.is_rule_36 = FALSE OR d.is_rule_36 IS NULL)")
        
        filter_clause = (" AND " + " AND ".join(filters)) if filters else ""
        
        # Build search condition with phrase and fuzzy support
        search_conditions = []
        search_params = []
        
        # Full-text search on chunks
        if clean_query:
            search_conditions.append("c.text_search_vector @@ plainto_tsquery('english', %s)")
            search_params.append(clean_query)
        
        # Phrase search
        for phrase in phrase_matches:
            search_conditions.append("c.text_search_vector @@ phraseto_tsquery('english', %s)")
            search_params.append(phrase)
        
        # Fuzzy matching on case_name (pg_trgm)
        if clean_query:
            search_conditions.append("similarity(d.case_name, %s) > 0.2")
            search_params.append(clean_query)
        
        search_clause = " OR ".join(search_conditions)
        
        # Parse cursor for keyset pagination (score, release_date, id)
        cursor_score = None
        cursor_ts = None
        cursor_id = None
        if cursor_token:
            try:
                decoded = base64.b64decode(cursor_token).decode('utf-8')
                cursor_data_parsed = json.loads(decoded)
                cursor_score = cursor_data_parsed.get('score')
                cursor_ts = cursor_data_parsed.get('ts')
                cursor_id = cursor_data_parsed.get('id')
            except Exception:
                pass
        
        # Build cursor WHERE clause
        cursor_clause = ""
        cursor_params = []
        if cursor_score is not None and cursor_id:
            if cursor_ts:
                cursor_clause = "AND (hybrid_score, release_date, id::text) < (%s, %s::timestamp, %s)"
                cursor_params = [cursor_score, cursor_ts, cursor_id]
            else:
                cursor_clause = "AND (hybrid_score, id::text) < (%s, %s)"
                cursor_params = [cursor_score, cursor_id]
        
        # Main query with hybrid ranking
        # Formula: ts_rank * (1.0 / (days_old / 365 + 1)) + fuzzy_bonus
        sql = f"""
            WITH ranked_results AS (
                SELECT DISTINCT ON (d.id)
                    d.id,
                    d.case_name,
                    d.author_judge,
                    d.originating_forum,
                    d.is_rule_36,
                    d.release_date,
                    c.text,
                    c.page_start,
                    (
                        COALESCE(ts_rank(c.text_search_vector, plainto_tsquery('english', %s)), 0.01) 
                        * (1.0 / (GREATEST(EXTRACT(DAYS FROM (NOW() - COALESCE(d.release_date, NOW()))) / 365.0, 0) + 1))
                        + CASE WHEN similarity(d.case_name, %s) > 0.2 THEN 5.0 ELSE 0.0 END
                    ) as hybrid_score
                FROM document_chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE d.ingested = TRUE
                  AND ({search_clause})
                  {filter_clause}
                ORDER BY d.id, hybrid_score DESC
            )
            SELECT 
                id, case_name, author_judge, originating_forum, is_rule_36, 
                release_date, text as snippet, page_start, hybrid_score
            FROM ranked_results
            WHERE 1=1
              {cursor_clause}
            ORDER BY hybrid_score DESC, release_date DESC NULLS LAST, id DESC
            LIMIT %s
        """
        
        # Build params list
        base_params = [clean_query or phrase_matches[0], clean_query or phrase_matches[0]] + search_params + params + cursor_params
        base_params.append(limit + 1)
        
        cursor.execute(sql, tuple(base_params))
        rows = cursor.fetchall()
        
        results = []
        next_cursor = None
        
        for i, row in enumerate(rows):
            if i >= limit:
                # We got an extra row, so there's more data
                last_row = rows[limit - 1]
                cursor_data = {
                    'score': float(last_row.get('hybrid_score', 0)),
                    'ts': last_row['release_date'].isoformat() if last_row.get('release_date') else None,
                    'id': str(last_row['id'])
                }
                next_cursor = base64.b64encode(json.dumps(cursor_data).encode()).decode()
                break
            
            results.append({
                'id': str(row['id']),
                'case_name': row['case_name'],
                'author': row['author_judge'],
                'forum': row['originating_forum'],
                'is_rule_36': row['is_rule_36'],
                'highlights': (row.get('snippet') or '')[:300],
                'score': float(row.get('hybrid_score', 0))
            })
        
        return {
            'results': results,
            'next_cursor': next_cursor
        }


def normalize_case_name_query(query: str) -> str:
    """Normalize case name for flexible matching.
    
    Handles abbreviations like Corp./Corporation, Inc./Incorporated, etc.
    """
    import re
    # Remove trailing periods from abbreviations
    q = query.strip().rstrip('.')
    # Replace common abbreviations with patterns that match both forms
    # For ILIKE: we just need to use the shorter form without period
    q = re.sub(r'\bCorp\.?$', 'Corp', q)
    q = re.sub(r'\bInc\.?$', 'Inc', q)
    q = re.sub(r'\bCo\.?$', 'Co', q)
    q = re.sub(r'\bLtd\.?$', 'Ltd', q)
    q = re.sub(r'\bL\.?L\.?C\.?$', 'LLC', q)
    return q


def find_documents_by_name(case_name: str, limit: int = 5) -> List[str]:
    """Find document IDs that match a case name.
    
    Returns list of document ID strings for use in FTS queries.
    Improved: searches for both plaintiff AND defendant parts separately.
    """
    import re
    with get_db() as conn:
        cursor = conn.cursor()
        normalized = normalize_case_name_query(case_name)
        
        # First try exact substring match
        cursor.execute("""
            SELECT id::text
            FROM documents
            WHERE ingested = TRUE
              AND status NOT IN ('failed', 'duplicate')
              AND case_name ILIKE '%%' || %s || '%%'
            ORDER BY release_date DESC
            LIMIT %s
        """, (normalized, limit))
        results = [row['id'] for row in cursor.fetchall()]
        if results:
            return results
        
        # If no match, try splitting on " v. " and matching both parts
        if ' v. ' in case_name.lower():
            parts = re.split(r'\s+v\.?\s+', case_name, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                plaintiff = parts[0].strip()
                defendant = parts[1].strip()
                # Search for documents matching both plaintiff AND defendant
                cursor.execute("""
                    SELECT id::text
                    FROM documents
                    WHERE ingested = TRUE
                      AND status NOT IN ('failed', 'duplicate')
                      AND case_name ILIKE '%%' || %s || '%%'
                      AND case_name ILIKE '%%' || %s || '%%'
                    ORDER BY release_date DESC
                    LIMIT %s
                """, (plaintiff, defendant, limit))
                results = [row['id'] for row in cursor.fetchall()]
                if results:
                    return results
                
                # Try just the plaintiff name
                cursor.execute("""
                    SELECT id::text
                    FROM documents
                    WHERE ingested = TRUE
                      AND status NOT IN ('failed', 'duplicate')
                      AND case_name ILIKE '%%' || %s || '%%'
                    ORDER BY release_date DESC
                    LIMIT %s
                """, (plaintiff, limit))
                return [row['id'] for row in cursor.fetchall()]
        
        return []

def search_pages(query: str, opinion_ids: Optional[List[str]] = None, limit: int = 20, party_only: bool = False, max_text_chars: int = 2000) -> List[Dict]:
    """Search pages with case name boosting or party-only mode.
    
    Args:
        query: Search query
        opinion_ids: Optional list of specific opinion IDs to search within
        limit: Max results
        party_only: If True, only search case names (not full text)
        max_text_chars: Maximum characters to return per page text (prevents token bomb)
    """
    with get_db() as conn:
        cursor = conn.cursor()
        
        if not query.strip():
            return []
        
        # Normalize query for case name matching
        normalized_query = normalize_case_name_query(query) if party_only else query
        
        if opinion_ids and party_only:
            # Party-only search within specific opinions
            cursor.execute("""
                SELECT DISTINCT ON (d.id)
                    p.document_id as opinion_id, p.page_number, LEFT(p.text, %s) as text,
                    d.case_name, d.appeal_number as appeal_no, 
                    to_char(d.release_date, 'YYYY-MM-DD') as release_date, d.pdf_url,
                    d.courtlistener_url, d.origin,
                    1.0 as rank
                FROM document_pages p
                JOIN documents d ON p.document_id = d.id
                WHERE d.id::text = ANY(%s)
                  AND d.case_name ILIKE '%%' || %s || '%%'
                ORDER BY d.id, p.page_number
                LIMIT %s
            """, (max_text_chars, opinion_ids, normalized_query, limit))
        elif opinion_ids:
            # Full text search within specific opinions - uses pre-computed text_search_vector
            cursor.execute("""
                SELECT 
                    p.document_id as opinion_id, p.page_number, LEFT(p.text, %s) as text,
                    d.case_name, d.appeal_number as appeal_no, 
                    to_char(d.release_date, 'YYYY-MM-DD') as release_date, d.pdf_url,
                    d.courtlistener_url, d.origin,
                    ts_rank(p.text_search_vector, plainto_tsquery('english', %s)) as rank
                FROM document_pages p
                JOIN documents d ON p.document_id = d.id
                WHERE d.id::text = ANY(%s)
                  AND p.text_search_vector @@ plainto_tsquery('english', %s)
                ORDER BY rank DESC
                LIMIT %s
            """, (max_text_chars, query, opinion_ids, query, limit))
        elif party_only:
            # Party-only search: return multiple pages from matching cases
            # Return pages with FTS match if possible, otherwise first few pages
            cursor.execute("""
                WITH matched_docs AS (
                    SELECT d.id, d.case_name, d.appeal_number, d.release_date, 
                           d.pdf_url, d.courtlistener_url, d.origin
                    FROM documents d
                    WHERE d.ingested = TRUE 
                      AND d.case_name ILIKE '%%' || %s || '%%'
                    LIMIT 3
                )
                SELECT 
                    p.document_id as opinion_id, p.page_number, LEFT(p.text, %s) as text,
                    d.case_name, d.appeal_number as appeal_no, 
                    to_char(d.release_date, 'YYYY-MM-DD') as release_date, d.pdf_url,
                    d.courtlistener_url, d.origin,
                    1.0 as rank
                FROM document_pages p
                JOIN matched_docs d ON p.document_id = d.id
                WHERE p.page_number <= 10  -- First 10 pages of each matched case
                ORDER BY d.case_name, p.page_number
                LIMIT %s
            """, (normalized_query, max_text_chars, limit))
        else:
            # For long queries (>100 chars), extract key legal terms and use OR-based
            # matching to avoid over-restrictive AND queries that return 0 results
            terms = extract_search_terms(query, max_terms=8)
            or_query = build_or_tsquery(terms)
            logging.info(f"[FTS] Search: {len(query)} chars -> OR query: '{or_query}'")
            
            if or_query:
                # Use OR-based to_tsquery for flexible matching (ANY term matches)
                cursor.execute("""
                    SELECT 
                        p.document_id as opinion_id, p.page_number, LEFT(p.text, %s) as text,
                        d.case_name, d.appeal_number as appeal_no, 
                        to_char(d.release_date, 'YYYY-MM-DD') as release_date, d.pdf_url,
                        d.courtlistener_url, d.origin,
                        (
                            ts_rank(p.text_search_vector, to_tsquery('english', %s)) +
                            CASE WHEN d.case_name ILIKE '%%' || %s || '%%' THEN 10.0 ELSE 0.0 END
                        ) as rank
                    FROM document_pages p
                    JOIN documents d ON p.document_id = d.id
                    WHERE d.ingested = TRUE 
                      AND d.status = 'completed'
                      AND (
                        p.text_search_vector @@ to_tsquery('english', %s)
                        OR d.case_name ILIKE '%%' || %s || '%%'
                      )
                    ORDER BY rank DESC
                    LIMIT %s
                """, (max_text_chars, or_query, query, or_query, query, limit))
            else:
                # Fallback to case name search only
                cursor.execute("""
                    SELECT 
                        p.document_id as opinion_id, p.page_number, LEFT(p.text, %s) as text,
                        d.case_name, d.appeal_number as appeal_no, 
                        to_char(d.release_date, 'YYYY-MM-DD') as release_date, d.pdf_url,
                        d.courtlistener_url, d.origin,
                        1.0 as rank
                    FROM document_pages p
                    JOIN documents d ON p.document_id = d.id
                    WHERE d.ingested = TRUE 
                      AND d.status = 'completed'
                      AND d.case_name ILIKE '%%' || %s || '%%'
                    ORDER BY d.release_date DESC
                    LIMIT %s
                """, (max_text_chars, query, limit))
        
        return [dict(row) for row in cursor.fetchall()]


def search_pages_two_pass(
    query: str,
    limit: int = 20,
    max_text_chars: int = 2000
) -> List[Dict]:
    """Two-pass search: authoritative sources first, then all precedential.
    
    Pass 1: SCOTUS + CAFC en banc (authoritative)
    Pass 2: CAFC precedential + PTAB precedential
    
    Results are merged by composite_score and deduplicated by (opinion_id, page_number).
    """
    from backend import ranking_scorer
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        if not query.strip():
            return []
        
        terms = extract_search_terms(query, max_terms=8)
        or_query = build_or_tsquery(terms)
        
        if not or_query:
            return []
        
        all_results = []
        seen_keys = set()
        
        # PASS 1: Authoritative sources (SCOTUS + en banc)
        cursor.execute("""
            SELECT 
                p.document_id as opinion_id, p.page_number, LEFT(p.text, %s) as text,
                d.case_name, d.appeal_number as appeal_no, 
                to_char(d.release_date, 'YYYY-MM-DD') as release_date, d.pdf_url,
                d.courtlistener_url, d.origin, d.is_en_banc, d.is_precedential,
                ts_rank(p.text_search_vector, to_tsquery('english', %s)) as rank
            FROM document_pages p
            JOIN documents d ON p.document_id = d.id
            WHERE d.ingested = TRUE 
              AND d.status = 'completed'
              AND (d.origin = 'SCOTUS' OR d.is_en_banc = TRUE)
              AND p.text_search_vector @@ to_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT %s
        """, (max_text_chars, or_query, or_query, limit))
        
        for row in cursor.fetchall():
            page = dict(row)
            key = (page.get("opinion_id"), page.get("page_number"))
            if key not in seen_keys:
                seen_keys.add(key)
                explain = ranking_scorer.compute_composite_score(page.get("rank", 0.5), page, page.get("text", ""))
                page["explain"] = explain
                page["composite_score"] = explain.get("composite_score", 0)
                all_results.append(page)
        
        # PASS 2: All precedential CAFC/PTAB (explicitly filter precedential)
        cursor.execute("""
            SELECT 
                p.document_id as opinion_id, p.page_number, LEFT(p.text, %s) as text,
                d.case_name, d.appeal_number as appeal_no, 
                to_char(d.release_date, 'YYYY-MM-DD') as release_date, d.pdf_url,
                d.courtlistener_url, d.origin, d.is_en_banc, d.is_precedential,
                ts_rank(p.text_search_vector, to_tsquery('english', %s)) as rank
            FROM document_pages p
            JOIN documents d ON p.document_id = d.id
            WHERE d.ingested = TRUE 
              AND d.status = 'completed'
              AND d.origin != 'SCOTUS'
              AND (d.is_en_banc IS NULL OR d.is_en_banc = FALSE)
              AND (d.is_precedential IS NULL OR d.is_precedential = TRUE)
              AND p.text_search_vector @@ to_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT %s
        """, (max_text_chars, or_query, or_query, limit))
        
        for row in cursor.fetchall():
            page = dict(row)
            key = (page.get("opinion_id"), page.get("page_number"))
            if key not in seen_keys:
                seen_keys.add(key)
                explain = ranking_scorer.compute_composite_score(page.get("rank", 0.5), page, page.get("text", ""))
                page["explain"] = explain
                page["composite_score"] = explain.get("composite_score", 0)
                all_results.append(page)
        
        # Sort merged results by composite_score
        all_results.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
        
        return all_results[:limit]


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
        
        # Update conversation title if this is the first user message and title is still default
        if role == "user":
            cursor.execute("SELECT title FROM conversations WHERE id = %s", (conv_id,))
            row = cursor.fetchone()
            if row and row["title"] == "New Research":
                title = content[:60].strip()
                if len(content) > 60:
                    title += "..."
                cursor.execute("UPDATE conversations SET title = %s WHERE id = %s", (title, conv_id))
        
        return msg_id

def get_messages(conv_id: str) -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE conversation_id = %s ORDER BY created_at", (conv_id,))
        return [dict(row) for row in cursor.fetchall()]

def delete_conversation(conv_id: str) -> bool:
    """Delete a single conversation and its messages. Atomic operation."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM conversations WHERE id = %s", (conv_id,))
        if cursor.fetchone() is None:
            return False
        cursor.execute("DELETE FROM messages WHERE conversation_id = %s", (conv_id,))
        cursor.execute("DELETE FROM conversations WHERE id = %s", (conv_id,))
        return True

def clear_all_conversations() -> int:
    """Delete all conversations and their messages. Returns count of deleted conversations."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM conversations")
        count = cursor.fetchone()["count"]
        cursor.execute("DELETE FROM messages")
        cursor.execute("DELETE FROM conversations")
        return count

def set_pending_disambiguation(conv_id: str, candidates: List[Dict], original_query: str) -> None:
    """Store disambiguation candidates for a conversation."""
    import json
    data = {
        "pending": True,
        "candidates": candidates,
        "original_query": original_query,
        "created_at": datetime.utcnow().isoformat()
    }
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE conversations SET pending_disambiguation = %s WHERE id = %s",
            (json.dumps(data), conv_id)
        )

def get_pending_disambiguation(conv_id: str) -> Optional[Dict]:
    """Get pending disambiguation state for a conversation."""
    import json
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT pending_disambiguation FROM conversations WHERE id = %s", (conv_id,))
        row = cursor.fetchone()
        if row and row.get("pending_disambiguation"):
            data = row["pending_disambiguation"]
            if isinstance(data, str):
                data = json.loads(data)
            if data.get("pending"):
                return data
        return None

def clear_pending_disambiguation(conv_id: str) -> None:
    """Clear disambiguation state after resolution."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE conversations SET pending_disambiguation = NULL WHERE id = %s",
            (conv_id,)
        )

def get_ingestion_stats() -> Dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM documents")
        total = cursor.fetchone()["total"]
        cursor.execute("SELECT COUNT(*) as ingested FROM documents WHERE ingested = TRUE")
        ingested = cursor.fetchone()["ingested"]
        
        cursor.execute("""
            SELECT status, COUNT(*) as count 
            FROM documents 
            GROUP BY status
        """)
        status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}
        
        cursor.execute("SELECT SUM(page_count) as total_pages FROM (SELECT COUNT(*) as page_count FROM document_pages GROUP BY document_id) sub")
        total_pages_result = cursor.fetchone()
        total_pages = total_pages_result["total_pages"] or 0
        
        cursor.execute("""
            SELECT id, case_name, appeal_number, release_date, status, error_message, total_pages, updated_at
            FROM documents 
            WHERE status = 'failed'
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 20
        """)
        recent_failures = [dict(row) for row in cursor.fetchall()]
        
        return {
            "total_documents": total,
            "ingested": ingested,
            "pending": status_counts.get("pending", 0),
            "failed": status_counts.get("failed", 0),
            "completed": status_counts.get("completed", 0),
            "processing": status_counts.get("processing", 0),
            "status_breakdown": status_counts,
            "total_pages": total_pages,
            "percent_complete": round(ingested / total * 100, 1) if total > 0 else 0,
            "recent_failures": recent_failures
        }

def get_pending_documents(limit: int = 10) -> List[Dict]:
    """Get pending documents and mark them as processing to prevent duplicates."""
    with get_db() as conn:
        cursor = conn.cursor()
        # Use SELECT FOR UPDATE SKIP LOCKED to atomically claim documents
        # This prevents multiple workers from picking up the same documents
        # Order by cluster_id ASC to process older documents first (they have stored PDFs)
        cursor.execute("""
            WITH to_process AS (
                SELECT id FROM documents 
                WHERE ingested = FALSE 
                  AND (last_error IS NULL OR last_error = '')
                ORDER BY courtlistener_cluster_id ASC NULLS LAST
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            SELECT d.* FROM documents d
            JOIN to_process tp ON d.id = tp.id
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


def record_web_search_ingest(document_id: str, case_name: str, cluster_id: int, search_query: str) -> int:
    """Record a case that was discovered and ingested via web search."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO web_search_ingests (document_id, case_name, cluster_id, search_query)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (document_id, case_name, cluster_id, search_query))
        result = cursor.fetchone()
        return result["id"] if result else 0


def get_recent_web_search_ingests(limit: int = 10) -> List[Dict]:
    """Get recently ingested cases discovered via web search."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wsi.*, d.case_name as full_case_name, d.pdf_url
            FROM web_search_ingests wsi
            LEFT JOIN documents d ON wsi.document_id = d.id
            ORDER BY wsi.ingested_at DESC
            LIMIT %s
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def check_document_exists_by_cluster_id(cluster_id: int) -> Optional[Dict]:
    """Check if a document already exists by CourtListener cluster_id."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, case_name, ingested FROM documents 
            WHERE courtlistener_cluster_id = %s
        """, (cluster_id,))
        result = cursor.fetchone()
        return dict(result) if result else None

def get_pages_for_opinion(opinion_id: str) -> List[Dict]:
    return get_pages_for_document(opinion_id)


# Failure reason taxonomy for citation verification
FAILURE_REASONS = [
    "QUOTE_NOT_FOUND",
    "WRONG_CASE_ID",
    "WRONG_PAGE",
    "TOO_SHORT",
    "OCR_ARTIFACT_MISMATCH",
    "ELLIPSIS_FRAGMENT",
    "NORMALIZATION_MISMATCH",
    "NO_CANDIDATE_PASSAGES",
    "OTHER"
]


# Telemetry functions
def insert_telemetry(
    conversation_id: Optional[str],
    doctrine: Optional[str],
    total_citations: int,
    verified_citations: int,
    unsupported_statements: int,
    total_statements: int,
    latency_ms: Optional[int],
    binding_failure_reasons: Optional[str],
    mode: str = "STRICT",
    response_id: Optional[str] = None,
    propositions_total: int = 0,
    propositions_case_attributed: int = 0,
    propositions_unsupported: int = 0,
    propositions_case_attributed_unsupported: int = 0
) -> str:
    """Insert a telemetry record for citation verification metrics. Returns the telemetry ID."""
    telemetry_id = str(uuid.uuid4())
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO citation_telemetry 
            (id, conversation_id, doctrine, total_citations, verified_citations, 
             unsupported_statements, total_statements, latency_ms, binding_failure_reasons,
             mode, response_id, propositions_total, propositions_case_attributed,
             propositions_unsupported, propositions_case_attributed_unsupported)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            telemetry_id,
            conversation_id,
            doctrine,
            total_citations,
            verified_citations,
            unsupported_statements,
            total_statements,
            latency_ms,
            binding_failure_reasons,
            mode,
            response_id,
            propositions_total,
            propositions_case_attributed,
            propositions_unsupported,
            propositions_case_attributed_unsupported
        ))
        conn.commit()
    return telemetry_id


def insert_citation_verification_result(
    telemetry_id: str,
    response_id: Optional[str],
    citation_text: str,
    case_name: Optional[str],
    verified: bool,
    failure_reason: Optional[str]
):
    """Insert an individual citation verification result."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO citation_verification_results
            (id, telemetry_id, response_id, citation_text, case_name, verified, failure_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            str(uuid.uuid4()),
            telemetry_id,
            response_id,
            citation_text[:500] if citation_text else None,
            case_name,
            verified,
            failure_reason
        ))
        conn.commit()


def get_telemetry_records(start_date: datetime, end_date: datetime, mode: Optional[str] = None) -> List[Dict]:
    """Get telemetry records within a date range, optionally filtered by mode."""
    with get_db() as conn:
        cursor = conn.cursor()
        if mode:
            cursor.execute("""
                SELECT * FROM citation_telemetry 
                WHERE created_at >= %s AND created_at <= %s AND mode = %s
                ORDER BY created_at DESC
            """, (start_date, end_date, mode))
        else:
            cursor.execute("""
                SELECT * FROM citation_telemetry 
                WHERE created_at >= %s AND created_at <= %s
                ORDER BY created_at DESC
            """, (start_date, end_date))
        return [dict(row) for row in cursor.fetchall()]


def get_failure_reason_breakdown(start_date: datetime, end_date: datetime, mode: Optional[str] = None) -> List[Dict]:
    """Get breakdown of failure reasons."""
    with get_db() as conn:
        cursor = conn.cursor()
        if mode:
            cursor.execute("""
                SELECT cvr.failure_reason, COUNT(*) as count
                FROM citation_verification_results cvr
                JOIN citation_telemetry ct ON cvr.telemetry_id = ct.id
                WHERE ct.created_at >= %s AND ct.created_at <= %s 
                AND ct.mode = %s AND cvr.verified = FALSE
                GROUP BY cvr.failure_reason
                ORDER BY count DESC
            """, (start_date, end_date, mode))
        else:
            cursor.execute("""
                SELECT failure_reason, COUNT(*) as count
                FROM citation_verification_results
                WHERE verified = FALSE
                GROUP BY failure_reason
                ORDER BY count DESC
            """)
        return [dict(row) for row in cursor.fetchall()]


def get_failing_responses(doctrine: str, start_date: datetime, end_date: datetime, limit: int = 50) -> List[Dict]:
    """Get recent failing response IDs for a doctrine."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT ct.response_id, ct.created_at, ct.total_citations, ct.verified_citations
            FROM citation_telemetry ct
            WHERE ct.doctrine = %s 
            AND ct.created_at >= %s AND ct.created_at <= %s
            AND ct.verified_citations < ct.total_citations
            ORDER BY ct.created_at DESC
            LIMIT %s
        """, (doctrine, start_date, end_date, limit))
        return [dict(row) for row in cursor.fetchall()]


def get_latency_percentiles(start_date: datetime, end_date: datetime, mode: Optional[str] = None) -> Dict:
    """Get p50 and p95 latency percentiles."""
    with get_db() as conn:
        cursor = conn.cursor()
        if mode:
            cursor.execute("""
                SELECT 
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms) as p50,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) as p95
                FROM citation_telemetry
                WHERE created_at >= %s AND created_at <= %s 
                AND mode = %s AND latency_ms IS NOT NULL
            """, (start_date, end_date, mode))
        else:
            cursor.execute("""
                SELECT 
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms) as p50,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) as p95
                FROM citation_telemetry
                WHERE created_at >= %s AND created_at <= %s AND latency_ms IS NOT NULL
            """, (start_date, end_date))
        result = cursor.fetchone()
        return {"p50": result["p50"] or 0, "p95": result["p95"] or 0} if result else {"p50": 0, "p95": 0}
