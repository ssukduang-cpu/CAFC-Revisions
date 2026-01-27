#!/usr/bin/env python3
"""
Patch Missing Landmark Cases

Downloads PDFs from authoritative sources (Supreme Court, Library of Congress)
and runs OCR recovery on Markman and KSR - the two Big 5 cases with failed status.
"""

import os
import sys
import uuid
import asyncio
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

from ocr_recovery import (
    ocr_pdf_to_pages,
    upsert_document_pages,
    check_ocr_dependencies,
    MIN_RECOVERED_CHARS
)

DATABASE_URL = os.environ.get('DATABASE_URL')
PDF_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'pdfs')

LANDMARK_SOURCES = {
    "Markman": {
        "url": "https://tile.loc.gov/storage-services/service/ll/usrep/usrep517/usrep517370/usrep517370.pdf",
        "case_name_pattern": "%Markman%",
        "full_name": "Markman v. Westview Instruments, Inc., 517 U.S. 370 (1996)",
        "source": "Library of Congress"
    },
    "KSR": {
        "url": "https://www.supremecourt.gov/opinions/06pdf/04-1350.pdf",
        "case_name_pattern": "%KSR%",
        "full_name": "KSR International Co. v. Teleflex Inc., 550 U.S. 398 (2007)",
        "source": "Supreme Court"
    }
}


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def download_pdf(url: str, dest_path: str) -> bool:
    """Download PDF from URL to destination path."""
    try:
        print(f"  Downloading from: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; LegalResearchBot/1.0)'
        }
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, 'wb') as f:
            f.write(response.content)
        
        file_size = os.path.getsize(dest_path)
        print(f"  Downloaded: {file_size:,} bytes")
        return True
        
    except Exception as e:
        print(f"  Download failed: {e}")
        return False


def find_document(case_pattern: str) -> dict:
    """Find existing document record by case name pattern."""
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT id, case_name, status, pdf_url
        FROM documents
        WHERE case_name ILIKE %s
        ORDER BY 
            CASE WHEN status = 'failed' THEN 0 ELSE 1 END,
            case_name
        LIMIT 1
    """, (case_pattern,))
    
    result = cur.fetchone()
    conn.close()
    
    return dict(result) if result else None


def update_document_status(doc_id: str, status: str, pdf_url: str = None):
    """Update document status after patching."""
    conn = get_connection()
    cur = conn.cursor()
    
    if pdf_url:
        cur.execute("""
            UPDATE documents
            SET status = %s, pdf_url = %s
            WHERE id = %s
        """, (status, pdf_url, doc_id))
    else:
        cur.execute("""
            UPDATE documents
            SET status = %s
            WHERE id = %s
        """, (status, doc_id))
    
    conn.commit()
    conn.close()


def patch_landmark(name: str, config: dict) -> dict:
    """Download and OCR a single landmark case."""
    print(f"\n{'='*60}")
    print(f"Patching: {name}")
    print(f"Source: {config['source']}")
    print(f"{'='*60}")
    
    doc = find_document(config['case_name_pattern'])
    
    if not doc:
        print(f"  WARNING: No document found matching '{config['case_name_pattern']}'")
        return {'success': False, 'error': 'Document not found'}
    
    print(f"  Found: {doc['case_name']}")
    print(f"  Current status: {doc['status']}")
    print(f"  Document ID: {doc['id']}")
    
    pdf_path = os.path.join(PDF_DIR, f"{doc['id']}.pdf")
    
    if not download_pdf(config['url'], pdf_path):
        return {'success': False, 'error': 'Download failed'}
    
    print(f"  Running OCR extraction...")
    pages = ocr_pdf_to_pages(pdf_path)
    
    if not pages:
        return {'success': False, 'error': 'OCR extraction failed'}
    
    total_chars = sum(len(p) for p in pages)
    print(f"  Extracted {len(pages)} pages, {total_chars:,} characters")
    
    result = upsert_document_pages(str(doc['id']), pages)
    
    if result.get('success'):
        status = result.get('status', 'recovered')
        update_document_status(str(doc['id']), status, config['url'])
        print(f"  SUCCESS: Updated to status '{status}'")
        return {
            'success': True,
            'pages': len(pages),
            'chars': total_chars,
            'status': status,
            'doc_id': str(doc['id']),
            'case_name': doc['case_name']
        }
    else:
        return {'success': False, 'error': result.get('error', 'Unknown error')}


def patch_all_landmarks():
    """Patch all missing landmark cases."""
    deps = check_ocr_dependencies()
    if not deps['available']:
        print("ERROR: OCR dependencies not available:")
        for err in deps['errors']:
            print(f"  - {err}")
        return
    
    print("="*60)
    print("LANDMARK CASE PATCHING")
    print("="*60)
    print(f"Cases to patch: {', '.join(LANDMARK_SOURCES.keys())}")
    
    results = {}
    for name, config in LANDMARK_SOURCES.items():
        results[name] = patch_landmark(name, config)
    
    print("\n" + "="*60)
    print("PATCH SUMMARY")
    print("="*60)
    
    for name, result in results.items():
        if result.get('success'):
            print(f"  {name}: SUCCESS - {result['pages']} pages, {result['chars']:,} chars")
        else:
            print(f"  {name}: FAILED - {result.get('error', 'Unknown error')}")
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Patch missing landmark cases")
    parser.add_argument("--case", type=str, choices=list(LANDMARK_SOURCES.keys()),
                        help="Patch a specific case only")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check what would be patched without making changes")
    
    args = parser.parse_args()
    
    if args.dry_run:
        print("DRY RUN - Checking landmark case status:")
        for name, config in LANDMARK_SOURCES.items():
            doc = find_document(config['case_name_pattern'])
            if doc:
                print(f"  {name}: {doc['case_name']} (status: {doc['status']})")
            else:
                print(f"  {name}: NOT FOUND")
    elif args.case:
        config = LANDMARK_SOURCES[args.case]
        patch_landmark(args.case, config)
    else:
        patch_all_landmarks()
