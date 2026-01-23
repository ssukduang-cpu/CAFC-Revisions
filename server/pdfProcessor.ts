import axios from "axios";
import type { InsertChunk } from "@shared/schema";

export interface ProcessedPDF {
  text: string;
  numPages: number;
  chunks: Array<{
    text: string;
    pageNumber: number;
    chunkIndex: number;
  }>;
}

export async function downloadPDF(pdfUrl: string): Promise<Buffer> {
  console.log(`Downloading PDF from ${pdfUrl}...`);
  
  const response = await axios.get(pdfUrl, {
    responseType: 'arraybuffer',
    timeout: 60000,
    headers: {
      'User-Agent': 'Mozilla/5.0 (compatible; CAFC-Copilot/1.0)',
    },
  });
  
  return Buffer.from(response.data);
}

export async function extractTextFromPDF(pdfBuffer: Buffer): Promise<{ text: string; numPages: number }> {
  console.log('Extracting text from PDF...');
  
  // Dynamic import for pdf-parse (CommonJS module)
  const pdfParse = (await import('pdf-parse')).default;
  const data = await pdfParse(pdfBuffer);
  
  return {
    text: data.text,
    numPages: data.numpages,
  };
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
  const pdfBuffer = await downloadPDF(pdfUrl);
  const { text, numPages } = await extractTextFromPDF(pdfBuffer);
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
