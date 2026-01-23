#!/usr/bin/env python3
"""
Build CAFC precedential opinions manifest using CourtListener API.
This approach doesn't require Playwright or browser automation.
"""

import os
import json
import time
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional

BASE_URL = "https://www.courtlistener.com/api/rest/v4"
CAFC_BASE = "https://www.cafc.uscourts.gov"

def get_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Federal-Circuit-AI-Research/1.0',
        'Accept': 'application/json',
    })
    return session

def search_cafc_opinions(session: requests.Session, page: int = 1, page_size: int = 100) -> Dict[str, Any]:
    """Search for CAFC opinions using CourtListener API."""
    params = {
        'type': 'o',
        'court': 'cafc',
        'order_by': 'dateFiled desc',
        'page': page,
        'page_size': min(page_size, 100),
    }
    
    resp = session.get(f"{BASE_URL}/search/", params=params)
    resp.raise_for_status()
    return resp.json()

def get_cluster_details(session: requests.Session, cluster_id: int) -> Optional[Dict[str, Any]]:
    """Get details for a specific opinion cluster."""
    try:
        resp = session.get(f"{BASE_URL}/clusters/{cluster_id}/")
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"  Error fetching cluster {cluster_id}: {e}")
    return None

def get_opinion_pdf_url(session: requests.Session, opinion_id: int) -> Optional[str]:
    """Get the PDF URL for an opinion."""
    try:
        resp = session.get(f"{BASE_URL}/opinions/{opinion_id}/")
        if resp.status_code == 200:
            data = resp.json()
            return data.get('download_url') or data.get('local_path')
    except Exception as e:
        pass
    return None

def map_to_manifest_format(result: Dict[str, Any], cluster: Optional[Dict] = None) -> Dict[str, Any]:
    """Map CourtListener result to our manifest format."""
    
    case_name = result.get('caseName', '')
    
    docket_number = result.get('docketNumber', '')
    
    date_filed = result.get('dateFiled', '')
    if date_filed:
        try:
            dt = datetime.strptime(date_filed[:10], '%Y-%m-%d')
            release_date = dt.strftime('%m/%d/%Y')
        except:
            release_date = date_filed
    else:
        release_date = ''
    
    is_precedential = result.get('status', '').lower() == 'published'
    if cluster:
        is_precedential = cluster.get('precedential_status', '').lower() == 'published'
    
    cluster_id = result.get('cluster_id')
    pdf_url = None
    if cluster_id:
        pdf_url = f"https://www.courtlistener.com/pdf/{cluster_id}/"
    
    download_url = result.get('download_url', '')
    if download_url:
        pdf_url = download_url
    
    return {
        'case_name': case_name,
        'appeal_number': docket_number,
        'release_date': release_date,
        'origin': 'CAFC',
        'status': 'Precedential' if is_precedential else 'Nonprecedential',
        'document_type': 'OPINION',
        'pdf_url': pdf_url,
        'courtlistener_cluster_id': cluster_id,
        'courtlistener_url': f"https://www.courtlistener.com{result.get('absolute_url', '')}",
    }

def fetch_all_precedential_opinions(max_results: Optional[int] = None, page_size: int = 100) -> List[Dict]:
    """Fetch all precedential CAFC opinions from CourtListener."""
    session = get_session()
    all_opinions = []
    page = 1
    total_count = None
    
    print("Fetching CAFC precedential opinions from CourtListener...")
    
    while True:
        print(f"Fetching page {page}...")
        
        try:
            data = search_cafc_opinions(session, page=page, page_size=page_size)
        except Exception as e:
            print(f"Error fetching page {page}: {e}")
            break
        
        if total_count is None:
            total_count = data.get('count', 0)
            print(f"Total CAFC opinions: {total_count}")
        
        results = data.get('results', [])
        if not results:
            print("No more results")
            break
        
        for result in results:
            status = result.get('status', '').lower()
            if status == 'published':
                opinion = map_to_manifest_format(result)
                all_opinions.append(opinion)
        
        print(f"  Page {page}: {len(results)} opinions, {len(all_opinions)} precedential so far")
        
        if max_results and len(all_opinions) >= max_results:
            print(f"Reached max results limit ({max_results})")
            all_opinions = all_opinions[:max_results]
            break
        
        if not data.get('next'):
            print("No more pages")
            break
        
        page += 1
        time.sleep(0.3)
    
    return all_opinions

def enrich_with_cafc_urls(opinions: List[Dict]) -> List[Dict]:
    """Try to find CAFC website PDF URLs for opinions."""
    print("\nEnriching with CAFC website URLs...")
    
    for i, opinion in enumerate(opinions):
        appeal_no = opinion.get('appeal_number', '')
        release_date = opinion.get('release_date', '')
        
        if appeal_no and release_date:
            try:
                dt = datetime.strptime(release_date, '%m/%d/%Y')
                date_str = dt.strftime('%m-%d-%Y')
                year = dt.year
                
                if int(appeal_no.split('-')[0]) >= 20:
                    opinion['cafc_pdf_url'] = f"{CAFC_BASE}/opinions-orders/{appeal_no}.OPINION.{date_str}.pdf"
            except:
                pass
        
        if (i + 1) % 500 == 0:
            print(f"  Processed {i + 1}/{len(opinions)}")
    
    return opinions

def save_manifest(opinions: List[Dict], output_dir: str = "data"):
    """Save opinions to manifest files."""
    os.makedirs(output_dir, exist_ok=True)
    
    json_path = os.path.join(output_dir, "manifest.json")
    with open(json_path, 'w') as f:
        json.dump(opinions, f, indent=2)
    print(f"Saved {len(opinions)} opinions to {json_path}")
    
    ndjson_path = os.path.join(output_dir, "manifest.ndjson")
    with open(ndjson_path, 'w') as f:
        for opinion in opinions:
            f.write(json.dumps(opinion) + '\n')
    print(f"Saved {len(opinions)} opinions to {ndjson_path}")
    
    return json_path, ndjson_path

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Build CAFC manifest from CourtListener")
    parser.add_argument("--max-results", type=int, help="Maximum opinions to fetch")
    parser.add_argument("--page-size", type=int, default=100, help="Results per page")
    parser.add_argument("--output", default="data", help="Output directory")
    parser.add_argument("--enrich-cafc", action="store_true", help="Try to find CAFC website URLs")
    args = parser.parse_args()
    
    opinions = fetch_all_precedential_opinions(
        max_results=args.max_results,
        page_size=args.page_size
    )
    
    if args.enrich_cafc and opinions:
        opinions = enrich_with_cafc_urls(opinions)
    
    if opinions:
        save_manifest(opinions, args.output)
        print(f"\nComplete! Fetched {len(opinions)} precedential CAFC opinions.")
    else:
        print("No opinions found.")

if __name__ == "__main__":
    main()
