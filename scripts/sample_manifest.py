#!/usr/bin/env python3
"""
Create a sample manifest of 100 recent opinions for testing.
We'll verify precedential status during ingestion by checking PDF text.
"""

import os
import json

MANIFEST_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "manifest.ndjson")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "manifest_sample.ndjson")


def main():
    print("Creating sample manifest for testing...")
    
    # Load full manifest
    with open(MANIFEST_FILE) as f:
        records = [json.loads(line) for line in f]
    
    print(f"  Loaded {len(records)} total records")
    
    # Sort by date descending
    records.sort(key=lambda r: r.get("release_date", ""), reverse=True)
    
    # Take 100 most recent
    sample = records[:100]
    
    # Save sample
    with open(OUTPUT_FILE, 'w') as f:
        for r in sample:
            f.write(json.dumps(r) + "\n")
    
    print(f"  Created sample with {len(sample)} records")
    print(f"  Date range: {sample[-1].get('release_date')} to {sample[0].get('release_date')}")
    print(f"  Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
