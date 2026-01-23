#!/bin/bash
set -e

OPINION_ID="$1"

if [ -z "$OPINION_ID" ]; then
    echo '{"success": false, "error": "Opinion ID required"}'
    exit 1
fi

if [ -z "$DATABASE_URL" ]; then
    echo '{"success": false, "error": "DATABASE_URL not set"}'
    exit 1
fi

TEMP_ID=$(cat /proc/sys/kernel/random/uuid)
PDF_PATH="/tmp/${TEMP_ID}.pdf"

cleanup() {
    rm -f "$PDF_PATH"
}
trap cleanup EXIT

OPINION=$(psql "$DATABASE_URL" -t -A -F'|' -c "SELECT id, case_name, pdf_url, is_ingested FROM opinions WHERE id = '$OPINION_ID'" 2>/dev/null)

if [ -z "$OPINION" ]; then
    echo '{"success": false, "error": "Opinion not found"}'
    exit 1
fi

IFS='|' read -r OP_ID CASE_NAME PDF_URL IS_INGESTED <<< "$OPINION"

if [ "$IS_INGESTED" = "t" ]; then
    echo '{"success": true, "message": "Already ingested", "chunksCreated": 0}'
    exit 0
fi

echo "Downloading: $CASE_NAME" >&2
curl -sL -o "$PDF_PATH" "$PDF_URL"

NUM_PAGES=$(pdfinfo "$PDF_PATH" 2>/dev/null | grep "Pages:" | awk '{print $2}')
echo "Processing $NUM_PAGES pages..." >&2

TOTAL_CHUNKS=0
GLOBAL_CHUNK_INDEX=0
TEXT_PREVIEW=""

for ((PAGE=1; PAGE<=NUM_PAGES; PAGE++)); do
    PAGE_TEXT=$(pdftotext -f $PAGE -l $PAGE -layout "$PDF_PATH" - 2>/dev/null || echo "")
    
    if [ $PAGE -eq 1 ]; then
        TEXT_PREVIEW="${PAGE_TEXT:0:10000}"
    elif [ ${#TEXT_PREVIEW} -lt 10000 ]; then
        REMAINING=$((10000 - ${#TEXT_PREVIEW}))
        TEXT_PREVIEW="$TEXT_PREVIEW

${PAGE_TEXT:0:$REMAINING}"
    fi
    
    CLEANED_TEXT=$(echo "$PAGE_TEXT" | tr -s '[:space:]' ' ' | sed 's/^ *//;s/ *$//')
    
    if [ ${#CLEANED_TEXT} -ge 50 ]; then
        CHUNK_SIZE=1500
        OVERLAP=300
        START=0
        TEXT_LEN=${#CLEANED_TEXT}
        
        while [ $START -lt $TEXT_LEN ]; do
            END=$((START + CHUNK_SIZE))
            if [ $END -gt $TEXT_LEN ]; then
                END=$TEXT_LEN
            fi
            
            CHUNK="${CLEANED_TEXT:$START:$((END - START))}"
            
            if [ ${#CHUNK} -ge 50 ]; then
                CHUNK_ID=$(cat /proc/sys/kernel/random/uuid)
                ESCAPED_CHUNK=$(echo "$CHUNK" | sed "s/'/''/g")
                
                psql "$DATABASE_URL" -q -c "INSERT INTO chunks (id, opinion_id, chunk_text, page_number, chunk_index) VALUES ('$CHUNK_ID', '$OP_ID', '$ESCAPED_CHUNK', $PAGE, $GLOBAL_CHUNK_INDEX)" 2>/dev/null
                
                TOTAL_CHUNKS=$((TOTAL_CHUNKS + 1))
                GLOBAL_CHUNK_INDEX=$((GLOBAL_CHUNK_INDEX + 1))
            fi
            
            START=$((START + ${#CHUNK} - OVERLAP))
            if [ $START -le 0 ]; then
                START=$END
            fi
        done
    fi
    
    echo "Page $PAGE/$NUM_PAGES done" >&2
done

ESCAPED_PREVIEW=$(echo "$TEXT_PREVIEW" | sed "s/'/''/g")
psql "$DATABASE_URL" -q -c "UPDATE opinions SET is_ingested = TRUE, pdf_text = '$ESCAPED_PREVIEW' WHERE id = '$OP_ID'" 2>/dev/null

echo "{\"success\": true, \"message\": \"Successfully ingested $CASE_NAME\", \"numPages\": $NUM_PAGES, \"chunksCreated\": $TOTAL_CHUNKS}"
