import httpx
from bs4 import BeautifulSoup
from typing import List, Dict
import re

CAFC_URL = "https://www.cafc.uscourts.gov/home/case-information/opinions-orders/"

async def scrape_opinions() -> List[Dict]:
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(CAFC_URL)
        response.raise_for_status()
    
    soup = BeautifulSoup(response.text, "html.parser")
    opinions = []
    
    table = soup.find("table")
    if not table:
        raise ValueError("Could not find opinions table on CAFC page")
    
    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]
    
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        
        release_date = cells[0].get_text(strip=True)
        appeal_no = cells[1].get_text(strip=True)
        origin = cells[2].get_text(strip=True)
        document_type = cells[3].get_text(strip=True)
        
        case_cell = cells[4]
        case_name = case_cell.get_text(strip=True)
        link = case_cell.find("a")
        
        status = cells[5].get_text(strip=True) if len(cells) > 5 else ""
        
        if not link or not link.get("href"):
            continue
        
        pdf_url = link.get("href")
        if pdf_url.startswith("/"):
            pdf_url = "https://www.cafc.uscourts.gov" + pdf_url
        
        if status != "Precedential" or document_type != "OPINION":
            continue
        
        opinions.append({
            "case_name": case_name,
            "appeal_no": appeal_no,
            "release_date": release_date,
            "origin": origin,
            "document_type": document_type,
            "status": status,
            "pdf_url": pdf_url,
        })
    
    return opinions
