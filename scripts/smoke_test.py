#!/usr/bin/env python3
"""
Smoke test for CourtListener-based CAFC opinions pipeline.

This script:
1. Builds a manifest for limit=100 opinions from CourtListener
2. Imports the manifest into the database
3. Ingests 5 opinions (downloads PDFs, extracts text)
4. Reports status counts

Usage:
    python scripts/smoke_test.py
"""

import os
import sys
import json
import time
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from build_manifest_courtlistener import build_manifest, DATA_DIR

API_BASE = "http://localhost:8000/api"

def wait_for_api(timeout: int = 30) -> bool:
    """Wait for the FastAPI server to be ready."""
    print("Waiting for API server...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{API_BASE}/status", timeout=5)
            if resp.status_code == 200:
                print("  API server is ready!")
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    print("  ERROR: API server not ready after timeout")
    return False

def step_build_manifest(limit: int = 100):
    """Step 1: Build manifest from CourtListener."""
    print("\n" + "=" * 60)
    print("STEP 1: Build Manifest from CourtListener")
    print("=" * 60)
    
    stats = build_manifest(max_results=limit, output_dir=DATA_DIR)
    
    return {
        "success": stats.total_unique_written > 0,
        "fetched": stats.total_fetched,
        "written": stats.total_unique_written,
        "duplicates": stats.duplicates_skipped,
        "errors": stats.errors
    }

def step_import_manifest():
    """Step 2: Import manifest into database."""
    print("\n" + "=" * 60)
    print("STEP 2: Import Manifest into Database")
    print("=" * 60)
    
    manifest_path = os.path.join(DATA_DIR, "manifest.ndjson")
    if not os.path.exists(manifest_path):
        print("  ERROR: Manifest file not found!")
        return {"success": False, "error": "Manifest file not found"}
    
    opinions = []
    with open(manifest_path, "r") as f:
        for line in f:
            if line.strip():
                try:
                    opinions.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    
    print(f"  Loaded {len(opinions)} opinions from manifest")
    
    try:
        resp = requests.post(
            f"{API_BASE}/admin/import_manifest",
            json={"opinions": opinions},
            timeout=120
        )
        resp.raise_for_status()
        result = resp.json()
        
        print(f"  Imported: {result.get('inserted', 0)}")
        print(f"  Skipped duplicates: {result.get('skipped_duplicates', 0)}")
        print(f"  Total in database: {result.get('total_documents', 0)}")
        
        return {
            "success": result.get("success", False),
            "inserted": result.get("inserted", 0),
            "skipped": result.get("skipped_duplicates", 0),
            "total": result.get("total_documents", 0)
        }
    except requests.RequestException as e:
        print(f"  ERROR: {e}")
        return {"success": False, "error": str(e)}

def step_ingest_batch(limit: int = 5):
    """Step 3: Ingest a batch of opinions."""
    print("\n" + "=" * 60)
    print(f"STEP 3: Ingest {limit} Opinions")
    print("=" * 60)
    
    try:
        resp = requests.post(
            f"{API_BASE}/admin/ingest_batch",
            params={"limit": limit},
            timeout=300
        )
        resp.raise_for_status()
        result = resp.json()
        
        succeeded = result.get("succeeded", 0)
        failed = result.get("failed", 0)
        
        print(f"  Processed: {result.get('processed', 0)}")
        print(f"  Succeeded: {succeeded}")
        print(f"  Failed: {failed}")
        
        return {
            "success": succeeded > 0,
            "processed": result.get("processed", 0),
            "succeeded": succeeded,
            "failed": failed
        }
    except requests.RequestException as e:
        print(f"  ERROR: {e}")
        return {"success": False, "error": str(e)}

def step_get_status():
    """Step 4: Report final status."""
    print("\n" + "=" * 60)
    print("STEP 4: Final Status Report")
    print("=" * 60)
    
    try:
        resp = requests.get(f"{API_BASE}/admin/ingest_status", timeout=30)
        resp.raise_for_status()
        stats = resp.json()
        
        print(f"  Total opinions:     {stats.get('total_documents', 0)}")
        print(f"  Opinions ingested:  {stats.get('ingested', 0)}")
        print(f"  Opinions pending:   {stats.get('pending', 0)}")
        print(f"  Total pages:        {stats.get('total_pages', 0)}")
        print(f"  Percent complete:   {stats.get('percent_complete', 0)}%")
        
        return stats
    except requests.RequestException as e:
        print(f"  ERROR: {e}")
        return {"error": str(e)}

def run_smoke_test():
    """Run the complete smoke test."""
    print("\n")
    print("=" * 60)
    print("CAFC OPINIONS PIPELINE - SMOKE TEST")
    print("Source: CourtListener API")
    print("=" * 60)
    
    if not wait_for_api():
        print("\nSMOKE TEST FAILED: API server not available")
        return False
    
    results = {}
    
    results["manifest"] = step_build_manifest(limit=100)
    if not results["manifest"]["success"]:
        print("\nSMOKE TEST FAILED: Could not build manifest")
        return False
    
    results["import"] = step_import_manifest()
    if not results["import"]["success"]:
        print("\nSMOKE TEST FAILED: Could not import manifest")
        return False
    
    results["ingest"] = step_ingest_batch(limit=5)
    
    results["status"] = step_get_status()
    
    print("\n" + "=" * 60)
    print("SMOKE TEST COMPLETE")
    print("=" * 60)
    
    print("\nSummary:")
    print(f"  Manifest: {results['manifest'].get('written', 0)} opinions fetched")
    print(f"  Import:   {results['import'].get('inserted', 0)} inserted, {results['import'].get('skipped', 0)} skipped")
    print(f"  Ingest:   {results['ingest'].get('succeeded', 0)} succeeded, {results['ingest'].get('failed', 0)} failed")
    print(f"  Status:   {results['status'].get('total_documents', 0)} total, {results['status'].get('ingested', 0)} ingested, {results['status'].get('total_pages', 0)} pages")
    
    overall_success = (
        results["manifest"]["success"] and
        results["import"]["success"] and
        results["ingest"].get("succeeded", 0) > 0
    )
    
    if overall_success:
        print("\nSMOKE TEST PASSED!")
    else:
        print("\nSMOKE TEST COMPLETED WITH ISSUES")
    
    return overall_success

def main():
    success = run_smoke_test()
    return 0 if success else 1

if __name__ == "__main__":
    exit(main())
