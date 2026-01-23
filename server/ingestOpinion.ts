#!/usr/bin/env npx tsx

import { spawn } from 'child_process';
import { createWriteStream, unlinkSync, existsSync } from 'fs';
import { randomUUID } from 'crypto';
import { get } from 'https';
import { db } from './db';
import { opinions, chunks } from '@shared/schema';
import { eq } from 'drizzle-orm';

function downloadPdf(url: string, destPath: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const file = createWriteStream(destPath);
    get(url, (response) => {
      if (response.statusCode === 301 || response.statusCode === 302) {
        const redirectUrl = response.headers.location;
        if (redirectUrl) {
          file.close();
          return downloadPdf(redirectUrl, destPath).then(resolve).catch(reject);
        }
      }
      response.pipe(file);
      file.on('finish', () => {
        file.close();
        resolve();
      });
    }).on('error', (err) => {
      file.close();
      if (existsSync(destPath)) unlinkSync(destPath);
      reject(err);
    });
  });
}

function getPageCount(pdfPath: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const proc = spawn('pdfinfo', [pdfPath]);
    let stdout = '';
    proc.stdout.on('data', (data) => { stdout += data.toString(); });
    proc.on('close', (code) => {
      const match = stdout.match(/Pages:\s*(\d+)/);
      if (match) {
        resolve(parseInt(match[1], 10));
      } else {
        reject(new Error('Could not determine page count'));
      }
    });
    proc.on('error', reject);
  });
}

function extractPageText(pdfPath: string, pageNum: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const proc = spawn('pdftotext', ['-f', String(pageNum), '-l', String(pageNum), '-layout', pdfPath, '-']);
    let text = '';
    proc.stdout.on('data', (data) => { text += data.toString(); });
    proc.stderr.on('data', () => {});
    proc.on('close', () => resolve(text));
    proc.on('error', reject);
  });
}

function chunkPageText(
  pageText: string,
  pageNumber: number,
  startChunkIndex: number,
  chunkSize: number = 1500,
  overlap: number = 300
): Array<{ chunkText: string; pageNumber: number; chunkIndex: number }> {
  const results: Array<{ chunkText: string; pageNumber: number; chunkIndex: number }> = [];
  const cleanedText = pageText.replace(/\s+/g, ' ').trim();
  
  if (cleanedText.length < 50) return results;
  
  let startIndex = 0;
  let chunkIndex = startChunkIndex;
  
  while (startIndex < cleanedText.length) {
    const endIndex = Math.min(startIndex + chunkSize, cleanedText.length);
    let chunk = cleanedText.slice(startIndex, endIndex);
    
    if (endIndex < cleanedText.length) {
      const lastPeriod = chunk.lastIndexOf('. ');
      if (lastPeriod > chunkSize / 2) {
        chunk = chunk.slice(0, lastPeriod + 1);
      }
    }
    
    if (chunk.trim().length > 50) {
      results.push({
        chunkText: chunk.trim(),
        pageNumber,
        chunkIndex: chunkIndex++,
      });
    }
    
    startIndex += chunk.length - overlap;
    if (startIndex <= 0) startIndex = endIndex;
  }
  
  return results;
}

async function main() {
  const opinionId = process.argv[2];
  
  if (!opinionId) {
    console.log(JSON.stringify({ success: false, error: 'Opinion ID required' }));
    process.exit(1);
  }
  
  const tempId = randomUUID();
  const pdfPath = `/tmp/${tempId}.pdf`;
  
  try {
    const [opinion] = await db.select().from(opinions).where(eq(opinions.id, opinionId));
    
    if (!opinion) {
      console.log(JSON.stringify({ success: false, error: 'Opinion not found' }));
      process.exit(1);
    }
    
    if (opinion.isIngested) {
      console.log(JSON.stringify({ success: true, message: 'Already ingested', chunksCreated: 0 }));
      process.exit(0);
    }
    
    console.error(`Downloading PDF for: ${opinion.caseName}`);
    await downloadPdf(opinion.pdfUrl, pdfPath);
    
    console.error('Getting page count...');
    const numPages = await getPageCount(pdfPath);
    console.error(`Processing ${numPages} pages...`);
    
    let totalChunks = 0;
    let globalChunkIndex = 0;
    let textPreview = '';
    
    for (let pageNum = 1; pageNum <= numPages; pageNum++) {
      const pageText = await extractPageText(pdfPath, pageNum);
      
      if (pageNum === 1) {
        textPreview = pageText.substring(0, 10000);
      } else if (textPreview.length < 10000) {
        textPreview += '\n\n' + pageText.substring(0, 10000 - textPreview.length);
      }
      
      const pageChunks = chunkPageText(pageText, pageNum, globalChunkIndex);
      
      if (pageChunks.length > 0) {
        const chunkInserts = pageChunks.map(c => ({
          id: randomUUID(),
          opinionId: opinion.id,
          chunkText: c.chunkText,
          pageNumber: c.pageNumber,
          chunkIndex: c.chunkIndex,
        }));
        
        await db.insert(chunks).values(chunkInserts);
        totalChunks += chunkInserts.length;
        globalChunkIndex += pageChunks.length;
      }
      
      console.error(`Page ${pageNum}/${numPages} done`);
    }
    
    await db.update(opinions)
      .set({ isIngested: true, pdfText: textPreview })
      .where(eq(opinions.id, opinion.id));
    
    if (existsSync(pdfPath)) unlinkSync(pdfPath);
    
    console.log(JSON.stringify({
      success: true,
      message: `Successfully ingested ${opinion.caseName}`,
      numPages,
      chunksCreated: totalChunks,
    }));
    
    process.exit(0);
  } catch (error) {
    if (existsSync(pdfPath)) unlinkSync(pdfPath);
    console.log(JSON.stringify({
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error',
    }));
    process.exit(1);
  }
}

main();
