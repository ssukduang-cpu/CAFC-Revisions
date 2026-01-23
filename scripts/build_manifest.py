#!/usr/bin/env python3
"""
Playwright-based manifest builder for CAFC precedential opinions.
Paginates through the CAFC website, applies filters, and extracts all opinion metadata.
"""
import asyncio
import json
import os
import random
import sys
from datetime import datetime
from typing import Dict, List, Optional

CAFC_URL = "https://www.cafc.uscourts.gov/home/case-information/opinions-orders/"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
MANIFEST_FILE = os.path.join(DATA_DIR, "manifest.ndjson")
PROGRESS_FILE = os.path.join(DATA_DIR, "manifest_progress.json")

MIN_DELAY_MS = 500
MAX_DELAY_MS = 1500

async def build_manifest(
    headless: bool = True,
    max_pages: Optional[int] = None,
    resume: bool = True
):
    from playwright.async_api import async_playwright
    
    os.makedirs(DATA_DIR, exist_ok=True)
    
    progress = {"page": 0, "rows_collected": 0, "unique_urls": set()}
    if resume and os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            saved = json.load(f)
            progress["page"] = saved.get("page", 0)
            progress["rows_collected"] = saved.get("rows_collected", 0)
            progress["unique_urls"] = set(saved.get("unique_urls", []))
            print(f"Resuming from page {progress['page']}, {progress['rows_collected']} rows collected")
    
    all_opinions = []
    if resume and os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE, "r") as f:
            for line in f:
                if line.strip():
                    opinion = json.loads(line)
                    all_opinions.append(opinion)
                    progress["unique_urls"].add(opinion["pdf_url"])
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        print(f"Navigating to {CAFC_URL}")
        await page.goto(CAFC_URL, wait_until="networkidle", timeout=60000)
        
        await asyncio.sleep(2)
        
        try:
            status_filter = page.locator("select").filter(has_text="Precedential")
            if await status_filter.count() > 0:
                print("Applying Status filter: Precedential")
                await status_filter.first.select_option(label="Precedential")
                await asyncio.sleep(1)
        except Exception as e:
            print(f"Could not apply Status filter: {e}")
        
        try:
            doc_type_filter = page.locator("select").filter(has_text="OPINION")
            if await doc_type_filter.count() > 0:
                print("Applying Document Type filter: OPINION")
                await doc_type_filter.first.select_option(label="OPINION")
                await asyncio.sleep(1)
        except Exception as e:
            print(f"Could not apply Document Type filter: {e}")
        
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)
        
        current_page = 0
        pages_without_new_data = 0
        max_empty_pages = 3
        
        while True:
            if max_pages and current_page >= max_pages:
                print(f"Reached max pages limit ({max_pages})")
                break
            
            if current_page < progress["page"]:
                print(f"Skipping already processed page {current_page}")
                try:
                    next_btn = page.locator("a.paginate_button.next:not(.disabled)")
                    if await next_btn.count() > 0:
                        await next_btn.click()
                        await page.wait_for_load_state("networkidle")
                        await asyncio.sleep(random.randint(MIN_DELAY_MS, MAX_DELAY_MS) / 1000)
                        current_page += 1
                        continue
                except:
                    pass
            
            print(f"\n--- Processing page {current_page + 1} ---")
            
            rows = page.locator("table#table_1 tbody tr")
            row_count = await rows.count()
            
            if row_count == 0:
                print("No rows found on this page")
                pages_without_new_data += 1
                if pages_without_new_data >= max_empty_pages:
                    print(f"No data for {max_empty_pages} consecutive pages, stopping")
                    break
            
            new_rows_on_page = 0
            
            for i in range(row_count):
                try:
                    row = rows.nth(i)
                    cells = row.locator("td")
                    cell_count = await cells.count()
                    
                    if cell_count < 6:
                        continue
                    
                    release_date = await cells.nth(0).inner_text()
                    appeal_number = await cells.nth(1).inner_text()
                    origin = await cells.nth(2).inner_text()
                    document_type = await cells.nth(3).inner_text()
                    
                    case_cell = cells.nth(4)
                    case_name = await case_cell.inner_text()
                    link = case_cell.locator("a")
                    
                    if await link.count() == 0:
                        continue
                    
                    pdf_url = await link.get_attribute("href")
                    if pdf_url and pdf_url.startswith("/"):
                        pdf_url = "https://www.cafc.uscourts.gov" + pdf_url
                    
                    status = await cells.nth(5).inner_text() if cell_count > 5 else ""
                    file_path = await cells.nth(6).inner_text() if cell_count > 6 else ""
                    
                    status = status.strip()
                    document_type = document_type.strip()
                    
                    if status != "Precedential" or document_type != "OPINION":
                        continue
                    
                    if pdf_url in progress["unique_urls"]:
                        continue
                    
                    opinion = {
                        "release_date": release_date.strip(),
                        "appeal_number": appeal_number.strip(),
                        "origin": origin.strip(),
                        "document_type": document_type,
                        "case_name": case_name.strip(),
                        "pdf_url": pdf_url,
                        "status": status,
                        "file_path": file_path.strip() if file_path else None,
                        "scraped_at": datetime.utcnow().isoformat()
                    }
                    
                    all_opinions.append(opinion)
                    progress["unique_urls"].add(pdf_url)
                    progress["rows_collected"] += 1
                    new_rows_on_page += 1
                    
                    with open(MANIFEST_FILE, "a") as f:
                        f.write(json.dumps(opinion) + "\n")
                    
                except Exception as e:
                    print(f"Error processing row {i}: {e}")
                    continue
            
            print(f"Found {new_rows_on_page} new opinions on page {current_page + 1}")
            
            if new_rows_on_page == 0:
                pages_without_new_data += 1
            else:
                pages_without_new_data = 0
            
            progress["page"] = current_page + 1
            save_progress(progress)
            
            if pages_without_new_data >= max_empty_pages:
                print(f"No new data for {max_empty_pages} consecutive pages, stopping")
                break
            
            try:
                next_btn = page.locator("a.paginate_button.next:not(.disabled)")
                if await next_btn.count() == 0:
                    print("No more pages (next button disabled or not found)")
                    break
                
                await next_btn.click()
                await page.wait_for_load_state("networkidle")
                
                delay = random.randint(MIN_DELAY_MS, MAX_DELAY_MS) / 1000
                await asyncio.sleep(delay)
                
                current_page += 1
                
            except Exception as e:
                print(f"Error navigating to next page: {e}")
                break
        
        await browser.close()
    
    print(f"\n=== Manifest Build Complete ===")
    print(f"Total opinions collected: {len(all_opinions)}")
    print(f"Unique PDF URLs: {len(progress['unique_urls'])}")
    print(f"Manifest saved to: {MANIFEST_FILE}")
    
    return all_opinions

def save_progress(progress: Dict):
    with open(PROGRESS_FILE, "w") as f:
        json.dump({
            "page": progress["page"],
            "rows_collected": progress["rows_collected"],
            "unique_urls": list(progress["unique_urls"]),
            "updated_at": datetime.utcnow().isoformat()
        }, f, indent=2)

async def load_manifest_to_db():
    """Load manifest file into database."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from backend import db_postgres as db
    
    db.init_db()
    
    if not os.path.exists(MANIFEST_FILE):
        print(f"Manifest file not found: {MANIFEST_FILE}")
        return
    
    count = 0
    with open(MANIFEST_FILE, "r") as f:
        for line in f:
            if line.strip():
                opinion = json.loads(line)
                db.upsert_document({
                    "pdf_url": opinion["pdf_url"],
                    "case_name": opinion["case_name"],
                    "appeal_number": opinion["appeal_number"],
                    "release_date": opinion["release_date"],
                    "origin": opinion["origin"],
                    "document_type": opinion["document_type"],
                    "status": opinion["status"],
                    "file_path": opinion.get("file_path")
                })
                count += 1
                if count % 100 == 0:
                    print(f"Loaded {count} documents...")
    
    print(f"Loaded {count} documents into database")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build CAFC opinion manifest")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser in headless mode")
    parser.add_argument("--no-headless", action="store_false", dest="headless", help="Run browser with visible window")
    parser.add_argument("--max-pages", type=int, default=None, help="Maximum pages to process")
    parser.add_argument("--no-resume", action="store_true", help="Start fresh, don't resume from progress")
    parser.add_argument("--load-to-db", action="store_true", help="Load existing manifest into database")
    
    args = parser.parse_args()
    
    if args.load_to_db:
        asyncio.run(load_manifest_to_db())
    else:
        asyncio.run(build_manifest(
            headless=args.headless,
            max_pages=args.max_pages,
            resume=not args.no_resume
        ))

if __name__ == "__main__":
    main()
