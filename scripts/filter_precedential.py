#!/usr/bin/env python3
"""
Filter CourtListener manifest to only include CAFC precedential opinions.
Uses Selenium to scrape CAFC's authoritative list, then matches against manifest.
"""

import os
import sys
import json
import time
import re
from datetime import datetime
from typing import List, Dict, Set, Tuple, Optional
from difflib import SequenceMatcher

MANIFEST_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "manifest.ndjson")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "manifest_precedential.ndjson")
CAFC_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "cafc_precedential_cache.ndjson")

CAFC_URL = "https://www.cafc.uscourts.gov/home/case-information/opinions-orders/"


def setup_driver():
    """Set up headless Chrome driver."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    
    chromium_path = '/nix/store/zi4f80l169xlmivz8vja8wlphq74qqk0-chromium-125.0.6422.141/bin/chromium'
    if os.path.exists(chromium_path):
        options.binary_location = chromium_path
    
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver


def wait_for_table(driver, timeout=30):
    """Wait for wpDataTables to finish loading."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    
    wait = WebDriverWait(driver, timeout)
    wait.until(EC.presence_of_element_located((By.ID, 'table_1')))
    time.sleep(2)
    
    for _ in range(15):
        try:
            processing = driver.find_element(By.ID, 'table_1_processing')
            if processing.get_attribute('style') and 'none' in processing.get_attribute('style'):
                break
        except:
            pass
        time.sleep(1)


def set_filters(driver):
    """Set filters for Precedential + OPINION."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select
    
    time.sleep(2)
    
    for select in driver.find_elements(By.CSS_SELECTOR, '.wpDataTableFilterSection select'):
        options_text = [opt.text for opt in select.find_elements(By.TAG_NAME, 'option')]
        if 'Precedential' in options_text:
            Select(select).select_by_visible_text('Precedential')
            print("  Selected: Precedential")
            time.sleep(2)
            wait_for_table(driver)
            break
    
    for select in driver.find_elements(By.CSS_SELECTOR, '.wpDataTableFilterSection select'):
        options_text = [opt.text for opt in select.find_elements(By.TAG_NAME, 'option')]
        if 'OPINION' in options_text:
            Select(select).select_by_visible_text('OPINION')
            print("  Selected: OPINION")
            time.sleep(2)
            wait_for_table(driver)
            break


def get_total_records(driver) -> int:
    """Get total number of filtered records."""
    from selenium.webdriver.common.by import By
    
    for _ in range(10):
        try:
            info = driver.find_element(By.ID, 'table_1_info')
            text = info.text
            match = re.search(r'of\s+([\d,]+)\s+entries', text)
            if match:
                return int(match.group(1).replace(',', ''))
        except:
            pass
        time.sleep(1)
    return 0


def parse_table_rows(driver, seen_keys: Set[Tuple]) -> Tuple[List[Dict], int]:
    """Parse current page of table rows with deduplication."""
    from selenium.webdriver.common.by import By
    
    opinions = []
    duplicates_on_page = 0
    
    try:
        table = driver.find_element(By.ID, 'table_1')
        tbody = table.find_element(By.TAG_NAME, 'tbody')
        rows = tbody.find_elements(By.TAG_NAME, 'tr')
        
        for row in rows:
            try:
                cells = row.find_elements(By.TAG_NAME, 'td')
                if len(cells) < 5:
                    continue
                
                if len(cells) == 5:
                    release_date = cells[0].text.strip()
                    appeal_number = cells[1].text.strip()
                    origin = cells[2].text.strip()
                    case_name = cells[3].text.strip()
                    status = cells[4].text.strip()
                    document_type = 'OPINION'
                    
                    pdf_url = None
                    try:
                        links = cells[3].find_elements(By.TAG_NAME, 'a')
                        if links:
                            pdf_url = links[0].get_attribute('href')
                    except:
                        pass
                else:
                    release_date = cells[0].text.strip()
                    appeal_number = cells[1].text.strip()
                    origin = cells[2].text.strip()
                    document_type = cells[3].text.strip()
                    case_name = cells[4].text.strip()
                    status = cells[5].text.strip()
                    
                    pdf_url = None
                    try:
                        links = cells[4].find_elements(By.TAG_NAME, 'a')
                        if links:
                            pdf_url = links[0].get_attribute('href')
                    except:
                        pass
                
                unique_key = (appeal_number, release_date, pdf_url)
                if unique_key in seen_keys:
                    duplicates_on_page += 1
                    continue
                
                seen_keys.add(unique_key)
                opinions.append({
                    'case_name': case_name,
                    'appeal_number': appeal_number,
                    'release_date': release_date,
                    'origin': origin,
                    'status': status,
                    'document_type': document_type,
                    'pdf_url': pdf_url,
                })
            except Exception as e:
                continue
    except Exception as e:
        print(f"  Error finding table: {e}")
    
    return opinions, duplicates_on_page


def click_next_page(driver) -> bool:
    """Click the next page button. Returns False if no more pages."""
    from selenium.webdriver.common.by import By
    
    try:
        selectors = [
            '#table_1_next',
            '.paginate_button.next',
            'a.next',
            '[data-dt-idx="next"]',
            '.dataTables_paginate .next'
        ]
        
        next_btn = None
        for selector in selectors:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, selector)
                if btn and btn.is_displayed():
                    next_btn = btn
                    break
            except:
                continue
        
        if not next_btn:
            return False
        
        class_attr = next_btn.get_attribute('class') or ''
        if 'disabled' in class_attr:
            return False
        
        driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
        time.sleep(0.5)
        
        try:
            next_btn.click()
        except:
            driver.execute_script("arguments[0].click();", next_btn)
        
        time.sleep(2)
        wait_for_table(driver)
        return True
    except Exception as e:
        print(f"  Error clicking next: {e}")
        return False


def scrape_cafc_precedential(max_pages: Optional[int] = None) -> List[Dict]:
    """Scrape all precedential opinions from CAFC website."""
    
    # Check cache first
    if os.path.exists(CAFC_CACHE_FILE):
        print(f"Loading from cache: {CAFC_CACHE_FILE}")
        with open(CAFC_CACHE_FILE) as f:
            records = [json.loads(line) for line in f]
        print(f"  Loaded {len(records)} cached records")
        return records
    
    print("Scraping CAFC precedential opinions...")
    driver = setup_driver()
    all_records = []
    seen = set()
    
    try:
        print(f"  Loading: {CAFC_URL}")
        driver.get(CAFC_URL)
        wait_for_table(driver)
        
        set_filters(driver)
        total = get_total_records(driver)
        print(f"  Total precedential opinions: {total}")
        
        page = 1
        while True:
            if max_pages and page > max_pages:
                print(f"  Reached max pages limit ({max_pages})")
                break
            
            print(f"  Page {page}...", end=" ", flush=True)
            records, dups = parse_table_rows(driver, seen)
            all_records.extend(records)
            
            print(f"{len(records)} new, {dups} dups (total: {len(all_records)})")
            
            if not click_next_page(driver):
                print("  Reached last page")
                break
            page += 1
        
    finally:
        driver.quit()
    
    # Cache results
    print(f"\nCaching {len(all_records)} records to {CAFC_CACHE_FILE}...")
    with open(CAFC_CACHE_FILE, 'w') as f:
        for r in all_records:
            f.write(json.dumps(r) + "\n")
    
    return all_records


def normalize_case_name(name: str) -> str:
    """Normalize case name for matching."""
    name = name.lower()
    name = re.sub(r'\s+', ' ', name)
    name = re.sub(r'[^\w\s]', '', name)
    name = name.strip()
    return name


def normalize_date(date_str: str) -> str:
    """Normalize date to YYYY-MM-DD."""
    for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y"]:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except:
            pass
    return date_str


def similarity(a: str, b: str) -> float:
    """Calculate string similarity."""
    return SequenceMatcher(None, a, b).ratio()


def match_records(cafc_records: List[Dict], manifest_records: List[Dict]) -> List[Dict]:
    """Match CAFC records to CourtListener manifest."""
    
    print(f"\nMatching {len(cafc_records)} CAFC records against {len(manifest_records)} manifest records...")
    
    # Build lookup by normalized date
    manifest_by_date = {}
    for r in manifest_records:
        date = normalize_date(r.get("release_date", ""))
        if date not in manifest_by_date:
            manifest_by_date[date] = []
        manifest_by_date[date].append(r)
    
    matched = []
    unmatched_cafc = []
    
    for cafc in cafc_records:
        cafc_date = normalize_date(cafc.get("release_date", ""))
        cafc_name = normalize_case_name(cafc.get("case_name", ""))
        
        candidates = manifest_by_date.get(cafc_date, [])
        
        best_match = None
        best_score = 0
        
        for m in candidates:
            m_name = normalize_case_name(m.get("case_name", ""))
            score = similarity(cafc_name, m_name)
            if score > best_score:
                best_score = score
                best_match = m
        
        if best_match and best_score >= 0.6:
            enriched = {
                **best_match,
                "appeal_number": cafc.get("appeal_number", ""),
                "pdf_url": cafc.get("pdf_url", ""),
                "status": "Precedential",
                "document_type": "OPINION",
                "precedential_status_verified": True,
                "match_score": round(best_score, 3),
            }
            matched.append(enriched)
        else:
            unmatched_cafc.append(cafc)
    
    print(f"  Matched to CourtListener: {len(matched)}")
    print(f"  CAFC-only (no CourtListener match): {len(unmatched_cafc)}")
    
    # Add unmatched CAFC records directly (they're authoritative)
    for cafc in unmatched_cafc:
        record = {
            "case_name": cafc.get("case_name", ""),
            "appeal_number": cafc.get("appeal_number", ""),
            "release_date": normalize_date(cafc.get("release_date", "")),
            "pdf_url": cafc.get("pdf_url", ""),
            "courtlistener_cluster_id": None,
            "courtlistener_url": "",
            "status": "Precedential",
            "document_type": "OPINION",
            "precedential_status_verified": True,
            "match_score": 0,
        }
        matched.append(record)
    
    print(f"  Total precedential records: {len(matched)}")
    return matched


def main():
    print("=" * 60)
    print("CAFC Precedential Filter")
    print("=" * 60)
    
    # Load manifest
    print(f"\nLoading manifest: {MANIFEST_FILE}")
    with open(MANIFEST_FILE) as f:
        manifest = [json.loads(line) for line in f]
    print(f"  Loaded {len(manifest)} records")
    
    # Scrape CAFC precedential list (no page limit for full scrape)
    cafc_records = scrape_cafc_precedential(max_pages=None)
    
    # Match records
    matched = match_records(cafc_records, manifest)
    
    # Deduplicate by appeal_number + date
    seen = set()
    unique = []
    for r in matched:
        key = (r.get("appeal_number", ""), r.get("release_date", ""))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    
    print(f"\nAfter deduplication: {len(unique)} unique records")
    
    # Save output
    print(f"\nSaving to: {OUTPUT_FILE}")
    with open(OUTPUT_FILE, 'w') as f:
        for r in unique:
            f.write(json.dumps(r) + "\n")
    
    print("\nDone!")
    print(f"  Output: {OUTPUT_FILE}")
    print(f"  Total precedential opinions: {len(unique)}")


if __name__ == "__main__":
    main()
