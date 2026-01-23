#!/usr/bin/env python3
"""
Build CAFC precedential opinions manifest using Selenium with headless Chromium.
This scrapes the CAFC website's wpDataTables directly.
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime
from typing import List, Dict, Optional

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
    
    for _ in range(10):
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

def parse_table_rows(driver) -> List[Dict]:
    """Parse current page of table rows."""
    from selenium.webdriver.common.by import By
    
    opinions = []
    
    try:
        table = driver.find_element(By.ID, 'table_1')
        tbody = table.find_element(By.TAG_NAME, 'tbody')
        rows = tbody.find_elements(By.TAG_NAME, 'tr')
        
        print(f"  Found {len(rows)} rows in table")
        
        for i, row in enumerate(rows):
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
                print(f"  Error parsing row: {e}")
                continue
    except Exception as e:
        print(f"  Error finding table: {e}")
        driver.save_screenshot('/tmp/debug_screenshot.png')
        print("  Screenshot saved to /tmp/debug_screenshot.png")
    
    return opinions

def click_next_page(driver) -> bool:
    """Click the next page button. Returns False if no more pages."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    
    try:
        next_btn = driver.find_element(By.CSS_SELECTOR, '#table_1_next, .paginate_button.next')
        class_attr = next_btn.get_attribute('class') or ''
        if 'disabled' in class_attr:
            return False
        
        next_btn.click()
        time.sleep(2)
        wait_for_table(driver)
        return True
    except Exception as e:
        print(f"  Pagination error: {e}")
        
        try:
            paginate_btns = driver.find_elements(By.CSS_SELECTOR, '.paginate_button:not(.previous):not(.next):not(.disabled)')
            current = driver.find_element(By.CSS_SELECTOR, '.paginate_button.current')
            current_page = int(current.text)
            
            for btn in paginate_btns:
                try:
                    page_num = int(btn.text)
                    if page_num == current_page + 1:
                        btn.click()
                        time.sleep(2)
                        wait_for_table(driver)
                        return True
                except:
                    continue
        except:
            pass
        
        return False

def set_page_length(driver, length=100):
    """Set the number of entries per page."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select
    
    try:
        length_select = driver.find_element(By.NAME, 'table_1_length')
        select = Select(length_select)
        select.select_by_value(str(length))
        print(f"  Set page length to {length}")
        time.sleep(2)
        wait_for_table(driver)
    except Exception as e:
        print(f"  Could not set page length: {e}")

def scrape_all_opinions(max_pages: Optional[int] = None, page_length: int = 100) -> List[Dict]:
    """Scrape all precedential CAFC opinions."""
    print("Setting up Selenium driver...")
    driver = setup_driver()
    all_opinions = []
    
    try:
        print("Loading CAFC opinions page...")
        driver.get("https://www.cafc.uscourts.gov/home/case-information/opinions-orders/")
        wait_for_table(driver)
        
        print("Setting filters...")
        set_filters(driver, status='Precedential', doc_type='OPINION')
        
        try:
            set_page_length(driver, page_length)
        except:
            pass
        
        total = get_total_records(driver)
        print(f"Total precedential opinions: {total}")
        
        page = 1
        while True:
            print(f"Scraping page {page}...")
            opinions = parse_table_rows(driver)
            
            if not opinions:
                print("  No opinions found on this page")
                break
            
            all_opinions.extend(opinions)
            print(f"  Found {len(opinions)} opinions (total: {len(all_opinions)})")
            
            if max_pages and page >= max_pages:
                print(f"Reached max pages limit ({max_pages})")
                break
            
            if len(all_opinions) >= total:
                print("All opinions collected")
                break
            
            if not click_next_page(driver):
                print("No more pages")
                break
            
            page += 1
            time.sleep(0.5)
        
    finally:
        driver.quit()
    
    return all_opinions

def save_manifest(opinions: List[Dict], output_dir: str = "data"):
    """Save opinions to manifest files."""
    os.makedirs(output_dir, exist_ok=True)
    
    json_path = os.path.join(output_dir, "manifest.json")
    with open(json_path, 'w') as f:
        json.dump(opinions, f, indent=2)
    print(f"Saved {len(opinions)} opinions to {json_path}")
    
    ndjson_path = os.path.join(output_dir, "manifest.ndjson")
    with open(ndjson_path, 'w') as f:
        for opinion in opinions:
            f.write(json.dumps(opinion) + '\n')
    print(f"Saved {len(opinions)} opinions to {ndjson_path}")
    
    return json_path, ndjson_path

def main():
    parser = argparse.ArgumentParser(description="Scrape CAFC Precedential Opinions with Selenium")
    parser.add_argument("--max-pages", type=int, help="Maximum pages to scrape")
    parser.add_argument("--page-length", type=int, default=100, help="Entries per page")
    parser.add_argument("--output", default="data", help="Output directory")
    args = parser.parse_args()
    
    opinions = scrape_all_opinions(
        max_pages=args.max_pages,
        page_length=args.page_length
    )
    
    if opinions:
        save_manifest(opinions, args.output)
        print(f"\nComplete! Scraped {len(opinions)} precedential opinions from CAFC website.")
    else:
        print("No opinions found.")

if __name__ == "__main__":
    main()
