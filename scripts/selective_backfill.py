#!/usr/bin/env python3
"""
Smart Backfill Script for CAFC Landmark Cases (1982-2024)

This script implements a strategic backfill approach:
1. Target 200+ landmark cases organized by doctrine
2. Discover frequently-cited cases from existing corpus
3. Merge, dedupe, and prioritize by citation frequency
"""
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import db_postgres as db
from backend.ingest.run import ingest_document
from scripts.landmark_cases import get_all_curated_cases, LANDMARK_CASES_BY_DOCTRINE, count_curated_cases

LEGACY_LANDMARK_CASES = [
    {
        "name": "Alice Corp. v. CLS Bank International",
        "citation": "573 U.S. 208",
        "year": 2014,
        "appeal_number": "13-298",
        "significance": "§101 abstract idea test",
        "search_terms": ["Alice", "CLS Bank"],
        "court": "cafc",
        "required_words": ["alice", "cls", "bank"]
    },
    {
        "name": "Phillips v. AWH Corp.",
        "citation": "415 F.3d 1303",
        "year": 2005,
        "appeal_number": "03-1269",
        "significance": "Claim construction standard",
        "search_terms": ["Phillips", "AWH"],
        "court": "cafc",
        "required_words": ["phillips", "awh"]
    },
    {
        "name": "KSR International Co. v. Teleflex Inc.",
        "citation": "550 U.S. 398",
        "year": 2007,
        "appeal_number": "04-1350",
        "significance": "§103 obviousness standard",
        "search_terms": ["KSR", "Teleflex"],
        "court": "cafc",
        "required_words": ["ksr", "teleflex"]
    },
    {
        "name": "Markman v. Westview Instruments, Inc.",
        "citation": "517 U.S. 370",
        "year": 1996,
        "appeal_number": "95-26",
        "significance": "Claim construction is matter of law",
        "search_terms": ["Markman", "Westview"],
        "court": "cafc",
        "required_words": ["markman", "westview"]
    },
    {
        "name": "Ariad Pharmaceuticals, Inc. v. Eli Lilly & Co.",
        "citation": "598 F.3d 1336",
        "year": 2010,
        "appeal_number": "08-1248",
        "significance": "Written description requirement",
        "search_terms": ["Ariad", "Eli Lilly"],
        "court": "cafc",
        "required_words": ["ariad", "lilly"]
    },
    {
        "name": "In re Bilski",
        "citation": "545 F.3d 943",
        "year": 2008,
        "appeal_number": "07-1130",
        "significance": "Machine-or-transformation test",
        "search_terms": ["Bilski"],
        "court": "cafc",
        "required_words": ["bilski"]
    },
    {
        "name": "Nautilus, Inc. v. Biosig Instruments, Inc.",
        "citation": "572 U.S. 898",
        "year": 2014,
        "appeal_number": "13-369",
        "significance": "§112 indefiniteness standard",
        "search_terms": ["Nautilus", "Biosig"],
        "court": "cafc",
        "required_words": ["nautilus", "biosig"]
    },
    {
        "name": "Therasense, Inc. v. Becton, Dickinson & Co.",
        "citation": "649 F.3d 1276",
        "year": 2011,
        "appeal_number": "08-1511",
        "significance": "Inequitable conduct standard",
        "search_terms": ["Therasense", "Becton"],
        "court": "cafc",
        "required_words": ["therasense", "becton"]
    },
    {
        "name": "H-W Technology, L.C. v. Overstock.com, Inc.",
        "citation": "758 F.3d 1329",
        "year": 2014,
        "appeal_number": "14-1054",
        "significance": "Certificate of correction timing",
        "search_terms": ["H-W Technology", "Overstock"],
        "court": "cafc",
        "required_words": ["h-w", "overstock"]
    },
    {
        "name": "Cybor Corp. v. FAS Technologies, Inc.",
        "citation": "138 F.3d 1448",
        "year": 1998,
        "appeal_number": "96-1416",
        "significance": "De novo claim construction review",
        "search_terms": ["Cybor", "FAS Technologies"],
        "court": "cafc",
        "required_words": ["cybor", "fas"]
    }
]

COURTLISTENER_API_TOKEN = os.environ.get("COURTLISTENER_API_TOKEN")

def log(msg: str):
    import time
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", file=sys.stderr)


async def search_courtlistener(query: str, court: str = "cafc") -> List[Dict]:
    """Search CourtListener for cases matching query."""
    if not COURTLISTENER_API_TOKEN:
        log("Warning: COURTLISTENER_API_TOKEN not set")
        return []
    
    headers = {
        "Authorization": f"Token {COURTLISTENER_API_TOKEN}",
        "User-Agent": "Federal-Circuit-AI-Research/1.0"
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        url = "https://www.courtlistener.com/api/rest/v4/search/"
        params = {
            "type": "o",
            "court": court,
            "q": query,
            "order_by": "score desc"
        }
        
        response = await client.get(url, params=params, headers=headers)
        if response.status_code == 200:
            return response.json().get("results", [])
        else:
            log(f"CourtListener search failed: {response.status_code}")
            return []


def validate_landmark_match(case_name: str, landmark: Dict, result_year: int) -> bool:
    """
    Strictly validate that a case matches the landmark criteria.
    Requires all required_words AND correct year.
    """
    case_name_lower = case_name.lower()
    
    if landmark.get("year"):
        if abs(result_year - landmark["year"]) > 1:
            return False
    
    required_words = landmark.get("required_words", [])
    for word in required_words:
        if word.lower() not in case_name_lower:
            return False
    
    return True


async def find_landmark_on_courtlistener(landmark: Dict) -> Optional[Dict]:
    """Find a landmark case on CourtListener with strict matching."""
    all_terms = " ".join(landmark["search_terms"])
    results = await search_courtlistener(all_terms)
    
    for result in results:
        case_name = result.get("caseName", "")
        date_filed = result.get("dateFiled", "")
        result_year = int(date_filed[:4]) if date_filed else 0
        
        if validate_landmark_match(case_name, landmark, result_year):
            log(f"Found: {case_name} (cluster {result.get('cluster_id')})")
            return result
    
    for term in landmark["search_terms"]:
        results = await search_courtlistener(f'"{term}"')
        for result in results:
            case_name = result.get("caseName", "")
            date_filed = result.get("dateFiled", "")
            result_year = int(date_filed[:4]) if date_filed else 0
            
            if validate_landmark_match(case_name, landmark, result_year):
                log(f"Found: {case_name} (cluster {result.get('cluster_id')})")
                return result
        
        await asyncio.sleep(1)
    
    log(f"WARNING: Could not find exact match for {landmark['name']} - check cluster manually")
    return None


def extract_citations_from_text(text: str) -> List[Tuple[str, str]]:
    """
    Extract case citations from opinion text.
    Returns list of (case_name, citation) tuples.
    """
    citations = []
    
    fed_cir_pattern = r'(\d+)\s+F\.3d\s+(\d+)'
    matches = re.findall(fed_cir_pattern, text)
    for vol, page in matches:
        citations.append((f"{vol} F.3d {page}", "F.3d"))
    
    fed_cir_2d_pattern = r'(\d+)\s+F\.2d\s+(\d+)'
    matches = re.findall(fed_cir_2d_pattern, text)
    for vol, page in matches:
        citations.append((f"{vol} F.2d {page}", "F.2d"))
    
    us_pattern = r'(\d+)\s+U\.S\.\s+(\d+)'
    matches = re.findall(us_pattern, text)
    for vol, page in matches:
        citations.append((f"{vol} U.S. {page}", "U.S."))
    
    case_name_pattern = r'([A-Z][a-zA-Z\-]+(?:\s+(?:Corp|Inc|LLC|Ltd|Co)\.?)?)\s+v\.\s+([A-Z][a-zA-Z\-]+(?:\s+(?:Corp|Inc|LLC|Ltd|Co)\.?)?)'
    matches = re.findall(case_name_pattern, text)
    for plaintiff, defendant in matches:
        citations.append((f"{plaintiff} v. {defendant}", "case_name"))
    
    return citations


def discover_cited_cases(min_citations: int = 3, limit_chunks: int = 5000) -> Dict[str, int]:
    """
    Parse ingested documents to find frequently-cited cases.
    Scans full corpus to discover influential precedent.
    Returns dict of citation -> count, sorted by frequency.
    """
    log(f"Discovering frequently-cited cases from corpus (scanning up to {limit_chunks} chunks)...")
    citation_counts = defaultdict(int)
    case_name_counts = defaultdict(int)
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT dc.text 
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.ingested = TRUE
            LIMIT %s
        """, (limit_chunks,))
        
        chunks_processed = 0
        for row in cursor.fetchall():
            text = row["text"] or ""
            citations = extract_citations_from_text(text)
            for citation, ctype in citations:
                if ctype in ("F.3d", "F.2d", "U.S."):
                    citation_counts[citation] += 1
                elif ctype == "case_name":
                    case_name_counts[citation] += 1
            chunks_processed += 1
            if chunks_processed % 1000 == 0:
                log(f"Processed {chunks_processed} chunks...")
    
    log(f"Processed {chunks_processed} chunks total")
    
    frequent_citations = {k: v for k, v in citation_counts.items() if v >= min_citations}
    frequent_cases = {k: v for k, v in case_name_counts.items() if v >= min_citations}
    
    log(f"Found {len(frequent_citations)} reporter citations appearing {min_citations}+ times")
    log(f"Found {len(frequent_cases)} case names appearing {min_citations}+ times")
    
    all_frequent = {**frequent_citations, **frequent_cases}
    return dict(sorted(all_frequent.items(), key=lambda x: x[1], reverse=True))


def save_discovered_cases(output_path: str = "data/discovered_cases.json"):
    """Run citation discovery and save results to file."""
    discovered = discover_cited_cases(min_citations=3, limit_chunks=10000)
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(discovered, f, indent=2)
    
    log(f"Saved {len(discovered)} discovered cases to {output_path}")
    return discovered


async def add_case_to_database(result: Dict, landmark_info: Optional[Dict] = None) -> Optional[str]:
    """Add a case from CourtListener search results to the database."""
    cluster_id = result.get("cluster_id")
    case_name = result.get("caseName", "")
    appeal_number = result.get("docketNumber", "")
    date_filed = result.get("dateFiled")
    
    pdf_url = f"https://www.courtlistener.com/pdf/{cluster_id}/"
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM documents WHERE courtlistener_cluster_id = %s
        """, (cluster_id,))
        existing = cursor.fetchone()
        
        if existing:
            if landmark_info:
                cursor.execute("""
                    UPDATE documents 
                    SET is_landmark = TRUE, landmark_significance = %s
                    WHERE id = %s
                """, (landmark_info.get("significance", ""), existing["id"]))
                conn.commit()
                log(f"Marked as landmark: {case_name}")
            else:
                log(f"Case already in database: {case_name}")
            return existing["id"]
        
        is_landmark = landmark_info is not None
        significance = landmark_info.get("significance", "") if landmark_info else ""
        
        cursor.execute("""
            INSERT INTO documents (
                pdf_url, case_name, appeal_number, release_date,
                origin, document_type, status, courtlistener_cluster_id,
                courtlistener_url, is_landmark, landmark_significance
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            pdf_url,
            case_name,
            appeal_number,
            date_filed,
            "CourtListener",
            "OPINION",
            "Precedential",
            cluster_id,
            f"https://www.courtlistener.com/opinion/{cluster_id}/",
            is_landmark,
            significance
        ))
        
        doc_id = cursor.fetchone()["id"]
        conn.commit()
        
        log(f"Added to database: {case_name} (ID: {doc_id}, Landmark: {is_landmark})")
        return doc_id


async def ingest_landmarks(dry_run: bool = False, doctrine: Optional[str] = None) -> Dict[str, any]:
    """
    Find and ingest landmark cases from CourtListener.
    Uses the comprehensive curated list from landmark_cases.py (~96 cases).
    
    Args:
        dry_run: If True, only search - don't ingest
        doctrine: If specified, only process cases from that doctrine
    """
    results = {
        "found": [],
        "not_found": [],
        "ingested": [],
        "failed": [],
        "by_doctrine": {}
    }
    
    all_landmarks = get_all_curated_cases()
    
    if doctrine:
        all_landmarks = [c for c in all_landmarks if c.get("doctrine") == doctrine]
        log(f"Filtering to doctrine: {doctrine}")
    
    log(f"Processing {len(all_landmarks)} curated landmark cases...")
    
    for i, landmark in enumerate(all_landmarks):
        pct = int((i / len(all_landmarks)) * 100)
        doc_doctrine = landmark.get("doctrine", "unknown")
        log(f"\n[{pct}%] [{doc_doctrine}] Searching for: {landmark['name']}")
        
        result = await find_landmark_on_courtlistener(landmark)
        
        if result:
            results["found"].append(landmark["name"])
            
            if doc_doctrine not in results["by_doctrine"]:
                results["by_doctrine"][doc_doctrine] = {"found": 0, "ingested": 0, "failed": 0}
            results["by_doctrine"][doc_doctrine]["found"] += 1
            
            if not dry_run:
                doc_id = await add_case_to_database(result, landmark)
                if doc_id:
                    log(f"Ingesting {landmark['name']}...")
                    try:
                        doc = db.get_document(str(doc_id))
                        if doc:
                            ingest_result = await ingest_document(doc)
                            if ingest_result.get("success"):
                                results["ingested"].append(landmark["name"])
                                results["by_doctrine"][doc_doctrine]["ingested"] += 1
                                log(f"Successfully ingested: {landmark['name']}")
                            else:
                                results["failed"].append({
                                    "name": landmark["name"],
                                    "doctrine": doc_doctrine,
                                    "error": ingest_result.get("error")
                                })
                                results["by_doctrine"][doc_doctrine]["failed"] += 1
                        else:
                            results["failed"].append({
                                "name": landmark["name"],
                                "doctrine": doc_doctrine,
                                "error": "Document not found after insert"
                            })
                    except Exception as e:
                        results["failed"].append({
                            "name": landmark["name"],
                            "doctrine": doc_doctrine,
                            "error": str(e)
                        })
        else:
            results["not_found"].append(landmark["name"])
            log(f"Not found: {landmark['name']}")
        
        await asyncio.sleep(2)
    
    log(f"\n=== Landmark Ingestion Complete ===")
    log(f"Found: {len(results['found'])}/{len(all_landmarks)}")
    log(f"Ingested: {len(results['ingested'])}")
    log(f"Failed: {len(results['failed'])}")
    log(f"Not Found: {len(results['not_found'])}")
    
    return results


async def backfill_historical_cases(
    start_year: int = 1982,
    end_year: int = 2014,
    limit: int = 500,
    delay_seconds: float = 5.0
) -> Dict[str, any]:
    """
    Fetch historical precedential cases from CourtListener.
    Slow and steady to avoid rate limits.
    """
    if not COURTLISTENER_API_TOKEN:
        return {"error": "COURTLISTENER_API_TOKEN not set"}
    
    headers = {
        "Authorization": f"Token {COURTLISTENER_API_TOKEN}",
        "User-Agent": "Federal-Circuit-AI-Research/1.0"
    }
    
    added = 0
    skipped = 0
    
    log(f"Fetching historical cases from {start_year}-{end_year}...")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        next_url = None
        base_url = "https://www.courtlistener.com/api/rest/v4/search/"
        
        while added < limit:
            if next_url:
                response = await client.get(next_url, headers=headers)
            else:
                params = {
                    "type": "o",
                    "court": "cafc",
                    "stat_Published": "on",
                    "filed_after": f"{start_year}-01-01",
                    "filed_before": f"{end_year}-12-31",
                    "order_by": "dateFiled desc"
                }
                response = await client.get(base_url, params=params, headers=headers)
            
            if response.status_code == 429:
                log("Rate limited, waiting 60 seconds...")
                await asyncio.sleep(60)
                continue
            
            if response.status_code != 200:
                log(f"API error: {response.status_code}")
                break
            
            data = response.json()
            results = data.get("results", [])
            
            if not results:
                log("No more results")
                break
            
            for result in results:
                if added >= limit:
                    break
                
                cluster_id = result.get("cluster_id")
                
                with db.get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT id FROM documents WHERE courtlistener_cluster_id = %s
                    """, (cluster_id,))
                    if cursor.fetchone():
                        skipped += 1
                        continue
                
                await add_case_to_database(result)
                added += 1
                
                if added % 10 == 0:
                    log(f"Progress: {added} added, {skipped} skipped")
                
                await asyncio.sleep(delay_seconds)
            
            next_url = data.get("next")
            if not next_url:
                break
    
    return {
        "added": added,
        "skipped": skipped
    }


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Smart Backfill for CAFC Landmark Cases (200+)")
    parser.add_argument("--landmarks", action="store_true", help="Ingest curated landmark cases (~96)")
    parser.add_argument("--doctrine", type=str, help="Filter landmarks by doctrine (eligibility, obviousness, claim_construction, etc.)")
    parser.add_argument("--discover", action="store_true", help="Discover frequently-cited cases from corpus")
    parser.add_argument("--save-discovered", action="store_true", help="Save discovered cases to data/discovered_cases.json")
    parser.add_argument("--historical", action="store_true", help="Fetch historical cases (1982-2014)")
    parser.add_argument("--limit", type=int, default=100, help="Max cases to fetch for historical")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually ingest")
    parser.add_argument("--delay", type=float, default=5.0, help="Delay between API calls (seconds)")
    parser.add_argument("--list-doctrines", action="store_true", help="List available doctrines and case counts")
    
    args = parser.parse_args()
    
    if args.list_doctrines:
        print("\nAvailable Doctrines:")
        total = 0
        for doctrine, cases in LANDMARK_CASES_BY_DOCTRINE.items():
            print(f"  {doctrine}: {len(cases)} cases")
            total += len(cases)
        print(f"\nTotal curated cases: {total}")
        return
    
    if args.discover or args.save_discovered:
        if args.save_discovered:
            discovered = save_discovered_cases()
        else:
            discovered = discover_cited_cases(min_citations=3)
        
        print(f"\nTop 30 most cited cases/citations:")
        for i, (citation, count) in enumerate(list(discovered.items())[:30]):
            print(f"  {i+1}. {citation}: {count} citations")
    
    if args.landmarks:
        results = await ingest_landmarks(dry_run=args.dry_run, doctrine=args.doctrine)
        print(f"\nLandmark Results:")
        print(f"  Found: {len(results['found'])}")
        print(f"  Not Found: {len(results['not_found'])}")
        print(f"  Ingested: {len(results['ingested'])}")
        print(f"  Failed: {len(results['failed'])}")
        
        if results.get("by_doctrine"):
            print(f"\nBy Doctrine:")
            for doc, stats in results["by_doctrine"].items():
                print(f"  {doc}: {stats['found']} found, {stats['ingested']} ingested, {stats['failed']} failed")
        
        if results["not_found"]:
            print(f"\nMissing cases:")
            for name in results["not_found"]:
                print(f"  - {name}")
    
    if args.historical:
        results = await backfill_historical_cases(
            limit=args.limit,
            delay_seconds=args.delay
        )
        print(f"\nHistorical Backfill Results:")
        print(f"  Added: {results.get('added', 0)}")
        print(f"  Skipped: {results.get('skipped', 0)}")
    
    if not any([args.landmarks, args.discover, args.historical, args.list_doctrines, args.save_discovered]):
        parser.print_help()
        print(f"\n\nCurated landmark cases: {count_curated_cases()}")


if __name__ == "__main__":
    asyncio.run(main())
