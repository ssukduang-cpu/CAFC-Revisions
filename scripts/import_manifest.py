#!/usr/bin/env python3
"""
Import manifest records into the database, enriching with PDF URLs from CourtListener.
"""

import os
import sys
import json
import time
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

SAMPLE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "manifest_sample.ndjson")
FULL_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "manifest.ndjson")

DATABASE_URL = os.environ.get("DATABASE_URL")
COURTLISTENER_TOKEN = os.environ.get("COURTLISTENER_API_TOKEN")


def get_pdf_url_from_courtlistener(cluster_id: int, session: requests.Session) -> dict:
    """Fetch opinion details from CourtListener to get PDF URL."""
    cluster_url = f"https://www.courtlistener.com/api/rest/v4/clusters/{cluster_id}/"
    
    for attempt in range(3):
        try:
            # First get cluster to find sub_opinions and docket
            resp = session.get(cluster_url, params={"fields": "sub_opinions,docket_id"}, timeout=30)
            if resp.status_code == 200:
                cluster_data = resp.json()
                docket_id = cluster_data.get("docket_id")
                sub_opinions = cluster_data.get("sub_opinions", [])
                
                # Get PDF URL from first opinion
                pdf_url = ""
                if sub_opinions:
                    opinion_url = sub_opinions[0]
                    op_resp = session.get(opinion_url, params={"fields": "download_url"}, timeout=30)
                    if op_resp.status_code == 200:
                        pdf_url = op_resp.json().get("download_url", "")
                
                return {
                    "pdf_url": pdf_url,
                    "docket_id": docket_id,
                }
            elif resp.status_code in (429, 502, 503):
                time.sleep(2 ** attempt)
            else:
                return {"pdf_url": "", "docket_id": None}
        except Exception as e:
            time.sleep(1)
    
    return {"pdf_url": "", "docket_id": None}


def get_docket_number(docket_id: int, session: requests.Session) -> str:
    """Fetch docket number (appeal number) from CourtListener."""
    if not docket_id:
        return ""
    
    url = f"https://www.courtlistener.com/api/rest/v4/dockets/{docket_id}/"
    
    for attempt in range(3):
        try:
            resp = session.get(url, params={"fields": "docket_number"}, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("docket_number", "")
            elif resp.status_code in (429, 502, 503):
                time.sleep(2 ** attempt)
            else:
                return ""
        except:
            time.sleep(1)
    
    return ""


def import_records(manifest_file: str, limit: int = None):
    print(f"Importing from: {manifest_file}")
    
    # Load records
    with open(manifest_file) as f:
        records = [json.loads(line) for line in f]
    
    if limit:
        records = records[:limit]
    
    print(f"  Loaded {len(records)} records")
    
    # Setup CourtListener session
    session = requests.Session()
    if COURTLISTENER_TOKEN:
        session.headers.update({
            "Authorization": f"Token {COURTLISTENER_TOKEN}",
            "User-Agent": "CAFC-AI/1.0"
        })
        print("  Using authenticated CourtListener API")
    else:
        session.headers.update({"User-Agent": "CAFC-AI/1.0"})
        print("  Warning: No COURTLISTENER_API_TOKEN - using unauthenticated API")
    
    # Connect to database
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cursor = conn.cursor()
    
    imported = 0
    skipped = 0
    errors = 0
    
    for i, r in enumerate(records):
        cluster_id = r.get("courtlistener_cluster_id")
        
        # Check if already exists
        cursor.execute(
            "SELECT id FROM documents WHERE courtlistener_cluster_id = %s",
            (cluster_id,)
        )
        if cursor.fetchone():
            skipped += 1
            continue
        
        # Enrich with PDF URL
        pdf_url = r.get("pdf_url", "")
        appeal_number = r.get("appeal_number", "")
        docket_id = None
        
        if cluster_id and (not pdf_url or not appeal_number):
            print(f"  [{i+1}/{len(records)}] Enriching cluster {cluster_id}...", end=" ", flush=True)
            
            enrichment = get_pdf_url_from_courtlistener(cluster_id, session)
            if enrichment.get("pdf_url"):
                pdf_url = enrichment["pdf_url"]
            docket_id = enrichment.get("docket_id")
            
            if not appeal_number and docket_id:
                appeal_number = get_docket_number(docket_id, session)
            
            print(f"PDF: {'✓' if pdf_url else '✗'}, Appeal#: {'✓' if appeal_number else '✗'}")
            time.sleep(0.1)  # Rate limiting
        
        if not pdf_url:
            print(f"  [{i+1}/{len(records)}] No PDF URL for cluster {cluster_id} - skipping")
            errors += 1
            continue
        
        # Parse release date
        release_date = r.get("release_date")
        if release_date and isinstance(release_date, str):
            try:
                release_date = datetime.strptime(release_date, "%Y-%m-%d").date()
            except:
                release_date = None
        
        # Insert record
        try:
            cursor.execute("""
                INSERT INTO documents (
                    pdf_url, case_name, appeal_number, release_date,
                    document_type, status, courtlistener_cluster_id, courtlistener_url
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (pdf_url) DO NOTHING
            """, (
                pdf_url,
                r.get("case_name", ""),
                appeal_number,
                release_date,
                r.get("document_type", "OPINION"),
                r.get("status", "Published"),
                cluster_id,
                r.get("courtlistener_url", "")
            ))
            conn.commit()
            imported += 1
        except Exception as e:
            conn.rollback()
            print(f"  Error inserting: {e}")
            errors += 1
    
    cursor.close()
    conn.close()
    
    print()
    print("=" * 50)
    print(f"Import complete!")
    print(f"  Imported: {imported}")
    print(f"  Skipped (already exists): {skipped}")
    print(f"  Errors: {errors}")


def main():
    use_full = "--full" in sys.argv
    limit = None
    
    for arg in sys.argv[1:]:
        if arg.startswith("--limit="):
            limit = int(arg.split("=")[1])
    
    manifest_file = FULL_FILE if use_full else SAMPLE_FILE
    import_records(manifest_file, limit)


if __name__ == "__main__":
    main()
