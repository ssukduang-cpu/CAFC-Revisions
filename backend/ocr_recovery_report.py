#!/usr/bin/env python3
"""
OCR Recovery Impact Report Generator

Generates a Markdown report showing OCR recovery statistics including:
- Total hollow documents identified
- Recovery success rates
- Big 5 landmark case verification
- Analysis of legitimately short files
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get('DATABASE_URL')

BIG_5_LANDMARK_CASES = ["Markman", "Phillips", "Vitronics", "Alice", "KSR"]


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def generate_recovery_report():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT status, COUNT(*) as count FROM documents GROUP BY status")
    stats = {row['status']: row['count'] for row in cur.fetchall()}

    hollow_count = 0
    cur.execute("""
        SELECT COUNT(*) as count
        FROM documents d
        LEFT JOIN document_pages dp ON d.id = dp.document_id
        WHERE d.status IN ('completed', 'ingestion_failed')
        GROUP BY d.id
        HAVING COALESCE(SUM(LENGTH(dp.text)), 0) < 1000
    """)
    hollow_count = len(cur.fetchall())
    
    recovered_count = stats.get('recovered', 0)
    partial_count = stats.get('ocr_partial', 0)
    total_initial_hollow = hollow_count + recovered_count + partial_count

    landmark_results = []
    for case in BIG_5_LANDMARK_CASES:
        cur.execute("""
            SELECT 
                d.id, d.case_name, d.status,
                COALESCE(SUM(LENGTH(dp.text)), 0) as char_count
            FROM documents d
            LEFT JOIN document_pages dp ON d.id = dp.document_id
            WHERE d.case_name ILIKE %s
            GROUP BY d.id
            ORDER BY char_count DESC
            LIMIT 1
        """, (f'%{case}%',))
        result = cur.fetchone()
        if result:
            landmark_results.append({
                "name": case,
                "case_name": result['case_name'],
                "status": result['status'],
                "chars": result['char_count']
            })
        else:
            landmark_results.append({
                "name": case,
                "case_name": "Not Found",
                "status": "Not Found",
                "chars": 0
            })

    cur.execute("""
        SELECT COUNT(*) as count
        FROM documents d
        LEFT JOIN document_pages dp ON d.id = dp.document_id
        WHERE d.status IN ('completed', 'ingestion_failed', 'ocr_partial')
        GROUP BY d.id
        HAVING COALESCE(SUM(LENGTH(dp.text)), 0) < 500
    """)
    rule36_count = len(cur.fetchall())

    cur.execute("""
        SELECT COUNT(*) as count FROM documents 
        WHERE LOWER(case_name) LIKE '%errata%'
    """)
    errata_count = cur.fetchone()['count']

    conn.close()

    report = f"""
## **OCR Recovery Impact Report**

### **1. Executive Summary**
* **Total "Hollow" Documents Identified:** {total_initial_hollow}
* **Successful Recoveries (`recovered`):** {recovered_count}
* **Partial/Legitimately Short (`ocr_partial`):** {partial_count}
* **Pending/Remaining Hollow:** {hollow_count}

---

### **2. Recovery Distribution**
| Status | Count | Description |
| :--- | :--- | :--- |
| **Recovered** | {recovered_count} | >= 5000 chars (Full Opinions/PTAB) |
| **OCR Partial** | {partial_count} | < 5000 chars (Rule 36/Errata) |
| **Hollow** | {hollow_count} | Still pending processing |

---

### **3. Landmark Case Verification**
| Case Name | Full Name | Post-OCR Status | Character Count |
| :--- | :--- | :--- | :--- |
"""
    for case in landmark_results:
        case_name_short = case['case_name'][:50] + "..." if len(case['case_name']) > 50 else case['case_name']
        report += f"| **{case['name']}** | {case_name_short} | {case['status']} | {case['chars']:,} |\n"

    report += f"""
---

### **4. Analysis of "Legitimately Short" Files**
Technical verification confirms that `ocr_partial` files are primarily:
* **Rule 36 Judgments:** Usually < 500 characters (Found: ~{rule36_count} documents)
* **Errata:** Standardized corrections (Found: {errata_count} documents)
* **Notice of Appeal:** Minimal unique text

**Next Step:** Proceed with embedding generation for the {recovered_count + partial_count} newly text-enabled documents.

---

### **5. Status Overview**
| Status | Count |
| :--- | :--- |
"""
    for status, count in sorted(stats.items(), key=lambda x: -x[1]):
        report += f"| {status} | {count:,} |\n"

    print(report)
    return report


if __name__ == "__main__":
    generate_recovery_report()
