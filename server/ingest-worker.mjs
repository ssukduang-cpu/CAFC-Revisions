import { spawn } from 'child_process';
import { createWriteStream, unlinkSync, existsSync } from 'fs';
import { get as httpsGet } from 'https';
import pg from 'pg';

const { Pool } = pg;

function logMemory(label) {
  const mem = process.memoryUsage();
  console.error(`[memory] ${label}: heap=${Math.round(mem.heapUsed/1024/1024)}MB`);
}

function downloadPdf(url, destPath) {
  return new Promise((resolve, reject) => {
    const file = createWriteStream(destPath);
    httpsGet(url, (response) => {
      if (response.statusCode === 301 || response.statusCode === 302) {
        file.close();
        return downloadPdf(response.headers.location, destPath).then(resolve).catch(reject);
      }
      response.pipe(file);
      file.on('finish', () => { file.close(); resolve(); });
    }).on('error', reject);
  });
}

function getPageCount(pdfPath) {
  return new Promise((resolve, reject) => {
    const proc = spawn('pdfinfo', [pdfPath]);
    let stdout = '';
    proc.stdout.on('data', (data) => { stdout += data.toString(); });
    proc.on('close', () => {
      const match = stdout.match(/Pages:\s*(\d+)/);
      resolve(match ? parseInt(match[1], 10) : 0);
    });
    proc.on('error', reject);
  });
}

function extractPage(pdfPath, pageNum) {
  return new Promise((resolve) => {
    const proc = spawn('pdftotext', ['-f', String(pageNum), '-l', String(pageNum), '-layout', pdfPath, '-']);
    let text = '';
    proc.stdout.on('data', (data) => { text += data.toString(); });
    proc.on('close', () => resolve(text));
  });
}

function chunkText(text, pageNumber, startIndex, chunkSize = 1500, overlap = 300) {
  const results = [];
  const cleaned = text.replace(/\s+/g, ' ').trim();
  if (cleaned.length < 50) return results;
  
  let start = 0;
  let idx = startIndex;
  
  while (start < cleaned.length) {
    let end = Math.min(start + chunkSize, cleaned.length);
    let chunk = cleaned.slice(start, end);
    
    if (end < cleaned.length) {
      const lastPeriod = chunk.lastIndexOf('. ');
      if (lastPeriod > chunkSize / 2) {
        chunk = chunk.slice(0, lastPeriod + 1);
      }
    }
    
    if (chunk.trim().length > 50) {
      results.push({ chunkText: chunk.trim(), pageNumber, chunkIndex: idx++ });
    }
    
    start += chunk.length - overlap;
    if (start <= 0) start = end;
  }
  
  return results;
}

async function main() {
  const opinionId = process.argv[2];
  if (!opinionId) {
    console.log(JSON.stringify({ success: false, error: 'Opinion ID required' }));
    process.exit(1);
  }
  
  const pool = new Pool({ connectionString: process.env.DATABASE_URL });
  const pdfPath = `/tmp/ingest_${Date.now()}.pdf`;
  
  try {
    logMemory('start');
    
    const opinionRes = await pool.query(
      'SELECT id, case_name, pdf_url, is_ingested FROM opinions WHERE id = $1',
      [opinionId]
    );
    
    if (opinionRes.rows.length === 0) {
      console.log(JSON.stringify({ success: false, error: 'Opinion not found' }));
      process.exit(1);
    }
    
    const opinion = opinionRes.rows[0];
    
    if (opinion.is_ingested) {
      console.log(JSON.stringify({ success: true, message: 'Already ingested', numPages: 0, insertedChunks: 0 }));
      process.exit(0);
    }
    
    console.error(`Downloading: ${opinion.case_name}`);
    await downloadPdf(opinion.pdf_url, pdfPath);
    logMemory('after-download');
    
    const numPages = await getPageCount(pdfPath);
    console.error(`Processing ${numPages} pages...`);
    
    let totalChunks = 0;
    let globalChunkIndex = 0;
    let page1Preview = '';
    
    for (let pageNum = 1; pageNum <= numPages; pageNum++) {
      const pageText = await extractPage(pdfPath, pageNum);
      
      if (pageNum === 1) {
        page1Preview = pageText.substring(0, 200).replace(/\s+/g, ' ').trim();
      }
      
      const chunks = chunkText(pageText, pageNum, globalChunkIndex);
      
      for (const chunk of chunks) {
        await pool.query(
          'INSERT INTO chunks (id, opinion_id, chunk_text, page_number, chunk_index) VALUES (gen_random_uuid(), $1, $2, $3, $4)',
          [opinion.id, chunk.chunkText, chunk.pageNumber, chunk.chunkIndex]
        );
        totalChunks++;
        globalChunkIndex++;
      }
      
      console.error(`Page ${pageNum}/${numPages}: ${chunks.length} chunks`);
      logMemory(`after-page-${pageNum}`);
    }
    
    await pool.query(
      'UPDATE opinions SET is_ingested = TRUE, pdf_text = $1 WHERE id = $2',
      [page1Preview, opinion.id]
    );
    
    if (existsSync(pdfPath)) unlinkSync(pdfPath);
    await pool.end();
    
    logMemory('done');
    console.log(JSON.stringify({
      success: true,
      numPages,
      insertedChunks: totalChunks,
      page1Preview,
    }));
    
  } catch (error) {
    if (existsSync(pdfPath)) unlinkSync(pdfPath);
    await pool.end();
    console.log(JSON.stringify({ success: false, error: error.message }));
    process.exit(1);
  }
}

main();
