import type { Express, Request, Response } from "express";
import { createServer, type Server } from "http";
import { storage } from "./storage";
import { scrapeCAFCOpinions, convertToInsertOpinion } from "./scraper";
import { processPDF, createChunkInserts } from "./pdfProcessor";
import { generateChatResponse, generateConversationTitle } from "./openai";

export async function registerRoutes(
  httpServer: Server,
  app: Express
): Promise<Server> {

  // ==================== OPINIONS API ====================

  // Sync opinions from CAFC website
  app.post("/api/opinions/sync", async (req: Request, res: Response) => {
    try {
      console.log("Starting CAFC opinion sync...");
      const scrapedOpinions = await scrapeCAFCOpinions();
      
      let added = 0;
      let skipped = 0;
      
      for (const scraped of scrapedOpinions) {
        const existing = await storage.getOpinionByPdfUrl(scraped.pdfUrl);
        if (!existing) {
          await storage.createOpinion(convertToInsertOpinion(scraped));
          added++;
        } else {
          skipped++;
        }
      }
      
      const counts = await storage.getOpinionCount();
      
      res.json({
        success: true,
        message: `Synced ${added} new opinions, ${skipped} already existed`,
        scraped: scrapedOpinions.length,
        added,
        skipped,
        total: counts.total,
        ingested: counts.ingested,
      });
    } catch (error) {
      console.error("Sync error:", error);
      res.status(500).json({ 
        success: false, 
        error: error instanceof Error ? error.message : "Failed to sync opinions" 
      });
    }
  });

  // List opinions
  app.get("/api/opinions", async (req: Request, res: Response) => {
    try {
      const { status, limit, ingested } = req.query;
      const opinions = await storage.listOpinions({
        status: status as string,
        limit: limit ? parseInt(limit as string) : undefined,
        isIngested: ingested === 'true' ? true : ingested === 'false' ? false : undefined,
      });
      
      const counts = await storage.getOpinionCount();
      
      res.json({
        opinions,
        total: counts.total,
        ingested: counts.ingested,
      });
    } catch (error) {
      console.error("List opinions error:", error);
      res.status(500).json({ error: "Failed to list opinions" });
    }
  });

  // Get single opinion
  app.get("/api/opinions/:id", async (req: Request, res: Response) => {
    try {
      const id = req.params.id as string;
      const opinion = await storage.getOpinion(id);
      if (!opinion) {
        return res.status(404).json({ error: "Opinion not found" });
      }
      res.json(opinion);
    } catch (error) {
      console.error("Get opinion error:", error);
      res.status(500).json({ error: "Failed to get opinion" });
    }
  });

  // Ingest opinion (download PDF, extract text, chunk)
  app.post("/api/opinions/:id/ingest", async (req: Request, res: Response) => {
    try {
      const id = req.params.id as string;
      const opinion = await storage.getOpinion(id);
      if (!opinion) {
        return res.status(404).json({ error: "Opinion not found" });
      }
      
      if (opinion.isIngested) {
        return res.json({ 
          success: true, 
          message: "Opinion already ingested",
          chunksCreated: 0,
        });
      }
      
      console.log(`Ingesting opinion: ${opinion.caseName}`);
      
      // Process PDF
      const processed = await processPDF(opinion.pdfUrl);
      
      // Create chunks
      const chunkInserts = createChunkInserts(opinion.id, processed.chunks);
      await storage.createChunks(chunkInserts);
      
      // Mark as ingested
      await storage.markOpinionIngested(opinion.id, processed.text);
      
      res.json({
        success: true,
        message: `Successfully ingested ${opinion.caseName}`,
        textLength: processed.text.length,
        numPages: processed.numPages,
        chunksCreated: chunkInserts.length,
      });
    } catch (error) {
      console.error("Ingest error:", error);
      res.status(500).json({ 
        success: false, 
        error: error instanceof Error ? error.message : "Failed to ingest opinion" 
      });
    }
  });

  // ==================== CONVERSATIONS API ====================

  // List conversations
  app.get("/api/conversations", async (req: Request, res: Response) => {
    try {
      const conversations = await storage.listConversations();
      res.json(conversations);
    } catch (error) {
      console.error("List conversations error:", error);
      res.status(500).json({ error: "Failed to list conversations" });
    }
  });

  // Create conversation
  app.post("/api/conversations", async (req: Request, res: Response) => {
    try {
      const { title } = req.body;
      const conversation = await storage.createConversation({
        title: title || "New Research",
      });
      res.status(201).json(conversation);
    } catch (error) {
      console.error("Create conversation error:", error);
      res.status(500).json({ error: "Failed to create conversation" });
    }
  });

  // Get conversation with messages
  app.get("/api/conversations/:id", async (req: Request, res: Response) => {
    try {
      const id = req.params.id as string;
      const conversation = await storage.getConversation(id);
      if (!conversation) {
        return res.status(404).json({ error: "Conversation not found" });
      }
      const messages = await storage.getMessagesByConversation(id);
      res.json({ ...conversation, messages });
    } catch (error) {
      console.error("Get conversation error:", error);
      res.status(500).json({ error: "Failed to get conversation" });
    }
  });

  // Delete conversation
  app.delete("/api/conversations/:id", async (req: Request, res: Response) => {
    try {
      const id = req.params.id as string;
      await storage.deleteConversation(id);
      res.status(204).send();
    } catch (error) {
      console.error("Delete conversation error:", error);
      res.status(500).json({ error: "Failed to delete conversation" });
    }
  });

  // ==================== CHAT API ====================

  // Send message and get AI response
  app.post("/api/conversations/:id/messages", async (req: Request, res: Response) => {
    try {
      const conversationId = req.params.id as string;
      const { content } = req.body;

      if (!content || typeof content !== 'string') {
        return res.status(400).json({ error: "Message content is required" });
      }

      // Verify conversation exists
      const conversation = await storage.getConversation(conversationId);
      if (!conversation) {
        return res.status(404).json({ error: "Conversation not found" });
      }

      // Save user message
      const userMessage = await storage.createMessage({
        conversationId,
        role: "user",
        content,
        citations: null,
      });

      // Search for relevant chunks
      const relevantChunks = await storage.searchChunks(content, 15);
      
      // Get conversation history
      const allMessages = await storage.getMessagesByConversation(conversationId);
      const conversationHistory = allMessages.slice(-10).map(m => ({
        role: m.role as "user" | "assistant",
        content: m.content,
      }));

      // Prepare chunks for OpenAI
      const chunksWithOpinions = relevantChunks.map(chunk => ({
        chunkText: chunk.chunkText,
        pageNumber: chunk.pageNumber,
        opinionId: chunk.opinion.id,
        caseName: chunk.opinion.caseName,
        appealNo: chunk.opinion.appealNo,
        releaseDate: chunk.opinion.releaseDate,
      }));

      // Generate response
      let response;
      if (chunksWithOpinions.length === 0) {
        response = {
          answer: "NOT FOUND IN PROVIDED OPINIONS: No opinions have been ingested yet. Please sync and ingest some CAFC opinions first using the Opinion Library.",
          citations: [],
        };
      } else {
        response = await generateChatResponse(content, chunksWithOpinions, conversationHistory);
      }

      // Save assistant message
      const assistantMessage = await storage.createMessage({
        conversationId,
        role: "assistant",
        content: response.answer,
        citations: JSON.stringify(response.citations),
      });

      // Update conversation title if this is the first message
      if (allMessages.length === 0) {
        const title = await generateConversationTitle(content);
        await storage.updateConversationTitle(conversationId, title);
      }

      res.json({
        userMessage,
        assistantMessage: {
          ...assistantMessage,
          citations: response.citations,
        },
      });
    } catch (error) {
      console.error("Chat error:", error);
      res.status(500).json({ 
        error: error instanceof Error ? error.message : "Failed to process message" 
      });
    }
  });

  // ==================== STATUS API ====================

  app.get("/api/status", async (req: Request, res: Response) => {
    try {
      const counts = await storage.getOpinionCount();
      res.json({
        status: "ok",
        opinions: counts,
      });
    } catch (error) {
      res.status(500).json({ status: "error", error: "Database connection failed" });
    }
  });

  return httpServer;
}
