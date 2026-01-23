#!/usr/bin/env python3
"""
Build CAFC precedential opinions manifest using Selenium with headless Chromium.
This scrapes the CAFC website's wpDataTables directly with in-memory deduplication.
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime
from typing import List, Dict, Optional, Set, Tuple

def setup_driver():
    """Set up headless Chrome driver."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
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

def set_filters(driver, status='Precedential', doc_type='OPINION'):
    """Set the wpDataTables filters for Status and Document Type."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select
    
    time.sleep(2)
    
    try:
        status_filter = None
        for select in driver.find_elements(By.CSS_SELECTOR, '.wpDataTableFilterSection select'):
            options_text = [opt.text for opt in select.find_elements(By.TAG_NAME, 'option')]
            if 'Precedential' in options_text:
                status_filter = Select(select)
                break
        
        if status_filter:
            status_filter.select_by_visible_text(status)
            print(f"  Selected Status: {status}")
            time.sleep(2)
            wait_for_table(driver)
    except Exception as e:
        print(f"  Error setting status filter: {e}")
    
    try:
        doc_type_filter = None
        for select in driver.find_elements(By.CSS_SELECTOR, '.wpDataTableFilterSection select'):
            options_text = [opt.text for opt in select.find_elements(By.TAG_NAME, 'option')]
            if 'OPINION' in options_text:
                doc_type_filter = Select(select)
                break
        
        if doc_type_filter:
            doc_type_filter.select_by_visible_text(doc_type)
            print(f"  Selected Document Type: {doc_type}")
            time.sleep(2)
            wait_for_table(driver)
    except Exception as e:
        print(f"  Error setting doc type filter: {e}")
    
    wait_for_table(driver)

def get_total_records(driver) -> int:
    """Get total number of filtered records."""
    from selenium.webdriver.common.by import By
    
    try:
        info = driver.find_element(By.ID, 'table_1_info')
        text = info.text
        import re
        match = re.search(r'of (\d+(?:,\d+)*) entries', text)
        if match:
            return int(match.group(1).replace(',', ''))
    except:
        pass
    return 0

def parse_table_rows(driver, seen_keys: Set[Tuple[str, str]]) -> Tuple[List[Dict], int]:
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
                    file_path = None
                    
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
                    file_path = cells[6].text.strip() if len(cells) > 6 else None
                    
                    pdf_url = None
                    try:
                        links = cells[4].find_elements(By.TAG_NAME, 'a')
                        if links:
                            pdf_url = links[0].get_attribute('href')
                    except:
                        pass
                
                # Deduplication check using stable key: appeal_number + release_date + pdf_url
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
                    'file_path': file_path
                })
            except Exception as e:
                continue
    except Exception as e:
        print(f"  Error finding table: {e}")
    
    return opinions, duplicates_on_page

def click_next_page(driver) -> bool:
    """Click the next page button. Returns False if no more pages."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    
    try:
        # Try multiple selectors for the next button
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
            print("    [DEBUG] Next button not found")
            return False
        
        class_attr = next_btn.get_attribute('class') or ''
        if 'disabled' in class_attr:
            print("    [DEBUG] Next button is disabled - reached last page")
            return False
        
        # Scroll into view and click
        driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
        time.sleep(0.5)
        
        try:
            next_btn.click()
        except:
            # If regular click fails, try JavaScript click
            driver.execute_script("arguments[0].click();", next_btn)
        
        time.sleep(2)
        wait_for_table(driver)
        return True
    except Exception as e:
        print(f"    [DEBUG] Error clicking next: {e}")
        return False

def scrape_all_opinions(max_pages: Optional[int] = None) -> Tuple[List[Dict], int]:
    """Scrape all precedential CAFC opinions with in-memory deduplication."""
    print("Setting up Selenium driver...")
    driver = setup_driver()
    all_opinions = []
    seen_keys = set()
    total_duplicates = 0
    
    try:
        print("Loading CAFC opinions page...")
        driver.get("https://www.cafc.uscourts.gov/home/case-information/opinions-orders/")
        wait_for_table(driver)
        
        print("Setting filters (Precedential + OPINION)...")
        set_filters(driver, status='Precedential', doc_type='OPINION')
        
        total_expected = get_total_records(driver)
        print(f"Total precedential opinions expected: {total_expected}")
        
        page = 1
        while True:
            opinions, page_duplicates = parse_table_rows(driver, seen_keys)
            all_opinions.extend(opinions)
            total_duplicates += page_duplicates
            
            print(f"  Page {page}: Found {len(opinions)} new unique opinions ({page_duplicates} duplicates skipped). Total: {len(all_opinions)}")
            
            if max_pages and page >= max_pages:
                break
            
            if not click_next_page(driver):
                break
            
            page += 1
            
    finally:
        driver.quit()
    
    return all_opinions, total_duplicates

def final_dedupe(opinions: List[Dict]) -> Tuple[List[Dict], int]:
    """Run a final dedupe pass using stable key: appeal_number + release_date + pdf_url."""
    unique_opinions = []
    seen = set()
    duplicates = 0
    
    for op in opinions:
        key = (op['appeal_number'], op['release_date'], op['pdf_url'])
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique_opinions.append(op)
        
    return unique_opinions, duplicates

def main():
    parser = argparse.ArgumentParser(description="Scrape CAFC Precedential Opinions with Deduplication")
    parser.add_argument("--max-pages", type=int, help="Maximum pages to scrape")
    parser.add_argument("--output", default="data/manifest.ndjson", help="Output file path (NDJSON)")
    args = parser.parse_args()
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    
    # 1) Discard any partially generated manifest
    if os.path.exists(args.output):
        os.remove(args.output)
        print(f"Clean start: removed existing {args.output}")

    # 2) Re-run the scrape from the beginning
    start_time = time.time()
    raw_opinions, scrape_duplicates = scrape_all_opinions(max_pages=args.max_pages)
    
    # 3) Final dedupe pass using stable key: appeal_number + release_date + pdf_url
    unique_opinions, final_duplicates = final_dedupe(raw_opinions)
    
    # 4) Write ONLY unique rows to data/manifest.ndjson (primary output)
    with open(args.output, 'w') as f:
        for op in unique_opinions:
            f.write(json.dumps(op) + '\n')
    
    # Also write JSON version for convenience
    json_output = args.output.replace('.ndjson', '.json')
    with open(json_output, 'w') as f:
        json.dump(unique_opinions, f, indent=2)

    duration = time.time() - start_time
    total_collected = len(raw_opinions) + scrape_duplicates
    
    print("\n" + "="*60)
    print("MANIFEST BUILD COMPLETE")
    print("="*60)
    print(f"Duration: {duration:.1f}s")
    print(f"Filters: Status=Precedential, DocumentType=OPINION")
    print(f"Deduplication key: (appeal_number, release_date, pdf_url)")
    print("-"*60)
    print(f"total_rows_collected:      {total_collected}")
    print(f"total_unique_after_dedupe: {len(unique_opinions)}")
    print(f"duplicates_removed:        {scrape_duplicates + final_duplicates}")
    print("-"*60)
    print(f"Output: {args.output}")
    print("="*60)

if __name__ == "__main__":
    main()
