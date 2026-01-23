import axios from "axios";
import pdfParse from "pdf-parse";
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
    timeout: 60000, // 60 second timeout
    headers: {
      'User-Agent': 'Mozilla/5.0 (compatible; CAFC-Copilot/1.0)',
    },
  });
  
  return Buffer.from(response.data);
}

export async function extractTextFromPDF(pdfBuffer: Buffer): Promise<{ text: string; numPages: number }> {
  console.log('Extracting text from PDF...');
  
  const data = await pdfParse(pdfBuffer);
  
  return {
    text: data.text,
    numPages: data.numpages,
  };
}

export function chunkText(text: string, chunkSize: number = 1000, overlap: number = 200): Array<{
  text: string;
  pageNumber: number;
  chunkIndex: number;
}> {
  const chunks: Array<{ text: string; pageNumber: number; chunkIndex: number }> = [];
  
  // Simple chunking by character count with overlap
  // In production, you might want smarter chunking (by sentence, paragraph, etc.)
  let startIndex = 0;
  let chunkIndex = 0;
  
  while (startIndex < text.length) {
    const endIndex = Math.min(startIndex + chunkSize, text.length);
    const chunkText = text.slice(startIndex, endIndex);
    
    chunks.push({
      text: chunkText,
      pageNumber: 1, // PDF-parse doesn't provide easy page mapping, would need custom solution
      chunkIndex,
    });
    
    startIndex += chunkSize - overlap;
    chunkIndex++;
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
  chunks: Array<{ text: string; pageNumber: number; chunkIndex: number }>,
  embeddings: number[][]
): InsertChunk[] {
  return chunks.map((chunk, index) => ({
    opinionId,
    chunkText: chunk.text,
    pageNumber: chunk.pageNumber,
    chunkIndex: chunk.chunkIndex,
    embedding: embeddings[index] || null,
  }));
}
