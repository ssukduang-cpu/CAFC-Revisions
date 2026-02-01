"""
Embeddings Build CLI

Offline job to create embeddings for document pages.
Run this BEFORE enabling SMART_EMBED_RECALL_ENABLED.

Usage:
    python -m backend.smart.build_embeddings --limit 1000
    python -m backend.smart.build_embeddings --all
    python -m backend.smart.build_embeddings --stats
"""

import argparse
import logging
import sys
import time
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def ensure_embeddings_table():
    """Create page_embeddings table if it doesn't exist."""
    from backend import db_postgres as db
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'page_embeddings'
            )
        """)
        if cursor.fetchone()[0]:
            logger.info("page_embeddings table already exists")
            return True
        
        try:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.commit()
        except Exception as e:
            logger.warning(f"pgvector extension not available: {e}")
            logger.error("Cannot create embeddings table without pgvector extension")
            return False
        
        cursor.execute("""
            CREATE TABLE page_embeddings (
                page_id VARCHAR PRIMARY KEY REFERENCES document_pages(id),
                embedding vector(1536),
                model VARCHAR DEFAULT 'text-embedding-3-small',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        cursor.execute("""
            CREATE INDEX idx_page_embeddings_vector 
            ON page_embeddings USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """)
        
        conn.commit()
        logger.info("Created page_embeddings table with vector index")
        return True


def get_pages_without_embeddings(limit: Optional[int] = None):
    """Get pages that don't have embeddings yet."""
    from backend import db_postgres as db
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        
        limit_clause = f"LIMIT {limit}" if limit else ""
        
        cursor.execute(f"""
            SELECT dp.id, dp.text, d.case_name
            FROM document_pages dp
            JOIN documents d ON dp.document_id = d.id
            LEFT JOIN page_embeddings pe ON dp.id = pe.page_id
            WHERE pe.page_id IS NULL
            AND d.is_precedential = TRUE
            AND dp.text IS NOT NULL
            AND LENGTH(dp.text) > 100
            ORDER BY d.release_date DESC NULLS LAST
            {limit_clause}
        """)
        
        return cursor.fetchall()


def build_embeddings(limit: Optional[int] = None, batch_size: int = 50):
    """Build embeddings for pages that don't have them."""
    from backend.smart.embeddings import embed_text
    from backend import db_postgres as db
    
    if not ensure_embeddings_table():
        return {"success": False, "error": "Could not create embeddings table"}
    
    pages = get_pages_without_embeddings(limit)
    total = len(pages)
    
    if total == 0:
        logger.info("No pages need embeddings")
        return {"success": True, "processed": 0, "total": 0}
    
    logger.info(f"Building embeddings for {total} pages...")
    
    processed = 0
    failed = 0
    start_time = time.time()
    
    for i, page in enumerate(pages):
        page_id = page["id"]
        text = page["text"]
        
        try:
            embedding = embed_text(text[:8000])
            
            if embedding:
                with db.get_db() as conn:
                    cursor = conn.cursor()
                    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
                    cursor.execute("""
                        INSERT INTO page_embeddings (page_id, embedding)
                        VALUES (%s, %s::vector)
                        ON CONFLICT (page_id) DO UPDATE SET 
                            embedding = EXCLUDED.embedding,
                            created_at = NOW()
                    """, (page_id, embedding_str))
                    conn.commit()
                processed += 1
            else:
                failed += 1
                
        except Exception as e:
            logger.warning(f"Failed to embed page {page_id}: {e}")
            failed += 1
        
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            eta = (total - i - 1) / rate if rate > 0 else 0
            logger.info(f"Progress: {i+1}/{total} ({processed} ok, {failed} failed) - ETA: {eta/60:.1f}m")
        
        if (i + 1) % 1000 == 0:
            time.sleep(1)
    
    elapsed = time.time() - start_time
    logger.info(f"Completed: {processed}/{total} embeddings in {elapsed/60:.1f}m ({failed} failed)")
    
    return {
        "success": True,
        "processed": processed,
        "failed": failed,
        "total": total,
        "elapsed_seconds": int(elapsed)
    }


def get_stats():
    """Get embedding statistics."""
    from backend.smart.embeddings import check_embeddings_available
    return check_embeddings_available()


def main():
    parser = argparse.ArgumentParser(description="Build embeddings for document pages")
    parser.add_argument("--limit", type=int, help="Maximum pages to process")
    parser.add_argument("--all", action="store_true", help="Process all pages without limit")
    parser.add_argument("--stats", action="store_true", help="Show embedding statistics only")
    parser.add_argument("--ensure-table", action="store_true", help="Create table only, don't build embeddings")
    
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("EMBEDDINGS BUILD")
    print("=" * 60)
    
    if args.stats:
        stats = get_stats()
        print(f"\nEmbeddings Status:")
        print(f"  Available: {stats['available']}")
        print(f"  Count: {stats.get('count', 0)}")
        print(f"  Total Pages: {stats.get('total_pages', 0)}")
        print(f"  Coverage: {stats.get('coverage', 0):.1%}")
        print(f"  Reason: {stats['reason']}")
        return 0
    
    if args.ensure_table:
        if ensure_embeddings_table():
            print("Table ready")
            return 0
        else:
            print("Failed to create table")
            return 1
    
    limit = None if args.all else (args.limit or 100)
    
    print(f"\nBuilding embeddings (limit: {'all' if limit is None else limit})...")
    result = build_embeddings(limit=limit)
    
    print(f"\nResult: {result}")
    
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
