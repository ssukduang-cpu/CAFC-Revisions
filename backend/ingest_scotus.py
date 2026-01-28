#!/usr/bin/env python3
"""
Supreme Court Patent Case Ingestion Script

Downloads and ingests the 15 landmark Supreme Court patent cases into the citation corpus.
Sets court/origin = "SCOTUS" and enables full-text search vectors.
"""

import asyncio
import os
import sys
import logging
from datetime import date
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SCOTUS_CASES = [
    {
        "case_name": "Alice Corp. v. CLS Bank International",
        "citation": "573 U.S. 208",
        "year": 2014,
        "pdf_url": "https://supreme.justia.com/cases/federal/us/573/13-298/case.pdf",
        "appeal_number": "13-298",
        "topic": "Patent eligibility - abstract ideas"
    },
    {
        "case_name": "Bilski v. Kappos",
        "citation": "561 U.S. 593",
        "year": 2010,
        "pdf_url": "https://tile.loc.gov/storage-services/service/ll/usrep/usrep561/usrep561593/usrep561593.pdf",
        "appeal_number": "08-964",
        "topic": "Patent eligibility - business methods"
    },
    {
        "case_name": "Diamond v. Diehr",
        "citation": "450 U.S. 175",
        "year": 1981,
        "pdf_url": "https://tile.loc.gov/storage-services/service/ll/usrep/usrep450/usrep450175/usrep450175.pdf",
        "appeal_number": "79-1111",
        "topic": "Patent eligibility - software/processes"
    },
    {
        "case_name": "KSR International Co. v. Teleflex Inc.",
        "citation": "550 U.S. 398",
        "year": 2007,
        "pdf_url": "https://tile.loc.gov/storage-services/service/ll/usrep/usrep550/usrep550398/usrep550398.pdf",
        "appeal_number": "04-1350",
        "topic": "Obviousness - motivation to combine"
    },
    {
        "case_name": "Graham v. John Deere Co.",
        "citation": "383 U.S. 1",
        "year": 1966,
        "pdf_url": "https://tile.loc.gov/storage-services/service/ll/usrep/usrep383/usrep383001/usrep383001.pdf",
        "appeal_number": "37",
        "topic": "Obviousness - Graham factors"
    },
    {
        "case_name": "eBay Inc. v. MercExchange, L.L.C.",
        "citation": "547 U.S. 388",
        "year": 2006,
        "pdf_url": "https://tile.loc.gov/storage-services/service/ll/usrep/usrep547/usrep547388/usrep547388.pdf",
        "appeal_number": "05-130",
        "topic": "Injunctive relief"
    },
    {
        "case_name": "Mayo Collaborative Services v. Prometheus Laboratories, Inc.",
        "citation": "566 U.S. 66",
        "year": 2012,
        "pdf_url": "https://supreme.justia.com/cases/federal/us/566/10-1150/case.pdf",
        "appeal_number": "10-1150",
        "topic": "Patent eligibility - laws of nature"
    },
    {
        "case_name": "Markman v. Westview Instruments, Inc.",
        "citation": "517 U.S. 370",
        "year": 1996,
        "pdf_url": "https://tile.loc.gov/storage-services/service/ll/usrep/usrep517/usrep517370/usrep517370.pdf",
        "appeal_number": "95-1180",
        "topic": "Claim construction"
    },
    {
        "case_name": "Teva Pharmaceuticals USA, Inc. v. Sandoz, Inc.",
        "citation": "574 U.S. 318",
        "year": 2015,
        "pdf_url": "https://supreme.justia.com/cases/federal/us/574/13-854/case.pdf",
        "appeal_number": "13-854",
        "topic": "Claim construction - standard of review"
    },
    {
        "case_name": "Nautilus, Inc. v. Biosig Instruments, Inc.",
        "citation": "572 U.S. 898",
        "year": 2014,
        "pdf_url": "https://supreme.justia.com/cases/federal/us/572/13-369/case.pdf",
        "appeal_number": "13-369",
        "topic": "Indefiniteness"
    },
    {
        "case_name": "Octane Fitness, LLC v. ICON Health & Fitness, Inc.",
        "citation": "572 U.S. 545",
        "year": 2014,
        "pdf_url": "https://supreme.justia.com/cases/federal/us/572/12-1184/case.pdf",
        "appeal_number": "12-1184",
        "topic": "Attorney fees - exceptional case"
    },
    {
        "case_name": "Halo Electronics, Inc. v. Pulse Electronics, Inc.",
        "citation": "579 U.S. 93",
        "year": 2016,
        "pdf_url": "https://supreme.justia.com/cases/federal/us/579/14-1513/case.pdf",
        "appeal_number": "14-1513",
        "topic": "Enhanced damages - willfulness"
    },
    {
        "case_name": "Cuozzo Speed Technologies, LLC v. Lee",
        "citation": "579 U.S. 261",
        "year": 2016,
        "pdf_url": "https://supreme.justia.com/cases/federal/us/579/15-446/case.pdf",
        "appeal_number": "15-446",
        "topic": "IPR proceedings - claim construction"
    },
    {
        "case_name": "Thryv, Inc. v. Click-to-Call Technologies, LP",
        "citation": "590 U.S. 45",
        "year": 2020,
        "pdf_url": "https://supreme.justia.com/cases/federal/us/590/18-916/case.pdf",
        "appeal_number": "18-916",
        "topic": "IPR proceedings - appealability"
    },
    {
        "case_name": "SAS Institute Inc. v. Iancu",
        "citation": "584 U.S. 357",
        "year": 2018,
        "pdf_url": "https://supreme.justia.com/cases/federal/us/584/16-969/case.pdf",
        "appeal_number": "16-969",
        "topic": "IPR proceedings - partial institution"
    }
]


def create_scotus_document(case: Dict) -> Dict[str, Any]:
    """Create a document record for a SCOTUS case."""
    return {
        "pdf_url": case["pdf_url"],
        "case_name": case["case_name"],
        "appeal_number": f"SCOTUS-{case['appeal_number']}",
        "release_date": date(case["year"], 6, 15),
        "origin": "SCOTUS",
        "document_type": "opinion",
        "status": "pending"
    }


async def insert_scotus_documents():
    """Insert SCOTUS case records into the database."""
    from backend.db_postgres import get_db
    
    inserted = 0
    skipped = 0
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        for case in SCOTUS_CASES:
            doc = create_scotus_document(case)
            
            cursor.execute(
                "SELECT id FROM documents WHERE pdf_url = %s",
                (doc["pdf_url"],)
            )
            existing = cursor.fetchone()
            
            if existing:
                logger.info(f"Skipping (already exists): {case['case_name']}")
                skipped += 1
                continue
            
            cursor.execute("""
                INSERT INTO documents (pdf_url, case_name, appeal_number, release_date, origin, document_type, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                doc["pdf_url"],
                doc["case_name"],
                doc["appeal_number"],
                doc["release_date"],
                doc["origin"],
                doc["document_type"],
                doc["status"]
            ))
            
            result = cursor.fetchone()
            doc_id = result['id'] if result else None
            logger.info(f"Inserted: {case['case_name']} (ID: {doc_id})")
            inserted += 1
        
        conn.commit()
    
    return inserted, skipped


async def ingest_scotus_cases():
    """Download PDFs and extract text for all SCOTUS cases."""
    from backend.ingest.run import ingest_document
    from backend.db_postgres import get_db
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, pdf_url, case_name, appeal_number, release_date, origin
            FROM documents 
            WHERE origin = 'SCOTUS' AND ingested = FALSE
            ORDER BY release_date DESC
        """)
        rows = cursor.fetchall()
    
    pending_docs = []
    for row in rows:
        pending_docs.append({
            "id": str(row['id']),
            "pdf_url": row['pdf_url'],
            "case_name": row['case_name'],
            "appeal_number": row['appeal_number'],
            "release_date": row['release_date'],
            "origin": row['origin'],
            "ingested": False
        })
    
    logger.info(f"Found {len(pending_docs)} SCOTUS cases to ingest")
    
    success_count = 0
    fail_count = 0
    
    for doc in pending_docs:
        logger.info(f"Ingesting: {doc['case_name']}")
        try:
            result = await ingest_document(doc)
            if result.get("success"):
                success_count += 1
                logger.info(f"✓ Success: {doc['case_name']}")
            else:
                fail_count += 1
                logger.error(f"✗ Failed: {doc['case_name']} - {result.get('error', 'Unknown error')}")
        except Exception as e:
            fail_count += 1
            logger.error(f"✗ Error ingesting {doc['case_name']}: {e}")
    
    return success_count, fail_count


async def main():
    logger.info("=" * 60)
    logger.info("SCOTUS Patent Case Ingestion")
    logger.info("=" * 60)
    
    logger.info("\nStep 1: Inserting document records...")
    inserted, skipped = await insert_scotus_documents()
    logger.info(f"Inserted: {inserted}, Skipped: {skipped}")
    
    logger.info("\nStep 2: Downloading PDFs and extracting text...")
    success, failed = await ingest_scotus_cases()
    
    logger.info("\n" + "=" * 60)
    logger.info("INGESTION COMPLETE")
    logger.info(f"Successful: {success}")
    logger.info(f"Failed: {failed}")
    logger.info("=" * 60)
    
    return success, failed


if __name__ == "__main__":
    success, failed = asyncio.run(main())
    sys.exit(0 if failed == 0 else 1)
