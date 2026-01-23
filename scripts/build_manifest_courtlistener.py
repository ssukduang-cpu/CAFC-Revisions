#!/usr/bin/env python3
"""
Build CAFC precedential opinions manifest using CourtListener API.
This is the primary data source for Federal Circuit opinions backfill.
Does NOT require Playwright, Selenium, or browser automation.

SCOPE DEFINITION:
- Court: Federal Circuit (CAFC) only
- Precedential status: Published (precedential) only
- Document type: Opinions only (excludes orders, judgments)
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
        self.total_api_returned = 0
        self.total_after_type_filter = 0
        self.total_after_deduplication = 0
        self.duplicates_skipped = 0
        self.non_opinion_skipped = 0
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
    next_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Fetch a page of CAFC opinions from CourtListener Search API.
    
    Filters enforced at API level:
    - court: cafc (Federal Circuit)
    - stat_Published: on (precedential only)
    - type: o (opinions)
    
    Uses cursor-based pagination (follow 'next' URL).
    """
    if next_url:
        resp = session.get(next_url, timeout=60)
    else:
        params = {
            'type': 'o',
            'court': 'cafc',
            'stat_Published': 'on',
            'order_by': 'dateFiled desc',
        }
        resp = session.get(f"{BASE_URL}/search/", params=params, timeout=60)
    
    resp.raise_for_status()
    return resp.json()

def is_opinion_document(result: Dict) -> bool:
    """
    Check if the result is an opinion (not an order, judgment, etc.)
    
    CourtListener uses 'type' field in cluster with values like:
    - 010combined: Combined Opinion
    - 015unamimous: Unanimous Opinion
    - 020lead: Lead Opinion
    - etc.
    
    We exclude:
    - Orders (type containing 'order')
    - Judgments (type containing 'judgment')
    - Errata (type containing 'errata')
    """
    doc_type = (result.get('type') or '').lower()
    case_name = (result.get('caseName') or '').lower()
    
    exclude_patterns = ['order', 'judgment', 'errata', 'mandate', 'rehearing']
    for pattern in exclude_patterns:
        if pattern in doc_type or pattern in case_name:
            return False
    
    return True

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
    fetch_details: bool = False,
    output_dir: str = None,
    dry_run: bool = False
) -> ManifestStats:
    """
    Build manifest of CAFC precedential opinions from CourtListener.
    
    Args:
        max_results: Maximum number of opinions to fetch (None = all)
        fetch_details: Whether to fetch individual opinion details for better PDF URLs
        output_dir: Output directory for manifest file
        dry_run: If True, only count records without writing to file
    
    Returns:
        ManifestStats with counts
    """
    stats = ManifestStats()
    session = get_session()
    seen_keys: Set[Tuple] = set()
    
    if output_dir is None:
        output_dir = DATA_DIR
    
    manifest_path = os.path.join(output_dir, "manifest.ndjson")
    
    print("=" * 70)
    print("CAFC Precedential Opinions Manifest Builder")
    print("=" * 70)
    print(f"Source:        CourtListener API ({BASE_URL})")
    print(f"Court:         Federal Circuit (CAFC)")
    print(f"Status:        Published (Precedential) only")
    print(f"Type:          Opinions only (excluding orders/judgments)")
    print(f"Mode:          {'DRY RUN (no file write)' if dry_run else 'LIVE (writing to file)'}")
    if not dry_run:
        print(f"Output:        {manifest_path}")
    print("=" * 70)
    
    if not dry_run:
        os.makedirs(output_dir, exist_ok=True)
    
    page = 1
    total_count = None
    sample_records: List[Dict] = []
    next_url: Optional[str] = None
    
    file_handle = None
    if not dry_run:
        file_handle = open(manifest_path, 'w')
    
    try:
        while True:
            print(f"\nFetching page {page}...")
            
            try:
                data = fetch_cafc_opinions_page(session, next_url=next_url)
            except requests.RequestException as e:
                print(f"  ERROR fetching page {page}: {e}")
                stats.errors += 1
                break
            
            if total_count is None:
                total_count = data.get('count', 0)
                print(f"API reports {total_count} total CAFC Published opinions")
            
            results = data.get('results', [])
            if not results:
                print("No more results")
                break
            
            page_api_count = len(results)
            page_opinion_count = 0
            page_written = 0
            page_skipped_type = 0
            page_skipped_dupe = 0
            
            for result in results:
                stats.total_api_returned += 1
                
                status = result.get('status', '').lower()
                if status not in ('published', 'precedential'):
                    continue
                
                if not is_opinion_document(result):
                    stats.non_opinion_skipped += 1
                    page_skipped_type += 1
                    continue
                
                stats.total_after_type_filter += 1
                page_opinion_count += 1
                
                opinion_details = None
                if fetch_details:
                    opinion_id = result.get('id')
                    if opinion_id:
                        try:
                            resp = session.get(f"{BASE_URL}/opinions/{opinion_id}/", timeout=30)
                            if resp.status_code == 200:
                                opinion_details = resp.json()
                        except:
                            pass
                        time.sleep(0.1)
                
                opinion = map_to_manifest_format(result, opinion_details)
                
                if not opinion.get('pdf_url'):
                    continue
                
                dedupe_key = get_dedupe_key(opinion)
                if dedupe_key in seen_keys:
                    stats.duplicates_skipped += 1
                    page_skipped_dupe += 1
                    continue
                
                seen_keys.add(dedupe_key)
                stats.total_after_deduplication += 1
                page_written += 1
                
                if len(sample_records) < 5:
                    sample_records.append(opinion)
                
                if not dry_run and file_handle:
                    file_handle.write(json.dumps(opinion) + '\n')
            
            print(f"  API returned: {page_api_count}")
            print(f"  Opinions (after type filter): {page_opinion_count}")
            print(f"  Skipped non-opinions: {page_skipped_type}")
            print(f"  Skipped duplicates: {page_skipped_dupe}")
            print(f"  Unique written: {page_written}")
            print(f"  Running total: {stats.total_after_deduplication} unique opinions")
            
            if max_results and stats.total_after_deduplication >= max_results:
                print(f"\nReached max_results limit ({max_results})")
                break
            
            next_url = data.get('next')
            if not next_url:
                print("\nNo more pages available")
                break
            
            page += 1
            time.sleep(0.3)
    
    finally:
        if file_handle:
            file_handle.close()
    
    print("\n" + "=" * 70)
    print("MANIFEST BUILD COMPLETE" if not dry_run else "DRY RUN COMPLETE")
    print("=" * 70)
    print(f"Total records from API:      {stats.total_api_returned}")
    print(f"After type filter:           {stats.total_after_type_filter}")
    print(f"Non-opinions skipped:        {stats.non_opinion_skipped}")
    print(f"Duplicates skipped:          {stats.duplicates_skipped}")
    print(f"Total unique opinions:       {stats.total_after_deduplication}")
    print(f"Errors:                      {stats.errors}")
    if not dry_run:
        print(f"Output file:                 {manifest_path}")
    print("=" * 70)
    
    if sample_records:
        print("\nSAMPLE RECORDS (first 5):")
        print("-" * 70)
        for i, rec in enumerate(sample_records, 1):
            print(f"\n{i}. {rec.get('case_name', 'Unknown')[:60]}")
            print(f"   Appeal: {rec.get('appeal_number', 'N/A')}")
            print(f"   Date: {rec.get('release_date', 'N/A')}")
            print(f"   Status: {rec.get('status', 'N/A')}")
            print(f"   Cluster ID: {rec.get('courtlistener_cluster_id', 'N/A')}")
            print(f"   PDF: {rec.get('pdf_url', 'N/A')[:60]}...")
        print("-" * 70)
    
    return stats

def main():
    parser = argparse.ArgumentParser(
        description="Build CAFC precedential opinions manifest from CourtListener",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
SCOPE:
  - Court: Federal Circuit (CAFC) only
  - Status: Published (Precedential) only
  - Type: Opinions only (excludes orders, judgments)

Examples:
  # Dry run - count records without writing
  python build_manifest_courtlistener.py --dry-run
  
  # Dry run with limit
  python build_manifest_courtlistener.py --dry-run --max-results 500
  
  # Build full manifest
  python build_manifest_courtlistener.py
  
  # Build with limit
  python build_manifest_courtlistener.py --max-results 100
"""
    )
    parser.add_argument(
        "--max-results", "-n", 
        type=int, 
        help="Maximum number of opinions to fetch (default: all)"
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count records only, do not write manifest file"
    )
    args = parser.parse_args()
    
    stats = build_manifest(
        max_results=args.max_results,
        fetch_details=args.fetch_details,
        output_dir=args.output,
        dry_run=args.dry_run
    )
    
    if stats.total_after_deduplication == 0 and stats.errors > 0:
        print("\nWARNING: No opinions found due to errors!")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
