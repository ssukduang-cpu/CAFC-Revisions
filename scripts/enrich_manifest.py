#!/usr/bin/env python3
"""
Enrich manifest with docket numbers (appeal_numbers) from CourtListener.
"""

import os
import sys
import json
import time
import requests

INPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "manifest_full.ndjson")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "manifest.ndjson")


def main():
    token = os.environ.get("COURTLISTENER_API_TOKEN")
    if not token:
        print("ERROR: COURTLISTENER_API_TOKEN not set")
        sys.exit(1)
    
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Token {token}",
        "User-Agent": "CAFC-AI/1.0"
    })
    
    # Load records
    with open(INPUT_FILE) as f:
        records = [json.loads(line) for line in f]
    
    print(f"Loaded {len(records)} records")
    print("Enriching with docket numbers...")
    
    enriched = []
    errors = 0
    
    for i, r in enumerate(records):
        if i % 500 == 0 and i > 0:
            print(f"  Progress: {i}/{len(records)}")
        
        docket_id = r.get("docket_id")
        appeal_number = ""
        
        if docket_id:
            for attempt in range(3):
                try:
                    resp = session.get(
                        f"https://www.courtlistener.com/api/rest/v4/dockets/{docket_id}/",
                        params={"fields": "docket_number"},
                        timeout=30
                    )
                    if resp.status_code == 200:
                        appeal_number = resp.json().get("docket_number", "")
                        break
                    elif resp.status_code in (502, 503):
                        time.sleep(2 ** attempt)
                    else:
                        break
                except:
                    time.sleep(1)
        
        if not appeal_number:
            errors += 1
        
        final_record = {
            "case_name": r.get("case_name", ""),
            "appeal_number": appeal_number,
            "release_date": r.get("release_date", ""),
            "pdf_url": "",  # Will be populated during ingestion
            "courtlistener_cluster_id": r.get("courtlistener_cluster_id"),
            "courtlistener_url": r.get("courtlistener_url", ""),
            "status": "Published",
            "precedential_status_verified": False,
            "document_type": "OPINION",
        }
        enriched.append(final_record)
        
        time.sleep(0.02)
    
    # Save enriched manifest
    with open(OUTPUT_FILE, "w") as f:
        for r in enriched:
            f.write(json.dumps(r) + "\n")
    
    print()
    print(f"Enrichment complete!")
    print(f"  Total records: {len(enriched)}")
    print(f"  Missing docket numbers: {errors}")
    print(f"  Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
