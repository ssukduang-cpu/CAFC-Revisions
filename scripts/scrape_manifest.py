#!/usr/bin/env python3
"""
Scrape CAFC opinions manifest using HTTP requests.
Extracts all Precedential OPINION documents from the CAFC website.
"""

import os
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

BASE_URL = "https://www.cafc.uscourts.gov"
OPINIONS_URL = f"{BASE_URL}/home/case-information/opinions-orders/"

def get_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    return session

def parse_table_rows(soup):
    """Parse opinion rows from the table."""
    opinions = []
    table = soup.find('table', {'id': 'table_1'})
    if not table:
        return opinions
    
    tbody = table.find('tbody')
    if not tbody:
        return opinions
    
    rows = tbody.find_all('tr')
    
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 6:
            continue
        
        release_date = cells[0].get_text(strip=True)
        appeal_number = cells[1].get_text(strip=True)
        origin = cells[2].get_text(strip=True)
        document_type = cells[3].get_text(strip=True)
        case_name = cells[4].get_text(strip=True)
        status = cells[5].get_text(strip=True)
        
        link = cells[4].find('a')
        pdf_path = link.get('href') if link else None
        if pdf_path and not pdf_path.startswith('http'):
            pdf_url = f"{BASE_URL}{pdf_path}"
        else:
            pdf_url = pdf_path
        
        file_path = cells[6].get_text(strip=True) if len(cells) > 6 else None
        
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
    
    return opinions

def fetch_with_filters(session, status_filter="Precedential", doctype_filter="OPINION", page=0, page_size=100):
    """Fetch opinions with server-side filtering using wpDataTables AJAX."""
    
    resp = session.get(OPINIONS_URL)
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    nonce_input = soup.find('input', {'id': 'wdtNonceFrontendServerSide_1'})
    nonce = nonce_input.get('value') if nonce_input else ''
    
    session.headers.update({
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Referer': OPINIONS_URL
    })
    
    data = {
        'action': 'get_wdtable',
        'table_id': '1',
        'draw': str(page + 1),
        'start': str(page * page_size),
        'length': str(page_size),
        'wdtNonce': nonce,
        'wdtNonceFrontendServerSide_1': nonce,
        'columns[0][data]': '0',
        'columns[0][name]': '',
        'columns[0][searchable]': 'true',
        'columns[0][orderable]': 'true',
        'columns[0][search][value]': '',
        'columns[0][search][regex]': 'false',
        'columns[1][data]': '1',
        'columns[1][name]': '',
        'columns[1][searchable]': 'true',
        'columns[1][orderable]': 'true',
        'columns[1][search][value]': '',
        'columns[1][search][regex]': 'false',
        'columns[2][data]': '2',
        'columns[2][name]': '',
        'columns[2][searchable]': 'true',
        'columns[2][orderable]': 'true',
        'columns[2][search][value]': '',
        'columns[2][search][regex]': 'false',
        'columns[3][data]': '3',
        'columns[3][name]': '',
        'columns[3][searchable]': 'true',
        'columns[3][orderable]': 'true',
        'columns[3][search][value]': doctype_filter,
        'columns[3][search][regex]': 'false',
        'columns[4][data]': '4',
        'columns[4][name]': '',
        'columns[4][searchable]': 'true',
        'columns[4][orderable]': 'true',
        'columns[4][search][value]': '',
        'columns[4][search][regex]': 'false',
        'columns[5][data]': '5',
        'columns[5][name]': '',
        'columns[5][searchable]': 'true',
        'columns[5][orderable]': 'true',
        'columns[5][search][value]': status_filter,
        'columns[5][search][regex]': 'false',
        'columns[6][data]': '6',
        'columns[6][name]': '',
        'columns[6][searchable]': 'true',
        'columns[6][orderable]': 'false',
        'columns[6][search][value]': '',
        'columns[6][search][regex]': 'false',
        'order[0][column]': '0',
        'order[0][dir]': 'desc',
        'search[value]': '',
        'search[regex]': 'false',
    }
    
    ajax_resp = session.post(f"{BASE_URL}/wp-admin/admin-ajax.php", data=data)
    
    if ajax_resp.status_code == 200 and ajax_resp.text:
        try:
            result = ajax_resp.json()
            return result
        except json.JSONDecodeError:
            return None
    return None

def parse_ajax_response(data):
    """Parse AJAX response from wpDataTables."""
    opinions = []
    
    if not data or 'data' not in data:
        return opinions, 0
    
    total = data.get('recordsFiltered', 0)
    
    for row in data.get('data', []):
        if len(row) < 6:
            continue
        
        release_date = BeautifulSoup(str(row[0]), 'html.parser').get_text(strip=True)
        appeal_number = BeautifulSoup(str(row[1]), 'html.parser').get_text(strip=True)
        origin = BeautifulSoup(str(row[2]), 'html.parser').get_text(strip=True)
        document_type = BeautifulSoup(str(row[3]), 'html.parser').get_text(strip=True)
        
        case_cell = BeautifulSoup(str(row[4]), 'html.parser')
        case_name = case_cell.get_text(strip=True)
        link = case_cell.find('a')
        pdf_path = link.get('href') if link else None
        if pdf_path and not pdf_path.startswith('http'):
            pdf_url = f"{BASE_URL}{pdf_path}"
        else:
            pdf_url = pdf_path
        
        status = BeautifulSoup(str(row[5]), 'html.parser').get_text(strip=True)
        file_path = BeautifulSoup(str(row[6]), 'html.parser').get_text(strip=True) if len(row) > 6 else None
        
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
    
    return opinions, total

def scrape_all_precedential_opinions(max_pages=None, page_size=100):
    """Scrape all precedential opinions from CAFC website."""
    session = get_session()
    all_opinions = []
    page = 0
    total = None
    
    print("Starting scrape of CAFC Precedential Opinions...")
    
    while True:
        print(f"Fetching page {page + 1}...")
        
        result = fetch_with_filters(
            session, 
            status_filter="Precedential",
            doctype_filter="OPINION",
            page=page,
            page_size=page_size
        )
        
        if result is None:
            print("AJAX request failed, falling back to HTML parsing...")
            resp = session.get(OPINIONS_URL)
            soup = BeautifulSoup(resp.text, 'html.parser')
            opinions = parse_table_rows(soup)
            opinions = [o for o in opinions if o['status'] == 'Precedential' and o['document_type'] == 'OPINION']
            all_opinions.extend(opinions)
            print(f"  Found {len(opinions)} opinions from initial page (limited)")
            break
        
        opinions, total_records = parse_ajax_response(result)
        
        if total is None:
            total = total_records
            print(f"Total precedential opinions: {total}")
        
        if not opinions:
            print("  No more opinions found")
            break
        
        all_opinions.extend(opinions)
        print(f"  Page {page + 1}: {len(opinions)} opinions (total so far: {len(all_opinions)})")
        
        if len(all_opinions) >= total:
            break
        
        if max_pages and page + 1 >= max_pages:
            print(f"Reached max pages limit ({max_pages})")
            break
        
        page += 1
        time.sleep(0.5)
    
    return all_opinions

def save_manifest(opinions, output_dir="data"):
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

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Scrape CAFC Precedential Opinions")
    parser.add_argument("--max-pages", type=int, help="Maximum pages to scrape")
    parser.add_argument("--page-size", type=int, default=100, help="Page size for AJAX requests")
    parser.add_argument("--output", default="data", help="Output directory")
    args = parser.parse_args()
    
    opinions = scrape_all_precedential_opinions(
        max_pages=args.max_pages,
        page_size=args.page_size
    )
    
    if opinions:
        save_manifest(opinions, args.output)
        print(f"\nComplete! Scraped {len(opinions)} precedential opinions.")
    else:
        print("No opinions found.")
