#!/usr/bin/env python3
"""
Build CAFC precedential opinions manifest from University of Iowa Dataset.
This provides accurate precedential status filtering that CourtListener lacks.

Source: Federal Circuit Document Dataset (Harvard Dataverse)
https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/UQ2SF7
"""

import os
import csv
import json
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Tuple

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
IOWA_FILE = os.path.join(DATA_DIR, "fedcircuit_documents.tab")
MANIFEST_FILE = os.path.join(DATA_DIR, "manifest.ndjson")


def parse_date(date_str: str) -> Optional[str]:
    """Parse date from Iowa dataset format (M/D/YY or M/D/YYYY) to MM/DD/YYYY."""
    if not date_str:
        return None
    date_str = date_str.strip('"')
    
    for fmt in ['%m/%d/%y', '%m/%d/%Y']:
        try:
            dt = datetime.strptime(date_str, fmt)
            # Handle 2-digit years (y2k)
            if dt.year > 2050:
                dt = dt.replace(year=dt.year - 100)
            return dt.strftime('%m/%d/%Y')
        except ValueError:
            continue
    return None


def get_year(date_str: str) -> int:
    """Extract year from date string."""
    if not date_str:
        return 0
    date_str = date_str.strip('"')
    try:
        return int(date_str)
    except:
        return 0


def load_existing_manifest(manifest_path: str) -> Set[str]:
    """Load existing manifest and return set of appeal numbers for deduplication."""
    existing = set()
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    appeal_no = entry.get('appeal_number', '')
                    if appeal_no:
                        # Normalize appeal number format
                        appeal_no = appeal_no.strip().replace('No. ', '').strip()
                        existing.add(appeal_no.lower())
                except:
                    pass
    return existing


def build_manifest_from_iowa(
    before_year: Optional[int] = None,
    after_year: Optional[int] = None,
    precedential_only: bool = True,
    append: bool = False,
    dry_run: bool = False,
    output_path: Optional[str] = None
) -> Dict[str, int]:
    """
    Build manifest from University of Iowa Federal Circuit Dataset.
    
    Args:
        before_year: Only include cases before this year
        after_year: Only include cases after this year  
        precedential_only: Only include precedential opinions (default: True)
        append: Append to existing manifest instead of overwriting
        dry_run: Don't write, just count
        output_path: Output file path (default: data/manifest.ndjson)
    
    Returns:
        Dict with statistics
    """
    if output_path is None:
        output_path = MANIFEST_FILE
    
    stats = {
        'total_in_dataset': 0,
        'precedential': 0,
        'in_date_range': 0,
        'skipped_duplicate': 0,
        'skipped_no_url': 0,
        'written': 0,
    }
    
    print("=" * 70)
    print("CAFC Manifest Builder - Iowa Dataset")
    print("=" * 70)
    print(f"Source:      {IOWA_FILE}")
    print(f"Filter:      {'Precedential only' if precedential_only else 'All'}")
    if before_year:
        print(f"Before Year: {before_year}")
    if after_year:
        print(f"After Year:  {after_year}")
    print(f"Mode:        {'DRY RUN' if dry_run else 'WRITE'}")
    print(f"Append:      {append}")
    print("=" * 70)
    
    # Load existing manifest for deduplication if appending
    existing_appeals = set()
    if append:
        existing_appeals = load_existing_manifest(output_path)
        print(f"\nLoaded {len(existing_appeals)} existing entries for deduplication")
    
    entries = []
    
    with open(IOWA_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')
        
        for row in reader:
            stats['total_in_dataset'] += 1
            
            # Get precedential status
            prec_status = row.get('PrecedentialStatus', '').strip('"')
            
            if precedential_only and prec_status != 'Precedential':
                continue
            
            stats['precedential'] += 1
            
            # Get year
            year = get_year(row.get('docYear', ''))
            
            # Apply date filters
            if before_year and year >= before_year:
                continue
            if after_year and year <= after_year:
                continue
            
            stats['in_date_range'] += 1
            
            # Get appeal number for deduplication
            appeal_no = row.get('appealNumber', '').strip('"').replace('No. ', '').strip()
            if appeal_no.lower() in existing_appeals:
                stats['skipped_duplicate'] += 1
                continue
            
            # Get PDF URL
            pdf_url = row.get('CAFC_URL', '').strip('"')
            cloud_link = row.get('CloudLink', '').strip('"')
            
            # Prefer CAFC URL, fallback to CloudLink
            if not pdf_url and cloud_link:
                pdf_url = cloud_link
            
            if not pdf_url:
                stats['skipped_no_url'] += 1
                continue
            
            # Build manifest entry
            case_name = row.get('caseName', '').strip('"')
            doc_date = parse_date(row.get('docDate', ''))
            origin = row.get('origin', '').strip('"')
            
            entry = {
                'case_name': case_name,
                'appeal_number': appeal_no,
                'release_date': doc_date,
                'origin': origin if origin else None,
                'status': 'Precedential',
                'document_type': 'OPINION',
                'pdf_url': pdf_url,
                'source': 'iowa_dataset',
            }
            
            entries.append(entry)
            existing_appeals.add(appeal_no.lower())
            stats['written'] += 1
    
    print(f"\n{'=' * 70}")
    print("RESULTS")
    print("=" * 70)
    print(f"Total in dataset:     {stats['total_in_dataset']}")
    print(f"Precedential:         {stats['precedential']}")
    print(f"In date range:        {stats['in_date_range']}")
    print(f"Skipped (duplicate):  {stats['skipped_duplicate']}")
    print(f"Skipped (no URL):     {stats['skipped_no_url']}")
    print(f"To write:             {stats['written']}")
    print("=" * 70)
    
    if not dry_run and entries:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        mode = 'a' if append else 'w'
        with open(output_path, mode) as f:
            for entry in entries:
                f.write(json.dumps(entry) + '\n')
        print(f"\nWritten to: {output_path}")
    
    # Show sample entries
    if entries:
        print("\nSample entries:")
        for entry in entries[:3]:
            print(f"  - {entry['case_name'][:50]} ({entry['release_date']})")
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Build CAFC manifest from Iowa Dataset (accurate precedential filtering)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Count all precedential cases
  python build_manifest_iowa.py --dry-run
  
  # Add pre-2015 precedential cases to existing manifest
  python build_manifest_iowa.py --before-year 2015 --append
  
  # Build fresh manifest with all precedential cases
  python build_manifest_iowa.py --precedential-only
"""
    )
    parser.add_argument(
        "--before-year",
        type=int,
        help="Only include cases before this year"
    )
    parser.add_argument(
        "--after-year", 
        type=int,
        help="Only include cases after this year"
    )
    parser.add_argument(
        "--precedential-only",
        action="store_true",
        default=True,
        help="Only include precedential opinions (default: True)"
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include all opinions (not just precedential)"
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing manifest"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write, just count"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path"
    )
    
    args = parser.parse_args()
    
    precedential_only = not args.include_all
    
    stats = build_manifest_from_iowa(
        before_year=args.before_year,
        after_year=args.after_year,
        precedential_only=precedential_only,
        append=args.append,
        dry_run=args.dry_run,
        output_path=args.output
    )
    
    return 0 if stats['written'] > 0 or args.dry_run else 1


if __name__ == "__main__":
    exit(main())
