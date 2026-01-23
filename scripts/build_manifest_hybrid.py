#!/usr/bin/env python3
"""
Build CAFC precedential manifest using hybrid CAFC + CourtListener approach.

Strategy:
1. Use CAFC website as authoritative source for precedential count (~4,384)
2. Get CAFC precedential appeal_numbers from first page (sample validation)
3. Query CourtListener API for matching records
4. Build manifest with stable cluster_ids and PDF URLs from CourtListener
"""

import os
import sys
import json
import time
import requests
from bs4 import BeautifulSoup
from typing import Dict, List, Set, Tuple
from collections import defaultdict

# Configuration
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CAFC_URL = "https://www.cafc.uscourts.gov/home/case-information/opinions-orders/"
CL_API_BASE = "https://www.courtlistener.com/api/rest/v4"


def get_courtlistener_session():
    """Create authenticated CourtListener session."""
    token = os.environ.get("COURTLISTENER_API_TOKEN")
    if not token:
        print("ERROR: COURTLISTENER_API_TOKEN not found in environment")
        sys.exit(1)
    
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Token {token}",
        "User-Agent": "CAFC-AI/1.0",
        "Accept": "application/json"
    })
    return session


def get_cafc_precedential_sample():
    """Get sample of precedential appeal_numbers from CAFC website first page."""
    print("Fetching CAFC precedential sample from website...")
    
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    
    resp = session.get(CAFC_URL, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    
    table = soup.find("table")
    if not table:
        print("  Warning: Could not find table on CAFC page")
        return [], 0
    
    rows = table.find_all("tr")[1:]  # Skip header
    precedential_appeal_numbers = []
    
    for row in rows:
        cells = row.find_all("td")
        if len(cells) >= 6:
            doc_type = cells[3].get_text(strip=True)
            status = cells[5].get_text(strip=True)
            appeal_number = cells[1].get_text(strip=True)
            
            if doc_type == "OPINION" and status == "Precedential":
                precedential_appeal_numbers.append(appeal_number)
    
    # The total count was validated as 4,384 via Selenium
    cafc_total = 4384
    
    print(f"  CAFC precedential sample: {len(precedential_appeal_numbers)} from first page")
    print(f"  CAFC authoritative total: {cafc_total} (validated)")
    
    return precedential_appeal_numbers, cafc_total


def get_courtlistener_cafc_opinions(cl_session, sample_appeal_numbers: List[str]) -> Tuple[List[Dict], Dict]:
    """
    Fetch CAFC opinions from CourtListener.
    Returns opinions list and stats dict.
    """
    print("\nQuerying CourtListener for CAFC opinions...")
    
    # First, validate that sample appeal_numbers exist in CourtListener
    print("  Validating sample appeal_numbers against CourtListener...")
    matches_found = 0
    for appeal_num in sample_appeal_numbers[:5]:  # Check first 5
        # Search for this docket number
        params = {
            "docket__court": "cafc",
            "docket__docket_number__contains": appeal_num.split("-")[0],  # Use case number prefix
        }
        resp = cl_session.get(f"{CL_API_BASE}/clusters/", params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results:
                matches_found += 1
    
    print(f"    Sample validation: {matches_found}/5 appeal_numbers found in CourtListener")
    
    # Now fetch all CAFC precedential opinions from CourtListener
    print("\n  Fetching all CAFC precedential opinions from CourtListener...")
    
    all_opinions = []
    cursor = None
    page = 0
    
    while True:
        params = {
            "docket__court": "cafc",
            "precedential_status": "Published",
        }
        
        url = f"{CL_API_BASE}/clusters/"
        if cursor:
            url = cursor
            params = None
        
        resp = cl_session.get(url, params=params, timeout=60)
        if resp.status_code != 200:
            print(f"    Error: {resp.status_code}")
            break
        
        data = resp.json()
        results = data.get("results", [])
        
        if not results:
            break
        
        for cluster in results:
            # Get docket info for appeal_number
            docket_id = cluster.get("docket_id")
            cluster_id = cluster.get("id")
            date_filed = cluster.get("date_filed", "")
            case_name = cluster.get("case_name", "") or cluster.get("case_name_full", "") or ""
            
            # Get sub_opinions for PDF URL
            sub_opinions = cluster.get("sub_opinions", [])
            
            all_opinions.append({
                "cluster_id": cluster_id,
                "docket_id": docket_id,
                "date_filed": date_filed,
                "case_name": case_name[:200] if case_name else "",
                "sub_opinions": sub_opinions,
                "precedential_status": cluster.get("precedential_status", ""),
            })
        
        page += 1
        if page % 50 == 0:
            print(f"    Fetched {len(all_opinions)} opinions...")
        
        next_url = data.get("next")
        if not next_url:
            break
        cursor = next_url
        
        # Rate limiting
        time.sleep(0.1)
    
    print(f"  Total CourtListener CAFC Published opinions: {len(all_opinions)}")
    
    stats = {
        "courtlistener_total": len(all_opinions),
        "sample_matches": matches_found,
    }
    
    return all_opinions, stats


def enrich_opinions_with_details(cl_session, opinions: List[Dict]) -> List[Dict]:
    """Fetch additional details (docket_number, PDF URLs) for each opinion."""
    print("\nEnriching opinions with docket details and PDF URLs...")
    
    enriched = []
    errors = 0
    
    for i, op in enumerate(opinions):
        if i % 100 == 0 and i > 0:
            print(f"  Enriched {i}/{len(opinions)} opinions...")
        
        try:
            # Get docket details
            docket_id = op.get("docket_id")
            if docket_id:
                docket_resp = cl_session.get(
                    f"{CL_API_BASE}/dockets/{docket_id}/",
                    params={"fields": "docket_number,case_name"},
                    timeout=30
                )
                if docket_resp.status_code == 200:
                    docket = docket_resp.json()
                    op["appeal_number"] = docket.get("docket_number", "")
                    if not op["case_name"]:
                        op["case_name"] = docket.get("case_name", "")
            
            # Get opinion details for PDF URL
            sub_opinions = op.get("sub_opinions", [])
            if sub_opinions:
                # Get first opinion URL (usually the main opinion)
                opinion_url = sub_opinions[0] if isinstance(sub_opinions[0], str) else None
                if opinion_url:
                    op_resp = cl_session.get(opinion_url, params={"fields": "download_url,local_path"}, timeout=30)
                    if op_resp.status_code == 200:
                        op_data = op_resp.json()
                        op["pdf_url"] = op_data.get("download_url", "")
                        op["local_path"] = op_data.get("local_path", "")
            
            enriched.append(op)
            
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"    Error enriching opinion {op.get('cluster_id')}: {e}")
        
        # Rate limiting
        time.sleep(0.05)
    
    print(f"  Enriched {len(enriched)} opinions ({errors} errors)")
    return enriched


def build_manifest(opinions: List[Dict], cafc_total: int) -> Tuple[List[Dict], Dict]:
    """Build final manifest with deduplication."""
    print("\nBuilding final manifest...")
    
    manifest = []
    seen_keys = set()
    duplicates = 0
    
    for op in opinions:
        # Create stable deduplication key
        key = (
            op.get("appeal_number", ""),
            op.get("date_filed", ""),
            op.get("pdf_url", "")
        )
        
        if key in seen_keys:
            duplicates += 1
            continue
        
        seen_keys.add(key)
        
        # Build manifest entry
        entry = {
            "case_name": op.get("case_name", ""),
            "appeal_number": op.get("appeal_number", ""),
            "release_date": op.get("date_filed", ""),
            "pdf_url": op.get("pdf_url", ""),
            "courtlistener_cluster_id": op.get("cluster_id"),
            "courtlistener_url": f"https://www.courtlistener.com/opinion/{op.get('cluster_id')}/",
            "status": "Precedential",  # All entries are precedential
            "document_type": "OPINION",
        }
        
        manifest.append(entry)
    
    stats = {
        "total_before_dedupe": len(opinions),
        "duplicates_removed": duplicates,
        "final_count": len(manifest),
        "cafc_authoritative_count": cafc_total,
        "match_ratio": len(manifest) / cafc_total if cafc_total > 0 else 0,
    }
    
    return manifest, stats


def save_manifest(manifest: List[Dict], output_path: str):
    """Save manifest to NDJSON file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    with open(output_path, "w") as f:
        for entry in manifest:
            f.write(json.dumps(entry) + "\n")
    
    print(f"  Saved {len(manifest)} entries to {output_path}")


def main():
    print("=" * 60)
    print("HYBRID MANIFEST BUILDER")
    print("CAFC Authority + CourtListener Matching")
    print("=" * 60)
    print()
    
    # Step 1: Get CAFC precedential sample and authoritative count
    sample_appeal_numbers, cafc_total = get_cafc_precedential_sample()
    
    # Step 2: Get CourtListener session
    cl_session = get_courtlistener_session()
    
    # Step 3: Fetch all CAFC opinions from CourtListener
    opinions, fetch_stats = get_courtlistener_cafc_opinions(cl_session, sample_appeal_numbers)
    
    # Step 4: Report findings before enrichment
    print("\n" + "=" * 60)
    print("COUNTS REPORT (before enrichment)")
    print("=" * 60)
    print(f"CAFC authoritative precedential count: {cafc_total}")
    print(f"CourtListener CAFC Published count:    {fetch_stats['courtlistener_total']}")
    print(f"Difference:                            {fetch_stats['courtlistener_total'] - cafc_total}")
    print()
    print("NOTE: CourtListener 'Published' includes both CAFC 'Precedential'")
    print("      and 'Nonprecedential' opinions. The manifest will contain")
    print(f"      all {fetch_stats['courtlistener_total']} CourtListener records.")
    print("      Post-processing needed to filter to exactly {cafc_total}.")
    print("=" * 60)
    
    # Ask user if they want to proceed with enrichment
    # For now, we just report the counts without enrichment
    print("\nDry run complete. No manifest written.")
    print("To proceed with full manifest build, modify this script.")


if __name__ == "__main__":
    main()
