#!/usr/bin/env python3
"""
Build full CAFC manifest from CourtListener API.

This builds a manifest of all ~28k CourtListener CAFC "Published" opinions.
Each record is marked with precedential_status_verified=false since CourtListener
does not distinguish CAFC's Precedential vs Nonprecedential designation.

Filtering to the ~4,384 true precedential opinions will be done during ingestion
by cross-referencing against CAFC's authoritative list.
"""

import os
import sys
import json
import time
import requests
from typing import Dict, List, Tuple
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CL_API_BASE = "https://www.courtlistener.com/api/rest/v4"


def get_session():
    """Create authenticated CourtListener session."""
    token = os.environ.get("COURTLISTENER_API_TOKEN")
    if not token:
        print("ERROR: COURTLISTENER_API_TOKEN not found")
        sys.exit(1)
    
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Token {token}",
        "User-Agent": "CAFC-AI/1.0",
        "Accept": "application/json"
    })
    return session


def fetch_all_cafc_opinions(session) -> Tuple[List[Dict], Dict]:
    """Fetch all CAFC Published opinions from CourtListener."""
    print("Fetching all CAFC Published opinions from CourtListener...")
    print()
    
    all_records = []
    cursor = None
    page = 0
    year_counts = defaultdict(int)
    
    while True:
        params = {
            "docket__court": "cafc",
            "precedential_status": "Published",
        }
        
        url = f"{CL_API_BASE}/clusters/"
        if cursor:
            url = cursor
            params = None
        
        retries = 0
        max_retries = 3
        
        while retries < max_retries:
            try:
                resp = session.get(url, params=params, timeout=60)
                if resp.status_code == 502 or resp.status_code == 503:
                    retries += 1
                    wait_time = 2 ** retries
                    print(f"  Server error {resp.status_code}, retry {retries}/{max_retries} in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                    
                if resp.status_code != 200:
                    print(f"  Error: {resp.status_code}")
                    break
                
                data = resp.json()
                results = data.get("results", [])
                
                if not results:
                    break
                
                for cluster in results:
                    cluster_id = cluster.get("id")
                    date_filed = cluster.get("date_filed", "")
                    case_name = cluster.get("case_name", "") or ""
                    docket_id = cluster.get("docket_id")
                    sub_opinions = cluster.get("sub_opinions", [])
                    
                    record = {
                        "courtlistener_cluster_id": cluster_id,
                        "courtlistener_url": f"https://www.courtlistener.com/opinion/{cluster_id}/",
                        "docket_id": docket_id,
                        "case_name": case_name[:300] if case_name else "",
                        "release_date": date_filed,
                        "sub_opinions": sub_opinions,
                        "precedential_status_verified": False,
                        "source": "courtlistener",
                    }
                    
                    all_records.append(record)
                    
                    if date_filed:
                        year = date_filed[:4]
                        year_counts[year] += 1
                
                page += 1
                if page % 100 == 0:
                    print(f"  Fetched {len(all_records)} records... (page {page})")
                
                next_url = data.get("next")
                if not next_url:
                    cursor = None
                else:
                    cursor = next_url
                
                time.sleep(0.1)
                break
                
            except Exception as e:
                retries += 1
                print(f"  Error on page {page}: {e}, retry {retries}/{max_retries}")
                time.sleep(2 ** retries)
        
        if retries >= max_retries:
            print(f"  Max retries reached, stopping at {len(all_records)} records")
            break
        
        if cursor is None:
            break
    
    stats = {
        "total_fetched": len(all_records),
        "year_counts": dict(year_counts),
    }
    
    return all_records, stats


def enrich_with_docket_numbers(session, records: List[Dict]) -> List[Dict]:
    """Fetch docket numbers (appeal_numbers) for each record."""
    print()
    print(f"Enriching {len(records)} records with docket numbers...")
    
    enriched = []
    errors = 0
    batch_size = 100
    
    for i, record in enumerate(records):
        if i % 500 == 0 and i > 0:
            print(f"  Enriched {i}/{len(records)} records...")
        
        try:
            docket_id = record.get("docket_id")
            if docket_id:
                resp = session.get(
                    f"{CL_API_BASE}/dockets/{docket_id}/",
                    params={"fields": "docket_number"},
                    timeout=30
                )
                if resp.status_code == 200:
                    docket = resp.json()
                    record["appeal_number"] = docket.get("docket_number", "")
                else:
                    record["appeal_number"] = ""
            else:
                record["appeal_number"] = ""
            
            enriched.append(record)
            
        except Exception as e:
            errors += 1
            record["appeal_number"] = ""
            enriched.append(record)
        
        time.sleep(0.02)
    
    print(f"  Completed enrichment ({errors} errors)")
    return enriched


def enrich_with_pdf_urls(session, records: List[Dict]) -> List[Dict]:
    """Fetch PDF URLs from opinion records."""
    print()
    print(f"Fetching PDF URLs for {len(records)} records...")
    
    for i, record in enumerate(records):
        if i % 500 == 0 and i > 0:
            print(f"  Fetched PDF URLs for {i}/{len(records)} records...")
        
        try:
            sub_opinions = record.get("sub_opinions", [])
            if sub_opinions:
                opinion_url = sub_opinions[0] if isinstance(sub_opinions[0], str) else None
                if opinion_url:
                    resp = session.get(
                        opinion_url,
                        params={"fields": "download_url"},
                        timeout=30
                    )
                    if resp.status_code == 200:
                        op_data = resp.json()
                        record["pdf_url"] = op_data.get("download_url", "")
                    else:
                        record["pdf_url"] = ""
                else:
                    record["pdf_url"] = ""
            else:
                record["pdf_url"] = ""
                
        except Exception as e:
            record["pdf_url"] = ""
        
        time.sleep(0.02)
    
    print("  PDF URL enrichment complete")
    return records


def deduplicate(records: List[Dict]) -> Tuple[List[Dict], int]:
    """Deduplicate using stable key: appeal_number + release_date + pdf_url."""
    print()
    print("Deduplicating records...")
    
    unique = []
    seen = set()
    duplicates = 0
    
    for record in records:
        key = (
            record.get("appeal_number", ""),
            record.get("release_date", ""),
            record.get("pdf_url", "")
        )
        
        if key in seen:
            duplicates += 1
            continue
        
        seen.add(key)
        unique.append(record)
    
    print(f"  Removed {duplicates} duplicates")
    return unique, duplicates


def save_manifest(records: List[Dict], output_path: str):
    """Save manifest to NDJSON file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    with open(output_path, "w") as f:
        for record in records:
            clean_record = {
                "case_name": record.get("case_name", ""),
                "appeal_number": record.get("appeal_number", ""),
                "release_date": record.get("release_date", ""),
                "pdf_url": record.get("pdf_url", ""),
                "courtlistener_cluster_id": record.get("courtlistener_cluster_id"),
                "courtlistener_url": record.get("courtlistener_url", ""),
                "status": "Published",
                "precedential_status_verified": record.get("precedential_status_verified", False),
                "document_type": "OPINION",
            }
            f.write(json.dumps(clean_record) + "\n")
    
    print(f"  Saved to {output_path}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Build CAFC manifest from CourtListener")
    parser.add_argument("--output", default="data/manifest.ndjson", help="Output path")
    parser.add_argument("--skip-enrichment", action="store_true", help="Skip docket/PDF enrichment")
    parser.add_argument("--dry-run", action="store_true", help="Count only, don't save")
    args = parser.parse_args()
    
    print("=" * 60)
    print("COURTLISTENER MANIFEST BUILDER")
    print("=" * 60)
    print()
    
    session = get_session()
    
    records, stats = fetch_all_cafc_opinions(session)
    
    print()
    print("-" * 60)
    print(f"Total records fetched: {stats['total_fetched']}")
    print()
    print("Year breakdown (sample):")
    sorted_years = sorted(stats["year_counts"].keys(), reverse=True)
    for year in sorted_years[:10]:
        print(f"  {year}: {stats['year_counts'][year]}")
    if len(sorted_years) > 10:
        print(f"  ... and {len(sorted_years) - 10} more years")
    print("-" * 60)
    
    if args.dry_run:
        print()
        print("Dry run complete. No manifest written.")
        return
    
    if not args.skip_enrichment:
        records = enrich_with_docket_numbers(session, records)
        records = enrich_with_pdf_urls(session, records)
    
    records, duplicates = deduplicate(records)
    
    save_manifest(records, args.output)
    
    print()
    print("=" * 60)
    print("MANIFEST BUILD COMPLETE")
    print("=" * 60)
    print(f"total_records_fetched:     {stats['total_fetched']}")
    print(f"duplicates_removed:        {duplicates}")
    print(f"final_manifest_count:      {len(records)}")
    print(f"output_path:               {args.output}")
    print()
    print("NOTE: All records have precedential_status_verified=false")
    print("      Filtering to ~4,384 true precedential opinions will be")
    print("      done during ingestion by cross-referencing CAFC's list.")
    print("=" * 60)


if __name__ == "__main__":
    main()
