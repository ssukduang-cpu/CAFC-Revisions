#!/usr/bin/env python3
"""
Script to ingest landmark cases from HTML sources (law.resource.org)
when PDFs are not available.
"""
import os
import sys
import re
from html.parser import HTMLParser
from typing import List, Tuple

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import db_postgres as db

class HTMLTextExtractor(HTMLParser):
    """Extract text content from HTML, preserving paragraph structure."""
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.current_text = []
        self.in_body = False
        self.skip_tags = {'script', 'style', 'head', 'title', 'meta', 'link'}
        self.current_tag = None
        
    def handle_starttag(self, tag, attrs):
        self.current_tag = tag
        if tag == 'body':
            self.in_body = True
        elif tag in ('p', 'div', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            if self.current_text:
                self.text_parts.append(' '.join(self.current_text))
                self.current_text = []
    
    def handle_endtag(self, tag):
        if tag == 'body':
            self.in_body = False
        elif tag in ('p', 'div'):
            if self.current_text:
                self.text_parts.append(' '.join(self.current_text))
                self.current_text = []
    
    def handle_data(self, data):
        if self.in_body and self.current_tag not in self.skip_tags:
            text = data.strip()
            if text:
                self.current_text.append(text)
    
    def get_text(self) -> str:
        if self.current_text:
            self.text_parts.append(' '.join(self.current_text))
        return '\n\n'.join(self.text_parts)


def extract_text_from_html(html_content: str) -> str:
    """Extract clean text from HTML content."""
    parser = HTMLTextExtractor()
    parser.feed(html_content)
    return parser.get_text()


def split_into_pages(text: str, chars_per_page: int = 3000) -> List[str]:
    """Split text into logical pages for FTS indexing.
    
    For HTML sources, we don't have natural page breaks, so we split
    at paragraph boundaries close to the target size.
    """
    paragraphs = text.split('\n\n')
    pages = []
    current_page = []
    current_length = 0
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        para_len = len(para)
        
        if current_length + para_len > chars_per_page and current_page:
            pages.append('\n\n'.join(current_page))
            current_page = [para]
            current_length = para_len
        else:
            current_page.append(para)
            current_length += para_len
    
    if current_page:
        pages.append('\n\n'.join(current_page))
    
    return pages


def ingest_html_case(doc_id: str, html_path: str) -> Tuple[bool, str]:
    """Ingest an HTML case into the database.
    
    Args:
        doc_id: The existing document UUID in the database
        html_path: Path to the downloaded HTML file
        
    Returns:
        Tuple of (success, message)
    """
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        text = extract_text_from_html(html_content)
        
        if len(text) < 1000:
            return False, f"Extracted text too short ({len(text)} chars)"
        
        pages = split_into_pages(text)
        
        print(f"Extracted {len(text)} chars, split into {len(pages)} pages")
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM document_pages WHERE document_id = %s", (doc_id,))
            
            for page_num, page_text in enumerate(pages, 1):
                cursor.execute("""
                    INSERT INTO document_pages (document_id, page_number, text)
                    VALUES (%s, %s, %s)
                """, (doc_id, page_num, page_text))
            
            cursor.execute("""
                UPDATE documents 
                SET status = 'completed', ingested = true
                WHERE id = %s
            """, (doc_id,))
            
            conn.commit()
        
        return True, f"Successfully ingested {len(pages)} pages"
        
    except Exception as e:
        return False, f"Error: {str(e)}"


def main():
    """Ingest the two landmark cases."""
    
    cases = [
        {
            'doc_id': '085d1d49-9625-4cab-a0ef-39b5a8aa2b66',
            'case_name': 'Vitronics Corporation v. Conceptronic, Inc.',
            'html_path': '/tmp/vitronics_lawresource.html',
            'html_url': 'https://law.resource.org/pub/us/case/reporter/F3/090/90.F3d.1576.96-1058.html'
        },
        {
            'doc_id': '5d625f22-9c11-4fe8-8331-98b010bc3bab',
            'case_name': 'Superguide Corp. v. DirecTV Enterprises, Inc.',
            'html_path': '/tmp/superguide_lawresource.html',
            'html_url': 'https://law.resource.org/pub/us/case/reporter/F3/358/358.F3d.870.02-1594.02-1562.02-1561.html'
        }
    ]
    
    for case in cases:
        print(f"\n{'='*60}")
        print(f"Ingesting: {case['case_name']}")
        print(f"HTML source: {case['html_url']}")
        print(f"{'='*60}")
        
        if not os.path.exists(case['html_path']):
            print(f"ERROR: HTML file not found at {case['html_path']}")
            print("Please download it first using curl")
            continue
        
        success, message = ingest_html_case(case['doc_id'], case['html_path'])
        
        if success:
            print(f"SUCCESS: {message}")
        else:
            print(f"FAILED: {message}")


if __name__ == '__main__':
    main()
