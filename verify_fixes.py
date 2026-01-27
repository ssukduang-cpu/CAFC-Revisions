import sqlite3

# CONFIGURATION: Change this to match your actual database filename
DB_NAME = "federal_circuit.db" 

def run_audit():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        print(f"--- DATABASE INTEGRITY AUDIT: {DB_NAME} ---")
        
        # 1. Check for Metadata Desync (Alice/Bilski/Amgen)
        print("\n[1/3] Metadata Sync Check (Hollow but High Chunk):")
        cursor.execute("SELECT case_name, pages, chunks FROM cases WHERE (pages <= 1 AND chunks > 10)")
        desync_cases = cursor.fetchall()
        if desync_cases:
            print(f"❌ FAIL: {len(desync_cases)} cases show <= 1 page despite having many chunks.")
            for row in desync_cases[:5]:
                print(f"  - {row[0]}: {row[1]} Pages / {row[2]} Chunks")
        else:
            print("✅ PASS: No metadata/chunk mismatches found.")

        # 2. Check for Deduplication (Appeal 22-1556)
        print("\n[2/3] Deduplication Check (Appeal 22-1556):")
        cursor.execute("SELECT COUNT(*) FROM cases WHERE appeal_number = '22-1556'")
        count = cursor.fetchone()[0]
        if count > 1:
            print(f"❌ FAIL: Appeal 22-1556 still has {count} entries.")
        else:
            print("✅ PASS: Appeal 22-1556 is unique.")

        # 3. Check for Rule 36 Classification
        print("\n[3/3] Rule 36 Status Check:")
        cursor.execute("SELECT COUNT(*) FROM cases WHERE status = 'Summary Affirmance (No Opinion)'")
        status_count = cursor.fetchone()[0]
        if status_count == 0:
            print("❌ FAIL: No cases are flagged as 'Summary Affirmance'.")
        else:
            print(f"✅ PASS: {status_count} cases correctly flagged.")

        conn.close()
    except Exception as e:
        print(f"ERROR: Could not audit database. \nDetails: {e}")

run_audit()
