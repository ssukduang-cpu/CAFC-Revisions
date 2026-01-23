import { spawn } from 'child_process';
import { createWriteStream, unlinkSync, existsSync } from 'fs';
import { get as httpsGet } from 'https';

function logMemory(label) {
  const mem = process.memoryUsage();
  console.log(`[memory] ${label}: heap=${Math.round(mem.heapUsed/1024/1024)}MB, rss=${Math.round(mem.rss/1024/1024)}MB`);
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

async function main() {
  const pdfUrl = 'https://www.cafc.uscourts.gov/opinions-orders/25-1613.OPINION.1-22-2026_2636392.pdf';
  const pdfPath = '/tmp/test-extract.pdf';
  
  logMemory('start');
  
  console.log('Downloading...');
  await downloadPdf(pdfUrl, pdfPath);
  logMemory('after-download');
  
  const numPages = await getPageCount(pdfPath);
  console.log(`Pages: ${numPages}`);
  logMemory('after-pagecount');
  
  for (let i = 1; i <= numPages; i++) {
    logMemory(`before-page-${i}`);
    const text = await extractPage(pdfPath, i);
    console.log(`Page ${i}: ${text.length} chars`);
    logMemory(`after-page-${i}`);
  }
  
  if (existsSync(pdfPath)) unlinkSync(pdfPath);
  logMemory('done');
}

main().catch(console.error);
