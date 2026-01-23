import { apiRequest } from "./queryClient";
import type { Opinion, Conversation, Message } from "@shared/schema";

export interface Citation {
  opinionId: string;
  caseName: string;
  appealNo: string;
  releaseDate: string;
  pageNumber: number;
  quote: string;
}

export interface MessageWithCitations extends Message {
  parsedCitations?: Citation[];
}

export interface ConversationWithMessages extends Conversation {
  messages: Message[];
}

export interface OpinionStats {
  total: number;
  ingested: number;
}

export interface SyncResult {
  success: boolean;
  message: string;
  scraped: number;
  added: number;
  skipped: number;
  total: number;
  ingested: number;
}

export interface IngestResult {
  success: boolean;
  message: string;
  textLength?: number;
  numPages?: number;
  chunksCreated?: number;
}

export interface ChatResult {
  userMessage: Message;
  assistantMessage: MessageWithCitations;
}

// API functions
export async function fetchStatus(): Promise<{ status: string; opinions: OpinionStats }> {
  const res = await apiRequest("GET", "/api/status");
  return res.json();
}

export async function fetchOpinions(options?: {
  status?: string;
  limit?: number;
  ingested?: boolean;
}): Promise<{ opinions: Opinion[]; total: number; ingested: number }> {
  const params = new URLSearchParams();
  if (options?.status) params.set("status", options.status);
  if (options?.limit) params.set("limit", options.limit.toString());
  if (options?.ingested !== undefined) params.set("ingested", options.ingested.toString());
  
  const url = `/api/opinions${params.toString() ? `?${params}` : ""}`;
  const res = await apiRequest("GET", url);
  return res.json();
}

export async function syncOpinions(): Promise<SyncResult> {
  const res = await apiRequest("POST", "/api/opinions/sync");
  return res.json();
}

export async function ingestOpinion(opinionId: string): Promise<IngestResult> {
  const res = await apiRequest("POST", `/api/opinions/${opinionId}/ingest`);
  return res.json();
}

export async function fetchConversations(): Promise<Conversation[]> {
  const res = await apiRequest("GET", "/api/conversations");
  return res.json();
}

export async function fetchConversation(id: string): Promise<ConversationWithMessages> {
  const res = await apiRequest("GET", `/api/conversations/${id}`);
  return res.json();
}

export async function createConversation(title?: string): Promise<Conversation> {
  const res = await apiRequest("POST", "/api/conversations", { title });
  return res.json();
}

export async function deleteConversation(id: string): Promise<void> {
  await apiRequest("DELETE", `/api/conversations/${id}`);
}

export async function sendMessage(conversationId: string, content: string): Promise<ChatResult> {
  const res = await apiRequest("POST", `/api/conversations/${conversationId}/messages`, { content });
  const data = await res.json();
  
  // Parse citations from the assistant message
  let parsedCitations: Citation[] = [];
  if (data.assistantMessage.citations) {
    if (typeof data.assistantMessage.citations === 'string') {
      try {
        parsedCitations = JSON.parse(data.assistantMessage.citations);
      } catch {
        parsedCitations = [];
      }
    } else {
      parsedCitations = data.assistantMessage.citations;
    }
  }
  
  return {
    userMessage: data.userMessage,
    assistantMessage: {
      ...data.assistantMessage,
      parsedCitations,
    },
  };
}
