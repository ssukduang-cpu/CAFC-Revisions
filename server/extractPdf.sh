#!/bin/bash
set -e

PDF_URL="$1"
OUTPUT_PATH="$2"
TEMP_ID=$(cat /proc/sys/kernel/random/uuid)
PDF_PATH="/tmp/${TEMP_ID}.pdf"

cleanup() {
    rm -f "$PDF_PATH" /tmp/${TEMP_ID}_page_*.txt
}
trap cleanup EXIT

echo "Downloading PDF..." >&2
curl -sL -o "$PDF_PATH" "$PDF_URL"

NUM_PAGES=$(pdfinfo "$PDF_PATH" 2>/dev/null | grep "Pages:" | awk '{print $2}')
echo "Processing $NUM_PAGES pages..." >&2

python3 - "$PDF_PATH" "$NUM_PAGES" "$OUTPUT_PATH" << 'PYTHON_SCRIPT'
import sys
import json
import subprocess

pdf_path = sys.argv[1]
num_pages = int(sys.argv[2])
output_path = sys.argv[3]

pages = []
for i in range(1, num_pages + 1):
    try:
        result = subprocess.run(
            ['pdftotext', '-f', str(i), '-l', str(i), '-layout', pdf_path, '-'],
            capture_output=True,
            text=True,
            timeout=30
        )
        page_text = result.stdout if result.returncode == 0 else ""
    except Exception as e:
        print(f"Error extracting page {i}: {e}", file=sys.stderr)
        page_text = ""
    
    pages.append({"page": i, "text": page_text})

output = {
    "success": True,
    "numPages": num_pages,
    "pages": pages
}

with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False)

print(output_path)
PYTHON_SCRIPT
