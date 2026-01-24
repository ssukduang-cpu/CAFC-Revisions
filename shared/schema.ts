import { sql } from "drizzle-orm";
import { pgTable, text, varchar, timestamp, boolean, integer } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod";
import { relations } from "drizzle-orm";

// Opinions table - stores metadata for CAFC opinions
export const opinions = pgTable("opinions", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  caseName: text("case_name").notNull(),
  appealNo: text("appeal_no").notNull(),
  releaseDate: text("release_date").notNull(),
  status: text("status").notNull(), // "Precedential" or "Nonprecedential"
  origin: text("origin").notNull(), // e.g., "D. Del.", "PTAB"
  documentType: text("document_type").notNull(), // "OPINION" or "ORDER"
  pdfUrl: text("pdf_url").notNull().unique(),
  courtlistenerUrl: text("courtlistener_url"), // CourtListener opinion page URL
  summary: text("summary"),
  isIngested: boolean("is_ingested").notNull().default(false),
  pdfText: text("pdf_text"), // Full extracted text
  createdAt: timestamp("created_at").notNull().defaultNow(),
  updatedAt: timestamp("updated_at").notNull().defaultNow(),
});

// Chunks table - stores text chunks for full-text search
export const chunks = pgTable("chunks", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  opinionId: varchar("opinion_id").notNull().references(() => opinions.id, { onDelete: "cascade" }),
  chunkText: text("chunk_text").notNull(),
  pageNumber: integer("page_number"),
  chunkIndex: integer("chunk_index").notNull(),
  createdAt: timestamp("created_at").notNull().defaultNow(),
});

// Conversations table - stores chat sessions
export const conversations = pgTable("conversations", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  title: text("title").notNull(),
  createdAt: timestamp("created_at").notNull().defaultNow(),
  updatedAt: timestamp("updated_at").notNull().defaultNow(),
});

// Messages table - stores individual messages in conversations
export const messages = pgTable("messages", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  conversationId: varchar("conversation_id").notNull().references(() => conversations.id, { onDelete: "cascade" }),
  role: text("role").notNull(), // "user" or "assistant"
  content: text("content").notNull(),
  citations: text("citations"), // JSON stringified array of citation objects
  createdAt: timestamp("created_at").notNull().defaultNow(),
});

// Relations
export const opinionsRelations = relations(opinions, ({ many }) => ({
  chunks: many(chunks),
}));

export const chunksRelations = relations(chunks, ({ one }) => ({
  opinion: one(opinions, {
    fields: [chunks.opinionId],
    references: [opinions.id],
  }),
}));

export const conversationsRelations = relations(conversations, ({ many }) => ({
  messages: many(messages),
}));

export const messagesRelations = relations(messages, ({ one }) => ({
  conversation: one(conversations, {
    fields: [messages.conversationId],
    references: [conversations.id],
  }),
}));

// Insert schemas
export const insertOpinionSchema = createInsertSchema(opinions).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});

export const insertChunkSchema = createInsertSchema(chunks).omit({
  id: true,
  createdAt: true,
});

export const insertConversationSchema = createInsertSchema(conversations).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});

export const insertMessageSchema = createInsertSchema(messages).omit({
  id: true,
  createdAt: true,
});

// Types
export type Opinion = typeof opinions.$inferSelect;
export type InsertOpinion = z.infer<typeof insertOpinionSchema>;

export type Chunk = typeof chunks.$inferSelect;
export type InsertChunk = z.infer<typeof insertChunkSchema>;

export type Conversation = typeof conversations.$inferSelect;
export type InsertConversation = z.infer<typeof insertConversationSchema>;

export type Message = typeof messages.$inferSelect;
export type InsertMessage = z.infer<typeof insertMessageSchema>;
