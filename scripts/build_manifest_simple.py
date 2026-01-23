#!/usr/bin/env python3
"""
Simple manifest builder that saves progress incrementally.
"""

import os
import sys
import json
import time
import requests

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "manifest_full.ndjson")
CL_API = "https://www.courtlistener.com/api/rest/v4/clusters/"


def main():
    token = os.environ.get("COURTLISTENER_API_TOKEN")
    if not token:
        print("ERROR: COURTLISTENER_API_TOKEN not set")
        sys.exit(1)
    
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Token {token}",
        "User-Agent": "CAFC-AI/1.0",
        "Accept": "application/json"
    })
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    cursor = None
    total = 0
    
    with open(OUTPUT_FILE, "w") as f:
        while True:
            params = {"docket__court": "cafc", "precedential_status": "Published"}
            url = cursor if cursor else CL_API
            if cursor:
                params = None
            
            for attempt in range(3):
                try:
                    resp = session.get(url, params=params, timeout=60)
                    if resp.status_code in (502, 503):
                        time.sleep(2 ** (attempt + 1))
                        continue
                    break
                except Exception as e:
                    time.sleep(2 ** (attempt + 1))
            else:
                print(f"Failed after 3 retries at {total} records")
                break
            
            if resp.status_code != 200:
                print(f"Error {resp.status_code} at {total} records")
                break
            
            data = resp.json()
            results = data.get("results", [])
            
            if not results:
                break
            
            for c in results:
                record = {
                    "courtlistener_cluster_id": c.get("id"),
                    "courtlistener_url": f"https://www.courtlistener.com/opinion/{c.get('id')}/",
                    "case_name": (c.get("case_name") or "")[:300],
                    "release_date": c.get("date_filed", ""),
                    "docket_id": c.get("docket_id"),
                    "precedential_status_verified": False,
                }
                f.write(json.dumps(record) + "\n")
                total += 1
            
            f.flush()
            
            if total % 1000 == 0:
                print(f"Progress: {total} records")
            
            cursor = data.get("next")
            if not cursor:
                break
            
            time.sleep(0.1)
    
    print(f"\nComplete: {total} records saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
