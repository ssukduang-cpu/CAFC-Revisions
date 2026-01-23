#!/usr/bin/env python3
"""
Build CAFC precedential opinions manifest using CourtListener API.
This is the primary data source for Federal Circuit opinions backfill.
Does NOT require Playwright, Selenium, or browser automation.
"""

import os
import json
import time
import argparse
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Tuple

BASE_URL = "https://www.courtlistener.com/api/rest/v4"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
MANIFEST_FILE = os.path.join(DATA_DIR, "manifest.ndjson")

class ManifestStats:
    def __init__(self):
        self.total_fetched = 0
        self.total_unique_written = 0
        self.duplicates_skipped = 0
        self.errors = 0

def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Federal-Circuit-AI-Research/1.0 (legal research tool)',
        'Accept': 'application/json',
    })
    return session

def get_dedupe_key(opinion: Dict[str, Any]) -> Tuple:
    cluster_id = opinion.get('courtlistener_cluster_id')
    if cluster_id:
        return ('cluster', cluster_id)
    appeal_number = opinion.get('appeal_number')
    pdf_url = opinion.get('pdf_url')
    if appeal_number and pdf_url:
        return ('appeal_pdf', appeal_number, pdf_url)
    if pdf_url:
        return ('pdf', pdf_url)
    return ('unknown', id(opinion))

def fetch_cafc_opinions_page(
    session: requests.Session, 
    page: int = 1, 
    page_size: int = 100
) -> Dict[str, Any]:
    """Fetch a page of CAFC opinions from CourtListener Search API."""
    params = {
        'type': 'o',
        'court': 'cafc',
        'stat': 'Published',
        'order_by': 'dateFiled desc',
        'page': page,
        'page_size': min(page_size, 100),
    }
    
    resp = session.get(f"{BASE_URL}/search/", params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()

def get_opinion_details(session: requests.Session, opinion_id: int) -> Optional[Dict]:
    """Get detailed opinion info including PDF download URL."""
    try:
        resp = session.get(f"{BASE_URL}/opinions/{opinion_id}/", timeout=30)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"  Warning: Could not fetch opinion {opinion_id}: {e}")
    return None

def extract_pdf_url(result: Dict, opinion_details: Optional[Dict] = None) -> Optional[str]:
    """Extract the best PDF URL for an opinion."""
    if opinion_details:
        download_url = opinion_details.get('download_url')
        if download_url:
            if download_url.startswith('/'):
                return f"https://www.courtlistener.com{download_url}"
            return download_url
        
        local_path = opinion_details.get('local_path')
        if local_path:
            return f"https://storage.courtlistener.com/{local_path}"
    
    cluster_id = result.get('cluster_id')
    if cluster_id:
        return f"https://www.courtlistener.com/pdf/{cluster_id}/"
    
    return None

def map_to_manifest_format(result: Dict, opinion_details: Optional[Dict] = None) -> Dict[str, Any]:
    """Map CourtListener search result to our manifest format."""
    
    case_name = result.get('caseName', '') or result.get('case_name', '')
    docket_number = result.get('docketNumber', '') or result.get('docket_number', '')
    
    date_filed = result.get('dateFiled', '') or result.get('date_filed', '')
    release_date = ''
    if date_filed:
        try:
            dt = datetime.strptime(date_filed[:10], '%Y-%m-%d')
            release_date = dt.strftime('%m/%d/%Y')
        except:
            release_date = date_filed
    
    status_raw = result.get('status', '').lower()
    is_precedential = status_raw in ('published', 'precedential')
    
    cluster_id = result.get('cluster_id')
    pdf_url = extract_pdf_url(result, opinion_details)
    
    absolute_url = result.get('absolute_url', '')
    courtlistener_url = ''
    if absolute_url:
        courtlistener_url = f"https://www.courtlistener.com{absolute_url}"
    elif cluster_id:
        courtlistener_url = f"https://www.courtlistener.com/opinion/{cluster_id}/"
    
    return {
        'case_name': case_name,
        'appeal_number': docket_number or None,
        'release_date': release_date,
        'origin': None,
        'status': 'Precedential' if is_precedential else 'Nonprecedential',
        'document_type': 'OPINION',
        'pdf_url': pdf_url,
        'courtlistener_cluster_id': cluster_id,
        'courtlistener_url': courtlistener_url,
    }

def build_manifest(
    max_results: Optional[int] = None,
    page_size: int = 100,
    fetch_details: bool = False,
    output_dir: str = None
) -> ManifestStats:
    """
    Build manifest of CAFC precedential opinions from CourtListener.
    
    Args:
        max_results: Maximum number of opinions to fetch (None = all)
        page_size: Results per API page (max 100)
        fetch_details: Whether to fetch individual opinion details for better PDF URLs
        output_dir: Output directory for manifest file
    
    Returns:
        ManifestStats with counts
    """
    stats = ManifestStats()
    session = get_session()
    seen_keys: Set[Tuple] = set()
    
    if output_dir is None:
        output_dir = DATA_DIR
    os.makedirs(output_dir, exist_ok=True)
    manifest_path = os.path.join(output_dir, "manifest.ndjson")
    
    print("=" * 60)
    print("Building CAFC Precedential Opinions Manifest")
    print(f"Source: CourtListener API ({BASE_URL})")
    print(f"Output: {manifest_path}")
    print("=" * 60)
    
    page = 1
    total_count = None
    
    with open(manifest_path, 'w') as f:
        while True:
            print(f"\nFetching page {page}...")
            
            try:
                data = fetch_cafc_opinions_page(session, page=page, page_size=page_size)
            except requests.RequestException as e:
                print(f"  ERROR fetching page {page}: {e}")
                stats.errors += 1
                break
            
            if total_count is None:
                total_count = data.get('count', 0)
                print(f"Total CAFC precedential opinions available: {total_count}")
            
            results = data.get('results', [])
            if not results:
                print("No more results")
                break
            
            page_written = 0
            page_skipped = 0
            
            for result in results:
                stats.total_fetched += 1
                
                status = result.get('status', '').lower()
                if status not in ('published', 'precedential'):
                    continue
                
                opinion_details = None
                if fetch_details:
                    opinion_id = result.get('id')
                    if opinion_id:
                        opinion_details = get_opinion_details(session, opinion_id)
                        time.sleep(0.1)
                
                opinion = map_to_manifest_format(result, opinion_details)
                
                if not opinion.get('pdf_url'):
                    print(f"  Skipping opinion without PDF URL: {opinion.get('case_name', 'Unknown')[:50]}")
                    continue
                
                dedupe_key = get_dedupe_key(opinion)
                if dedupe_key in seen_keys:
                    stats.duplicates_skipped += 1
                    page_skipped += 1
                    continue
                
                seen_keys.add(dedupe_key)
                f.write(json.dumps(opinion) + '\n')
                stats.total_unique_written += 1
                page_written += 1
            
            print(f"  Page {page}: fetched {len(results)}, wrote {page_written}, skipped {page_skipped} dupes")
            print(f"  Running totals: {stats.total_unique_written} unique, {stats.duplicates_skipped} duplicates")
            
            if max_results and stats.total_unique_written >= max_results:
                print(f"\nReached max_results limit ({max_results})")
                break
            
            if not data.get('next'):
                print("\nNo more pages available")
                break
            
            page += 1
            time.sleep(0.3)
    
    print("\n" + "=" * 60)
    print("MANIFEST BUILD COMPLETE")
    print("=" * 60)
    print(f"Total rows fetched:    {stats.total_fetched}")
    print(f"Total unique written:  {stats.total_unique_written}")
    print(f"Duplicates skipped:    {stats.duplicates_skipped}")
    print(f"Errors:                {stats.errors}")
    print(f"Output file:           {manifest_path}")
    print("=" * 60)
    
    return stats

def main():
    parser = argparse.ArgumentParser(
        description="Build CAFC precedential opinions manifest from CourtListener",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python build_manifest_courtlistener.py --max-results 100  # Fetch first 100
  python build_manifest_courtlistener.py                    # Fetch all
  python build_manifest_courtlistener.py --fetch-details    # Fetch with detailed PDF URLs
"""
    )
    parser.add_argument(
        "--max-results", "-n", 
        type=int, 
        help="Maximum number of opinions to fetch (default: all)"
    )
    parser.add_argument(
        "--page-size", 
        type=int, 
        default=100, 
        help="Results per API page (default: 100, max: 100)"
    )
    parser.add_argument(
        "--output", "-o", 
        default=DATA_DIR, 
        help="Output directory (default: data/)"
    )
    parser.add_argument(
        "--fetch-details",
        action="store_true",
        help="Fetch individual opinion details for better PDF URLs (slower)"
    )
    args = parser.parse_args()
    
    stats = build_manifest(
        max_results=args.max_results,
        page_size=args.page_size,
        fetch_details=args.fetch_details,
        output_dir=args.output
    )
    
    if stats.total_unique_written == 0 and stats.errors > 0:
        print("\nWARNING: No opinions written due to errors!")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
