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
  isLandmark: boolean("is_landmark").notNull().default(false), // Foundation cases (Alice, Phillips, etc.)
  landmarkSignificance: text("landmark_significance"), // e.g., "§101 abstract idea test"
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

// Sync history table - tracks scheduled sync runs
export const syncHistory = pgTable("sync_history", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  syncType: text("sync_type").notNull(), // "scheduled", "manual"
  status: text("status").notNull(), // "running", "completed", "failed"
  startedAt: timestamp("started_at").notNull().defaultNow(),
  completedAt: timestamp("completed_at"),
  newOpinionsFound: integer("new_opinions_found").default(0),
  newOpinionsIngested: integer("new_opinions_ingested").default(0),
  errorMessage: text("error_message"),
  lastSyncedDate: text("last_synced_date"), // The date range synced (e.g., "2025-01-20 to 2025-01-27")
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

export const insertSyncHistorySchema = createInsertSchema(syncHistory).omit({
  id: true,
  startedAt: true,
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

export type SyncHistory = typeof syncHistory.$inferSelect;
export type InsertSyncHistory = z.infer<typeof insertSyncHistorySchema>;
