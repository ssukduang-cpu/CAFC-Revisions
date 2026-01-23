import { 
  opinions, 
  chunks, 
  conversations, 
  messages,
  type Opinion, 
  type InsertOpinion,
  type Chunk,
  type InsertChunk,
  type Conversation,
  type InsertConversation,
  type Message,
  type InsertMessage
} from "@shared/schema";
import { db } from "./db";
import { eq, desc, and, sql, cosineDistance } from "drizzle-orm";

export interface IStorage {
  // Opinion operations
  getOpinion(id: string): Promise<Opinion | undefined>;
  getOpinionByPdfUrl(pdfUrl: string): Promise<Opinion | undefined>;
  listOpinions(filters?: { status?: string; limit?: number }): Promise<Opinion[]>;
  createOpinion(opinion: InsertOpinion): Promise<Opinion>;
  updateOpinion(id: string, opinion: Partial<InsertOpinion>): Promise<Opinion | undefined>;
  markOpinionIngested(id: string, pdfText: string): Promise<void>;

  // Chunk operations
  createChunk(chunk: InsertChunk): Promise<Chunk>;
  createChunks(chunks: InsertChunk[]): Promise<Chunk[]>;
  getChunksByOpinion(opinionId: string): Promise<Chunk[]>;
  findSimilarChunks(embedding: number[], limit?: number): Promise<(Chunk & { opinion: Opinion, similarity: number })[]>;

  // Conversation operations
  getConversation(id: string): Promise<Conversation | undefined>;
  listConversations(limit?: number): Promise<Conversation[]>;
  createConversation(conversation: InsertConversation): Promise<Conversation>;
  updateConversationTitle(id: string, title: string): Promise<void>;

  // Message operations
  getMessage(id: string): Promise<Message | undefined>;
  getMessagesByConversation(conversationId: string): Promise<Message[]>;
  createMessage(message: InsertMessage): Promise<Message>;
}

export class DatabaseStorage implements IStorage {
  // Opinion operations
  async getOpinion(id: string): Promise<Opinion | undefined> {
    const [opinion] = await db.select().from(opinions).where(eq(opinions.id, id));
    return opinion || undefined;
  }

  async getOpinionByPdfUrl(pdfUrl: string): Promise<Opinion | undefined> {
    const [opinion] = await db.select().from(opinions).where(eq(opinions.pdfUrl, pdfUrl));
    return opinion || undefined;
  }

  async listOpinions(filters?: { status?: string; limit?: number }): Promise<Opinion[]> {
    let query = db.select().from(opinions).orderBy(desc(opinions.releaseDate));

    if (filters?.status) {
      query = query.where(eq(opinions.status, filters.status)) as any;
    }

    if (filters?.limit) {
      query = query.limit(filters.limit) as any;
    }

    return await query;
  }

  async createOpinion(opinion: InsertOpinion): Promise<Opinion> {
    const [newOpinion] = await db
      .insert(opinions)
      .values(opinion)
      .returning();
    return newOpinion;
  }

  async updateOpinion(id: string, opinion: Partial<InsertOpinion>): Promise<Opinion | undefined> {
    const [updated] = await db
      .update(opinions)
      .set({ ...opinion, updatedAt: new Date() })
      .where(eq(opinions.id, id))
      .returning();
    return updated || undefined;
  }

  async markOpinionIngested(id: string, pdfText: string): Promise<void> {
    await db
      .update(opinions)
      .set({ isIngested: true, pdfText, updatedAt: new Date() })
      .where(eq(opinions.id, id));
  }

  // Chunk operations
  async createChunk(chunk: InsertChunk): Promise<Chunk> {
    const [newChunk] = await db
      .insert(chunks)
      .values(chunk)
      .returning();
    return newChunk;
  }

  async createChunks(chunkData: InsertChunk[]): Promise<Chunk[]> {
    if (chunkData.length === 0) return [];
    return await db
      .insert(chunks)
      .values(chunkData)
      .returning();
  }

  async getChunksByOpinion(opinionId: string): Promise<Chunk[]> {
    return await db
      .select()
      .from(chunks)
      .where(eq(chunks.opinionId, opinionId))
      .orderBy(chunks.chunkIndex);
  }

  async findSimilarChunks(embedding: number[], limit: number = 10): Promise<(Chunk & { opinion: Opinion, similarity: number })[]> {
    const embeddingString = `[${embedding.join(',')}]`;
    
    const results = await db
      .select({
        chunk: chunks,
        opinion: opinions,
        similarity: sql<number>`1 - (${chunks.embedding} <=> ${embeddingString}::vector)`,
      })
      .from(chunks)
      .innerJoin(opinions, eq(chunks.opinionId, opinions.id))
      .where(eq(opinions.isIngested, true))
      .orderBy(sql`${chunks.embedding} <=> ${embeddingString}::vector`)
      .limit(limit);

    return results.map(r => ({
      ...r.chunk,
      opinion: r.opinion,
      similarity: r.similarity,
    }));
  }

  // Conversation operations
  async getConversation(id: string): Promise<Conversation | undefined> {
    const [conversation] = await db
      .select()
      .from(conversations)
      .where(eq(conversations.id, id));
    return conversation || undefined;
  }

  async listConversations(limit: number = 50): Promise<Conversation[]> {
    return await db
      .select()
      .from(conversations)
      .orderBy(desc(conversations.updatedAt))
      .limit(limit);
  }

  async createConversation(conversation: InsertConversation): Promise<Conversation> {
    const [newConversation] = await db
      .insert(conversations)
      .values(conversation)
      .returning();
    return newConversation;
  }

  async updateConversationTitle(id: string, title: string): Promise<void> {
    await db
      .update(conversations)
      .set({ title, updatedAt: new Date() })
      .where(eq(conversations.id, id));
  }

  // Message operations
  async getMessage(id: string): Promise<Message | undefined> {
    const [message] = await db
      .select()
      .from(messages)
      .where(eq(messages.id, id));
    return message || undefined;
  }

  async getMessagesByConversation(conversationId: string): Promise<Message[]> {
    return await db
      .select()
      .from(messages)
      .where(eq(messages.conversationId, conversationId))
      .orderBy(messages.createdAt);
  }

  async createMessage(message: InsertMessage): Promise<Message> {
    const [newMessage] = await db
      .insert(messages)
      .values(message)
      .returning();
    
    // Update conversation's updatedAt
    await db
      .update(conversations)
      .set({ updatedAt: new Date() })
      .where(eq(conversations.id, message.conversationId));
    
    return newMessage;
  }
}

export const storage = new DatabaseStorage();
