#!/usr/bin/env python3
"""
Scrape CAFC precedential opinions directly (no CourtListener matching).
CAFC is the authoritative source with PDF URLs.

This script runs in chunks to avoid timeouts.
"""

import os
import sys
import json
import time
import re
from typing import List, Dict, Set, Tuple

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "manifest_precedential.ndjson")
PROGRESS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "scrape_progress.json")

CAFC_URL = "https://www.cafc.uscourts.gov/home/case-information/opinions-orders/"


def setup_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
    
    chromium_path = '/nix/store/zi4f80l169xlmivz8vja8wlphq74qqk0-chromium-125.0.6422.141/bin/chromium'
    if os.path.exists(chromium_path):
        options.binary_location = chromium_path
    
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver


def wait_for_table(driver, timeout=30):
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
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select
    
    time.sleep(2)
    
    for select in driver.find_elements(By.CSS_SELECTOR, '.wpDataTableFilterSection select'):
        options_text = [opt.text for opt in select.find_elements(By.TAG_NAME, 'option')]
        if 'Precedential' in options_text:
            Select(select).select_by_visible_text('Precedential')
            time.sleep(2)
            wait_for_table(driver)
            break
    
    for select in driver.find_elements(By.CSS_SELECTOR, '.wpDataTableFilterSection select'):
        options_text = [opt.text for opt in select.find_elements(By.TAG_NAME, 'option')]
        if 'OPINION' in options_text:
            Select(select).select_by_visible_text('OPINION')
            time.sleep(2)
            wait_for_table(driver)
            break


def get_total(driver) -> int:
    from selenium.webdriver.common.by import By
    try:
        info = driver.find_element(By.ID, 'table_1_info')
        match = re.search(r'of\s+([\d,]+)\s+entries', info.text)
        if match:
            return int(match.group(1).replace(',', ''))
    except:
        pass
    return 0


def parse_rows(driver, seen: Set[Tuple]) -> List[Dict]:
    from selenium.webdriver.common.by import By
    
    records = []
    try:
        rows = driver.find_elements(By.CSS_SELECTOR, '#table_1 tbody tr')
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, 'td')
            if len(cells) < 5:
                continue
            
            if len(cells) == 5:
                release_date = cells[0].text.strip()
                appeal_number = cells[1].text.strip()
                origin = cells[2].text.strip()
                case_name = cells[3].text.strip()
                status = cells[4].text.strip()
                doc_type = 'OPINION'
                pdf_url = ""
                try:
                    link = cells[3].find_element(By.TAG_NAME, 'a')
                    pdf_url = link.get_attribute('href') or ""
                except:
                    pass
            else:
                release_date = cells[0].text.strip()
                appeal_number = cells[1].text.strip()
                origin = cells[2].text.strip()
                doc_type = cells[3].text.strip()
                case_name = cells[4].text.strip()
                status = cells[5].text.strip()
                pdf_url = ""
                try:
                    link = cells[4].find_element(By.TAG_NAME, 'a')
                    pdf_url = link.get_attribute('href') or ""
                except:
                    pass
            
            key = (appeal_number, release_date, pdf_url)
            if key in seen:
                continue
            seen.add(key)
            
            records.append({
                "case_name": case_name,
                "appeal_number": appeal_number,
                "release_date": release_date,
                "origin": origin,
                "pdf_url": pdf_url,
                "status": "Precedential",
                "document_type": "OPINION",
                "precedential_status_verified": True,
            })
    except Exception as e:
        print(f"  Error: {e}")
    
    return records


def click_next(driver) -> bool:
    from selenium.webdriver.common.by import By
    
    try:
        for selector in ['#table_1_next', '.paginate_button.next']:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, selector)
                if btn and btn.is_displayed():
                    if 'disabled' in (btn.get_attribute('class') or ''):
                        return False
                    driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                    time.sleep(0.3)
                    try:
                        btn.click()
                    except:
                        driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1.5)
                    wait_for_table(driver)
                    return True
            except:
                continue
    except:
        pass
    return False


def go_to_page(driver, page_num: int):
    """Navigate to a specific page number."""
    from selenium.webdriver.common.by import By
    
    for _ in range(page_num - 1):
        if not click_next(driver):
            break


def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"records": [], "last_page": 0, "seen_keys": []}


def save_progress(records: List[Dict], last_page: int, seen_keys: Set[Tuple]):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump({
            "records": records,
            "last_page": last_page,
            "seen_keys": list(seen_keys),
        }, f)


def main():
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else None
    
    print("=" * 50)
    print("CAFC Precedential Scraper")
    print("=" * 50)
    
    # Load progress
    progress = load_progress()
    all_records = progress.get("records", [])
    start_page = progress.get("last_page", 0) + 1
    seen = set(tuple(k) for k in progress.get("seen_keys", []))
    
    if start_page > 1:
        print(f"Resuming from page {start_page} ({len(all_records)} records so far)")
    
    print("Starting browser...")
    driver = setup_driver()
    
    try:
        driver.get(CAFC_URL)
        wait_for_table(driver)
        set_filters(driver)
        
        total = get_total(driver)
        print(f"Total precedential opinions: {total}")
        
        if start_page > 1:
            print(f"Navigating to page {start_page}...")
            go_to_page(driver, start_page)
        
        page = start_page
        while True:
            if max_pages and page > max_pages:
                break
            
            print(f"Page {page}...", end=" ", flush=True)
            records = parse_rows(driver, seen)
            all_records.extend(records)
            print(f"{len(records)} new (total: {len(all_records)})")
            
            # Save progress every 10 pages
            if page % 10 == 0:
                save_progress(all_records, page, seen)
            
            if not click_next(driver):
                print("Reached last page")
                break
            page += 1
        
    finally:
        driver.quit()
    
    # Save final output
    print(f"\nSaving {len(all_records)} records to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w') as f:
        for r in all_records:
            f.write(json.dumps(r) + "\n")
    
    # Clear progress file
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
    
    print("\nDone!")
    print(f"Total: {len(all_records)} precedential opinions")


if __name__ == "__main__":
    main()
