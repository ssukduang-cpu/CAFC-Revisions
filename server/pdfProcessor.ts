import { exec } from "child_process";
import { promisify } from "util";
import { unlink, readFile } from "fs/promises";
import { join } from "path";
import { randomUUID } from "crypto";
import type { InsertChunk } from "@shared/schema";

const execAsync = promisify(exec);

export interface ProcessedPDF {
  text: string;
  numPages: number;
  chunks: Array<{
    text: string;
    pageNumber: number;
    chunkIndex: number;
  }>;
}

export async function downloadPDF(pdfUrl: string): Promise<string> {
  console.log(`Downloading PDF from ${pdfUrl}...`);
  
  // Download directly to disk using curl to avoid memory issues
  const tempId = randomUUID();
  const tempPdfPath = join('/tmp', `${tempId}.pdf`);
  
  await execAsync(`curl -sL -o "${tempPdfPath}" "${pdfUrl}"`, { timeout: 60000 });
  
  return tempPdfPath;
}

export async function extractTextFromPDF(pdfPath: string): Promise<{ text: string; numPages: number }> {
  console.log('Extracting text from PDF...');
  
  // Use pdftotext from poppler-utils (memory efficient system tool)
  const tempTxtPath = pdfPath.replace('.pdf', '.txt');
  
  try {
    // Run pdftotext to extract text
    await execAsync(`pdftotext -layout "${pdfPath}" "${tempTxtPath}"`);
    
    // Read extracted text
    const text = await readFile(tempTxtPath, 'utf-8');
    
    // Get page count using pdfinfo
    const { stdout: pdfInfo } = await execAsync(`pdfinfo "${pdfPath}"`);
    const pagesMatch = pdfInfo.match(/Pages:\s*(\d+)/);
    const numPages = pagesMatch ? parseInt(pagesMatch[1], 10) : 1;
    
    return { text, numPages };
  } finally {
    // Clean up temp files
    try {
      await unlink(pdfPath);
      await unlink(tempTxtPath);
    } catch (e) {
      // Ignore cleanup errors
    }
  }
}

export function chunkText(text: string, chunkSize: number = 1500, overlap: number = 300): Array<{
  text: string;
  pageNumber: number;
  chunkIndex: number;
}> {
  const chunks: Array<{ text: string; pageNumber: number; chunkIndex: number }> = [];
  
  // Clean up text - remove excessive whitespace
  const cleanedText = text.replace(/\s+/g, ' ').trim();
  
  let startIndex = 0;
  let chunkIndex = 0;
  
  while (startIndex < cleanedText.length) {
    const endIndex = Math.min(startIndex + chunkSize, cleanedText.length);
    let chunkText = cleanedText.slice(startIndex, endIndex);
    
    // Try to end at a sentence boundary
    if (endIndex < cleanedText.length) {
      const lastPeriod = chunkText.lastIndexOf('. ');
      if (lastPeriod > chunkSize / 2) {
        chunkText = chunkText.slice(0, lastPeriod + 1);
      }
    }
    
    if (chunkText.trim().length > 50) { // Skip very short chunks
      chunks.push({
        text: chunkText.trim(),
        pageNumber: 1, // PDF-parse doesn't provide page mapping easily
        chunkIndex,
      });
      chunkIndex++;
    }
    
    startIndex += chunkText.length - overlap;
    if (startIndex < 0) startIndex = endIndex;
  }
  
  console.log(`Created ${chunks.length} chunks from text`);
  return chunks;
}

export async function processPDF(pdfUrl: string): Promise<ProcessedPDF> {
  const pdfPath = await downloadPDF(pdfUrl);
  const { text, numPages } = await extractTextFromPDF(pdfPath);
  const chunks = chunkText(text);
  
  return {
    text,
    numPages,
    chunks,
  };
}

export function createChunkInserts(
  opinionId: string,
  chunks: Array<{ text: string; pageNumber: number; chunkIndex: number }>
): InsertChunk[] {
  return chunks.map((chunk) => ({
    opinionId,
    chunkText: chunk.text,
    pageNumber: chunk.pageNumber,
    chunkIndex: chunk.chunkIndex,
  }));
}
