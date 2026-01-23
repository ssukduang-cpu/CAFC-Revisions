import { exec } from "child_process";
import { promisify } from "util";
import { unlink } from "fs/promises";
import { join } from "path";
import { randomUUID } from "crypto";

const execAsync = promisify(exec);

interface PageText {
  pageNumber: number;
  text: string;
}

interface IngestResult {
  success: boolean;
  text?: string;
  numPages?: number;
  chunks?: Array<{ text: string; pageNumber: number; chunkIndex: number }>;
  error?: string;
}

async function downloadPdf(pdfUrl: string, pdfPath: string): Promise<void> {
  await execAsync(`curl -sL -o "${pdfPath}" "${pdfUrl}"`, { timeout: 60000 });
}

async function getPageCount(pdfPath: string): Promise<number> {
  const { stdout } = await execAsync(`pdfinfo "${pdfPath}"`);
  const match = stdout.match(/Pages:\s*(\d+)/);
  return match ? parseInt(match[1], 10) : 1;
}

async function extractPageText(pdfPath: string, pageNum: number): Promise<string> {
  const { stdout } = await execAsync(
    `pdftotext -f ${pageNum} -l ${pageNum} -layout "${pdfPath}" -`,
    { maxBuffer: 1024 * 1024 }
  );
  return stdout;
}

function chunkPageText(
  pageText: string,
  pageNumber: number,
  startChunkIndex: number,
  chunkSize: number = 1500,
  overlap: number = 300
): Array<{ text: string; pageNumber: number; chunkIndex: number }> {
  const chunks: Array<{ text: string; pageNumber: number; chunkIndex: number }> = [];
  const cleanedText = pageText.replace(/\s+/g, ' ').trim();
  
  if (cleanedText.length < 50) {
    return chunks;
  }
  
  let startIndex = 0;
  let chunkIndex = startChunkIndex;
  
  while (startIndex < cleanedText.length) {
    const endIndex = Math.min(startIndex + chunkSize, cleanedText.length);
    let chunkText = cleanedText.slice(startIndex, endIndex);
    
    if (endIndex < cleanedText.length) {
      const lastPeriod = chunkText.lastIndexOf('. ');
      if (lastPeriod > chunkSize / 2) {
        chunkText = chunkText.slice(0, lastPeriod + 1);
      }
    }
    
    if (chunkText.trim().length > 50) {
      chunks.push({
        text: chunkText.trim(),
        pageNumber,
        chunkIndex,
      });
      chunkIndex++;
    }
    
    startIndex += chunkText.length - overlap;
    if (startIndex <= 0) startIndex = endIndex;
  }
  
  return chunks;
}

async function main() {
  const pdfUrl = process.argv[2];
  
  if (!pdfUrl) {
    const result: IngestResult = { success: false, error: 'No PDF URL provided' };
    console.log(JSON.stringify(result));
    process.exit(1);
  }
  
  const tempId = randomUUID();
  const pdfPath = join('/tmp', `${tempId}.pdf`);
  
  try {
    await downloadPdf(pdfUrl, pdfPath);
    
    const numPages = await getPageCount(pdfPath);
    
    const allChunks: Array<{ text: string; pageNumber: number; chunkIndex: number }> = [];
    const pageTexts: string[] = [];
    let chunkIndex = 0;
    
    for (let pageNum = 1; pageNum <= numPages; pageNum++) {
      const pageText = await extractPageText(pdfPath, pageNum);
      pageTexts.push(pageText);
      
      const pageChunks = chunkPageText(pageText, pageNum, chunkIndex);
      allChunks.push(...pageChunks);
      chunkIndex += pageChunks.length;
    }
    
    const result: IngestResult = {
      success: true,
      text: pageTexts.join('\n\n'),
      numPages,
      chunks: allChunks,
    };
    console.log(JSON.stringify(result));
  } catch (error) {
    const result: IngestResult = {
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error',
    };
    console.log(JSON.stringify(result));
    process.exit(1);
  } finally {
    try {
      await unlink(pdfPath);
    } catch (e) {}
  }
}

main();
