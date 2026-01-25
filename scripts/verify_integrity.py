#!/usr/bin/env python3
"""
Integrity Verification Script

Validates database records against physical PDFs and re-queues missing files.
"""
import os
import sys
from typing import Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import db_postgres as db

PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "pdfs")


def log(msg: str):
    import time
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", file=sys.stderr)


def verify_pdf_integrity() -> Dict:
    """
    Check that all ingested documents have corresponding PDF files.
    Returns stats and list of missing files.
    """
    results = {
        "total_ingested": 0,
        "pdf_exists": 0,
        "pdf_missing": 0,
        "missing_ids": [],
        "orphaned_pdfs": []
    }
    
    log("Checking PDF integrity...")
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, case_name, file_path 
            FROM documents 
            WHERE ingested = TRUE
        """)
        
        ingested_docs = cursor.fetchall()
        results["total_ingested"] = len(ingested_docs)
        
        db_pdf_ids = set()
        
        for doc in ingested_docs:
            doc_id = str(doc["id"])
            db_pdf_ids.add(doc_id)
            
            pdf_path = os.path.join(PDF_DIR, f"{doc_id}.pdf")
            
            if os.path.exists(pdf_path):
                results["pdf_exists"] += 1
            else:
                results["pdf_missing"] += 1
                results["missing_ids"].append({
                    "id": doc_id,
                    "case_name": doc["case_name"]
                })
    
    if os.path.exists(PDF_DIR):
        for filename in os.listdir(PDF_DIR):
            if filename.endswith(".pdf"):
                pdf_id = filename.replace(".pdf", "")
                if pdf_id not in db_pdf_ids:
                    results["orphaned_pdfs"].append(filename)
    
    return results


def verify_chunk_integrity() -> Dict:
    """
    Verify that all ingested documents have chunks and pages.
    """
    results = {
        "total_ingested": 0,
        "with_chunks": 0,
        "without_chunks": 0,
        "with_pages": 0,
        "without_pages": 0,
        "missing_chunks_ids": [],
        "missing_pages_ids": []
    }
    
    log("Checking chunk/page integrity...")
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT d.id, d.case_name,
                   (SELECT COUNT(*) FROM document_chunks dc WHERE dc.document_id = d.id) as chunk_count,
                   (SELECT COUNT(*) FROM document_pages dp WHERE dp.document_id = d.id) as page_count
            FROM documents d
            WHERE d.ingested = TRUE
        """)
        
        for row in cursor.fetchall():
            results["total_ingested"] += 1
            
            if row["chunk_count"] > 0:
                results["with_chunks"] += 1
            else:
                results["without_chunks"] += 1
                results["missing_chunks_ids"].append({
                    "id": str(row["id"]),
                    "case_name": row["case_name"]
                })
            
            if row["page_count"] > 0:
                results["with_pages"] += 1
            else:
                results["without_pages"] += 1
                results["missing_pages_ids"].append({
                    "id": str(row["id"]),
                    "case_name": row["case_name"]
                })
    
    return results


def verify_fts_integrity() -> Dict:
    """
    Check FTS (Full-Text Search) index health.
    """
    results = {
        "chunks_with_fts": 0,
        "chunks_without_fts": 0,
        "total_chunks": 0,
        "sample_missing": [],
        "fts_available": True
    }
    
    log("Checking FTS index integrity...")
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) as cnt FROM document_chunks")
        results["total_chunks"] = cursor.fetchone()["cnt"]
        
        cursor.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'document_chunks' AND column_name = 'search_vector'
        """)
        has_search_vector = cursor.fetchone() is not None
        
        if not has_search_vector:
            log("Note: search_vector column not found - FTS uses text_content directly")
            results["fts_available"] = False
            results["chunks_with_fts"] = results["total_chunks"]
            return results
        
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM document_chunks 
            WHERE search_vector IS NOT NULL
        """)
        results["chunks_with_fts"] = cursor.fetchone()["cnt"]
        
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM document_chunks 
            WHERE search_vector IS NULL
        """)
        results["chunks_without_fts"] = cursor.fetchone()["cnt"]
        
        if results["chunks_without_fts"] > 0:
            cursor.execute("""
                SELECT dc.id, d.case_name 
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE dc.search_vector IS NULL
                LIMIT 5
            """)
            results["sample_missing"] = [
                {"chunk_id": row["id"], "case_name": row["case_name"]}
                for row in cursor.fetchall()
            ]
    
    return results


def requeue_missing_pdfs(missing_ids: List[str]) -> int:
    """
    Reset documents with missing PDFs so they can be re-ingested.
    """
    if not missing_ids:
        return 0
    
    log(f"Re-queuing {len(missing_ids)} documents with missing PDFs...")
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE documents 
            SET ingested = FALSE, last_error = NULL
            WHERE id = ANY(%s)
        """, (missing_ids,))
        conn.commit()
        return cursor.rowcount


def rebuild_fts_index() -> int:
    """
    Rebuild FTS vectors for chunks missing them.
    """
    log("Rebuilding FTS index for chunks missing search_vector...")
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'document_chunks' AND column_name = 'search_vector'
        """)
        has_search_vector = cursor.fetchone() is not None
        
        if not has_search_vector:
            log("search_vector column not found - FTS uses text_content directly")
            return 0
        
        cursor.execute("""
            UPDATE document_chunks 
            SET search_vector = to_tsvector('english', text_content)
            WHERE search_vector IS NULL AND text_content IS NOT NULL
        """)
        conn.commit()
        return cursor.rowcount


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Verify database and file integrity")
    parser.add_argument("--fix", action="store_true", help="Fix issues (requeue missing PDFs, rebuild FTS)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    
    args = parser.parse_args()
    
    print("\n=== CAFC Database Integrity Report ===\n")
    
    pdf_results = verify_pdf_integrity()
    print(f"PDF Files:")
    print(f"  Total ingested documents: {pdf_results['total_ingested']}")
    print(f"  PDFs present: {pdf_results['pdf_exists']}")
    print(f"  PDFs missing: {pdf_results['pdf_missing']}")
    print(f"  Orphaned PDFs: {len(pdf_results['orphaned_pdfs'])}")
    
    if args.verbose and pdf_results['missing_ids']:
        print(f"\n  Missing PDFs (first 10):")
        for item in pdf_results['missing_ids'][:10]:
            print(f"    - {item['case_name'][:50]}...")
    
    chunk_results = verify_chunk_integrity()
    print(f"\nChunks/Pages:")
    print(f"  Documents with chunks: {chunk_results['with_chunks']}")
    print(f"  Documents without chunks: {chunk_results['without_chunks']}")
    print(f"  Documents with pages: {chunk_results['with_pages']}")
    print(f"  Documents without pages: {chunk_results['without_pages']}")
    
    fts_results = verify_fts_integrity()
    print(f"\nFull-Text Search:")
    print(f"  Chunks with FTS index: {fts_results['chunks_with_fts']}")
    print(f"  Chunks missing FTS index: {fts_results['chunks_without_fts']}")
    
    if args.fix:
        print("\n=== Fixing Issues ===\n")
        
        if pdf_results['missing_ids']:
            missing_ids = [item['id'] for item in pdf_results['missing_ids']]
            requeued = requeue_missing_pdfs(missing_ids)
            print(f"Re-queued {requeued} documents for re-ingestion")
        
        if fts_results['chunks_without_fts'] > 0:
            rebuilt = rebuild_fts_index()
            print(f"Rebuilt FTS index for {rebuilt} chunks")
    
    issues = (
        pdf_results['pdf_missing'] + 
        chunk_results['without_chunks'] + 
        fts_results['chunks_without_fts']
    )
    
    print(f"\n=== Summary ===")
    if issues == 0:
        print("All integrity checks passed!")
    else:
        print(f"Found {issues} total issues")
        if not args.fix:
            print("Run with --fix to attempt automatic repair")
    
    return 0 if issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
