import { exec } from "child_process";
import { promisify } from "util";
import { unlink } from "fs/promises";
import { join } from "path";
import { randomUUID } from "crypto";

const execAsync = promisify(exec);

async function smokeTest() {
  const testUrl = "https://www.cafc.uscourts.gov/opinions-orders/25-1613.OPINION.1-22-2026_2636392.pdf";
  const tempId = randomUUID();
  const pdfPath = join('/tmp', `smoke_${tempId}.pdf`);
  
  console.log("=== PDF Ingestion Smoke Test ===\n");
  
  try {
    console.log("1. Downloading PDF...");
    await execAsync(`curl -sL -o "${pdfPath}" "${testUrl}"`, { timeout: 60000 });
    console.log("   ✓ Download complete\n");
    
    console.log("2. Getting page count with pdfinfo...");
    const { stdout: pdfInfo } = await execAsync(`pdfinfo "${pdfPath}"`);
    const pagesMatch = pdfInfo.match(/Pages:\s*(\d+)/);
    const numPages = pagesMatch ? parseInt(pagesMatch[1], 10) : 0;
    console.log(`   ✓ Page count: ${numPages}\n`);
    
    console.log("3. Extracting text from page 1...");
    const { stdout: page1Text } = await execAsync(
      `pdftotext -f 1 -l 1 -layout "${pdfPath}" -`,
      { maxBuffer: 1024 * 1024 }
    );
    const first200 = page1Text.substring(0, 200).replace(/\s+/g, ' ').trim();
    console.log(`   ✓ First 200 chars of page 1:\n   "${first200}"\n`);
    
    console.log("4. Testing full worker process...");
    const { stdout: workerOutput, stderr } = await execAsync(
      `npx tsx server/ingestWorker.ts "${testUrl}"`,
      { timeout: 120000, maxBuffer: 10 * 1024 * 1024 }
    );
    
    const result = JSON.parse(workerOutput);
    if (result.success) {
      console.log(`   ✓ Worker succeeded`);
      console.log(`   - Text length: ${result.text?.length || 0} chars`);
      console.log(`   - Pages: ${result.numPages}`);
      console.log(`   - Chunks created: ${result.chunks?.length || 0}\n`);
    } else {
      console.log(`   ✗ Worker failed: ${result.error}\n`);
    }
    
    console.log("=== Smoke Test PASSED ===");
  } catch (error) {
    console.error("=== Smoke Test FAILED ===");
    console.error(error);
    process.exit(1);
  } finally {
    try {
      await unlink(pdfPath);
    } catch (e) {}
  }
}

smokeTest();
