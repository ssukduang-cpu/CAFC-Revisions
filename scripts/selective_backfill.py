#!/usr/bin/env python3
"""
Smart Backfill Script for CAFC Landmark Cases (1982-2014)

This script implements a strategic backfill approach:
1. Target specific landmark cases by citation/name
2. Discover frequently-cited pre-2015 cases from existing corpus
3. Prioritize ingestion based on citation frequency
"""
import asyncio
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import db_postgres as db
from backend.ingest.run import ingest_document

LANDMARK_CASES = [
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


def discover_cited_cases(min_citations: int = 5) -> Dict[str, int]:
    """
    Parse ingested documents to find frequently-cited pre-2015 cases.
    Returns dict of citation -> count.
    """
    log("Discovering frequently-cited cases from corpus...")
    citation_counts = defaultdict(int)
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT dc.text_content 
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.ingested = TRUE
            LIMIT 500
        """)
        
        for row in cursor.fetchall():
            text = row["text_content"] or ""
            citations = extract_citations_from_text(text)
            for citation, _ in citations:
                citation_counts[citation] += 1
    
    frequent = {k: v for k, v in citation_counts.items() if v >= min_citations}
    log(f"Found {len(frequent)} citations appearing {min_citations}+ times")
    
    return dict(sorted(frequent.items(), key=lambda x: x[1], reverse=True))


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


async def ingest_landmarks(dry_run: bool = False) -> Dict[str, any]:
    """
    Find and ingest landmark cases from CourtListener.
    """
    results = {
        "found": [],
        "not_found": [],
        "ingested": [],
        "failed": []
    }
    
    log(f"Processing {len(LANDMARK_CASES)} landmark cases...")
    
    for landmark in LANDMARK_CASES:
        log(f"\nSearching for: {landmark['name']}")
        
        result = await find_landmark_on_courtlistener(landmark)
        
        if result:
            results["found"].append(landmark["name"])
            
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
                                log(f"Successfully ingested: {landmark['name']}")
                            else:
                                results["failed"].append({
                                    "name": landmark["name"],
                                    "error": ingest_result.get("error")
                                })
                        else:
                            results["failed"].append({
                                "name": landmark["name"],
                                "error": "Document not found after insert"
                            })
                    except Exception as e:
                        results["failed"].append({
                            "name": landmark["name"],
                            "error": str(e)
                        })
        else:
            results["not_found"].append(landmark["name"])
            log(f"Not found: {landmark['name']}")
        
        await asyncio.sleep(2)
    
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
    
    parser = argparse.ArgumentParser(description="Smart Backfill for CAFC Landmark Cases")
    parser.add_argument("--landmarks", action="store_true", help="Ingest landmark cases")
    parser.add_argument("--discover", action="store_true", help="Discover frequently-cited cases")
    parser.add_argument("--historical", action="store_true", help="Fetch historical cases (1982-2014)")
    parser.add_argument("--limit", type=int, default=100, help="Max cases to fetch")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually ingest")
    parser.add_argument("--delay", type=float, default=5.0, help="Delay between API calls (seconds)")
    
    args = parser.parse_args()
    
    if args.discover:
        citations = discover_cited_cases(min_citations=5)
        print("\nTop 20 most cited cases:")
        for i, (citation, count) in enumerate(list(citations.items())[:20]):
            print(f"  {i+1}. {citation}: {count} citations")
    
    if args.landmarks:
        results = await ingest_landmarks(dry_run=args.dry_run)
        print(f"\nLandmark Results:")
        print(f"  Found: {len(results['found'])}")
        print(f"  Not Found: {len(results['not_found'])}")
        print(f"  Ingested: {len(results['ingested'])}")
        print(f"  Failed: {len(results['failed'])}")
        
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
    
    if not any([args.landmarks, args.discover, args.historical]):
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
