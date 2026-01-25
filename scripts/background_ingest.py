#!/usr/bin/env python3
"""
Background ingestion script that runs continuously to process all pending opinions.
Designed to run as a long-running process that will fill the database with all opinions.
"""
import asyncio
import os
import sys
import time
import signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import db_postgres as db
from backend.ingest.run import ingest_document

BATCH_SIZE = 20
DELAY_BETWEEN_BATCHES = 5
DELAY_BETWEEN_DOCS = 1
MAX_CONSECUTIVE_FAILURES = 50

running = True

def signal_handler(sig, frame):
    global running
    print("\n[SIGNAL] Graceful shutdown requested...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def log(message: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

async def run_continuous_ingest():
    global running
    
    db.init_db()
    
    total_processed = 0
    total_succeeded = 0
    total_failed = 0
    consecutive_failures = 0
    
    log("=" * 60)
    log("BACKGROUND INGESTION STARTED")
    log("=" * 60)
    
    stats = db.get_ingestion_stats()
    log(f"Initial state: {stats['ingested']} ingested / {stats['total_documents']} total ({stats['percent_complete']}%)")
    log(f"Pending: {stats['pending']}, Failed: {stats['failed']}")
    log("=" * 60)
    
    while running:
        documents = db.get_pending_documents(limit=BATCH_SIZE)
        
        if not documents:
            log("No more pending documents. Ingestion complete!")
            break
        
        log(f"\n--- Processing batch of {len(documents)} documents ---")
        
        batch_succeeded = 0
        batch_failed = 0
        
        for doc in documents:
            if not running:
                log("Shutdown requested, stopping...")
                break
            
            case_name = doc.get('case_name', 'Unknown')[:50]
            doc_id = doc.get('id')
            
            try:
                result = await ingest_document(doc)
                
                if result.get("success"):
                    batch_succeeded += 1
                    total_succeeded += 1
                    consecutive_failures = 0
                    log(f"  ✓ {case_name} ({result.get('num_pages', 0)} pages)")
                else:
                    batch_failed += 1
                    total_failed += 1
                    consecutive_failures += 1
                    error = result.get('error', 'Unknown error')[:60]
                    log(f"  ✗ {case_name}: {error}")
                
            except Exception as e:
                batch_failed += 1
                total_failed += 1
                consecutive_failures += 1
                log(f"  ✗ {case_name}: Exception - {str(e)[:60]}")
            
            total_processed += 1
            
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                log(f"\n[WARNING] {MAX_CONSECUTIVE_FAILURES} consecutive failures. Pausing for 60s...")
                await asyncio.sleep(60)
                consecutive_failures = 0
            
            await asyncio.sleep(DELAY_BETWEEN_DOCS)
        
        stats = db.get_ingestion_stats()
        log(f"\nBatch complete: {batch_succeeded} succeeded, {batch_failed} failed")
        log(f"Overall progress: {stats['ingested']} / {stats['total_documents']} ({stats['percent_complete']}%)")
        log(f"Session totals: {total_succeeded} succeeded, {total_failed} failed")
        
        if running and documents:
            log(f"Waiting {DELAY_BETWEEN_BATCHES}s before next batch...")
            await asyncio.sleep(DELAY_BETWEEN_BATCHES)
    
    log("\n" + "=" * 60)
    log("INGESTION SESSION COMPLETE")
    log(f"Total processed: {total_processed}")
    log(f"Succeeded: {total_succeeded}")
    log(f"Failed: {total_failed}")
    
    stats = db.get_ingestion_stats()
    log(f"Database state: {stats['ingested']} / {stats['total_documents']} ({stats['percent_complete']}%)")
    log("=" * 60)

def main():
    log("Starting background ingestion...")
    log(f"COURTLISTENER_API_TOKEN: {'set' if os.environ.get('COURTLISTENER_API_TOKEN') else 'NOT SET'}")
    log(f"DATABASE_URL: {'set' if os.environ.get('DATABASE_URL') else 'NOT SET'}")
    
    asyncio.run(run_continuous_ingest())

if __name__ == "__main__":
    main()
