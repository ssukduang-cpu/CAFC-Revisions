#!/usr/bin/env python3

import sys
import os
import json
import uuid
import subprocess
import tempfile
import urllib.request
import ssl

import psycopg2

def download_pdf(url, dest_path):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=ctx) as response:
        with open(dest_path, 'wb') as f:
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                f.write(chunk)

def get_page_count(pdf_path):
    result = subprocess.run(['pdfinfo', pdf_path], capture_output=True, text=True)
    for line in result.stdout.split('\n'):
        if line.startswith('Pages:'):
            return int(line.split(':')[1].strip())
    raise Exception('Could not determine page count')

def extract_page_text(pdf_path, page_num):
    result = subprocess.run(
        ['pdftotext', '-f', str(page_num), '-l', str(page_num), '-layout', pdf_path, '-'],
        capture_output=True,
        text=True
    )
    return result.stdout

def chunk_text(text, page_number, start_chunk_index, chunk_size=1500, overlap=300):
    chunks = []
    cleaned = ' '.join(text.split())
    
    if len(cleaned) < 50:
        return chunks
    
    start = 0
    chunk_index = start_chunk_index
    
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        chunk = cleaned[start:end]
        
        if end < len(cleaned):
            last_period = chunk.rfind('. ')
            if last_period > chunk_size // 2:
                chunk = chunk[:last_period + 1]
        
        if len(chunk.strip()) > 50:
            chunks.append({
                'chunk_text': chunk.strip(),
                'page_number': page_number,
                'chunk_index': chunk_index
            })
            chunk_index += 1
        
        start += len(chunk) - overlap
        if start <= 0:
            start = end
    
    return chunks

def main():
    if len(sys.argv) < 2:
        print(json.dumps({'success': False, 'error': 'Opinion ID required'}))
        sys.exit(1)
    
    opinion_id = sys.argv[1]
    database_url = os.environ.get('DATABASE_URL')
    
    if not database_url:
        print(json.dumps({'success': False, 'error': 'DATABASE_URL not set'}))
        sys.exit(1)
    
    conn = None
    pdf_path = None
    
    try:
        conn = psycopg2.connect(database_url)
        cur = conn.cursor()
        
        cur.execute('SELECT id, case_name, pdf_url, is_ingested FROM opinions WHERE id = %s', (opinion_id,))
        row = cur.fetchone()
        
        if not row:
            print(json.dumps({'success': False, 'error': 'Opinion not found'}))
            sys.exit(1)
        
        op_id, case_name, pdf_url, is_ingested = row
        
        if is_ingested:
            print(json.dumps({'success': True, 'message': 'Already ingested', 'chunksCreated': 0}))
            sys.exit(0)
        
        print(f'Downloading: {case_name}', file=sys.stderr)
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            pdf_path = tmp.name
        
        download_pdf(pdf_url, pdf_path)
        
        num_pages = get_page_count(pdf_path)
        print(f'Processing {num_pages} pages...', file=sys.stderr)
        
        total_chunks = 0
        global_chunk_index = 0
        text_preview = ''
        
        for page_num in range(1, num_pages + 1):
            page_text = extract_page_text(pdf_path, page_num)
            
            if page_num == 1:
                text_preview = page_text[:10000]
            elif len(text_preview) < 10000:
                text_preview += '\n\n' + page_text[:10000 - len(text_preview)]
            
            page_chunks = chunk_text(page_text, page_num, global_chunk_index)
            
            for chunk in page_chunks:
                chunk_id = str(uuid.uuid4())
                cur.execute(
                    '''INSERT INTO chunks (id, opinion_id, chunk_text, page_number, chunk_index) 
                       VALUES (%s, %s, %s, %s, %s)''',
                    (chunk_id, op_id, chunk['chunk_text'], chunk['page_number'], chunk['chunk_index'])
                )
                total_chunks += 1
                global_chunk_index += 1
            
            conn.commit()
            print(f'Page {page_num}/{num_pages} done', file=sys.stderr)
        
        cur.execute(
            'UPDATE opinions SET is_ingested = TRUE, pdf_text = %s WHERE id = %s',
            (text_preview, op_id)
        )
        conn.commit()
        
        print(json.dumps({
            'success': True,
            'message': f'Successfully ingested {case_name}',
            'numPages': num_pages,
            'chunksCreated': total_chunks
        }))
        
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
        sys.exit(1)
    finally:
        if conn:
            conn.close()
        if pdf_path and os.path.exists(pdf_path):
            os.unlink(pdf_path)

if __name__ == '__main__':
    main()
