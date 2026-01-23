import axios from "axios";
import * as cheerio from "cheerio";
import type { InsertOpinion } from "@shared/schema";

const CAFC_BASE_URL = "https://www.cafc.uscourts.gov";
const OPINIONS_URL = `${CAFC_BASE_URL}/home/case-information/opinions-orders/`;

export interface ScrapedOpinion {
  caseName: string;
  appealNo: string;
  releaseDate: string;
  status: string;
  origin: string;
  documentType: string;
  pdfUrl: string;
  summary: string;
}

export async function scrapeCAFCOpinions(maxPages: number = 1): Promise<ScrapedOpinion[]> {
  const opinions: ScrapedOpinion[] = [];
  
  try {
    console.log(`Fetching CAFC opinions from ${OPINIONS_URL}...`);
    const response = await axios.get(OPINIONS_URL, {
      timeout: 30000,
      headers: {
        'User-Agent': 'Mozilla/5.0 (compatible; CAFC-Copilot/1.0)',
      }
    });
    
    const $ = cheerio.load(response.data);
    
    // The CAFC page uses a table structure for opinions
    // Table columns: Release Date, Appeal Number, Origin, Document Type, Case Name (with link), Status, PDF Path
    $('tr[id^="table_1_row_"]').each((_, row) => {
      const $row = $(row);
      const columns = $row.find('td');
      
      if (columns.length >= 6) {
        const releaseDate = $(columns[0]).text().trim();
        const appealNo = $(columns[1]).text().trim();
        const origin = $(columns[2]).text().trim();
        const documentType = $(columns[3]).text().trim();
        const status = $(columns[5]).text().trim();
        
        // Find the PDF link in the case name column (index 4)
        const $link = $(columns[4]).find('a');
        const caseNameRaw = $link.text().trim();
        const pdfPath = $link.attr('href');
        
        // Clean up case name (remove [OPINION] or [ORDER] suffix)
        const caseName = caseNameRaw.replace(/\s*\[(OPINION|ORDER)\]\s*$/i, '').trim();
        
        if (pdfPath && caseName && status === "Precedential" && documentType === "OPINION") {
          const pdfUrl = pdfPath.startsWith('http') 
            ? pdfPath 
            : `${CAFC_BASE_URL}${pdfPath.startsWith('/') ? pdfPath : '/' + pdfPath}`;
          
          opinions.push({
            caseName,
            appealNo,
            releaseDate,
            status,
            origin,
            documentType,
            pdfUrl,
            summary: `${status} ${documentType} from ${origin}`,
          });
        }
      }
    });
    
    console.log(`Scraped ${opinions.length} precedential opinions from CAFC`);
    
  } catch (error) {
    console.error('Error scraping CAFC opinions:', error);
    throw new Error(`Failed to scrape CAFC opinions: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
  
  return opinions;
}

export function convertToInsertOpinion(scraped: ScrapedOpinion): InsertOpinion {
  return {
    caseName: scraped.caseName,
    appealNo: scraped.appealNo,
    releaseDate: scraped.releaseDate,
    status: scraped.status,
    origin: scraped.origin,
    documentType: scraped.documentType,
    pdfUrl: scraped.pdfUrl,
    summary: scraped.summary,
    isIngested: false,
    pdfText: null,
  };
}
