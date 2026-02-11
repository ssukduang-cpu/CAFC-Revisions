import { apiRequest } from "./queryClient";
import type { Opinion, Conversation, Message } from "@shared/schema";

export type ConfidenceTier = 'strong' | 'moderate' | 'weak' | 'unverified';

export type BindingMethod = 'strict' | 'fuzzy' | 'failed';

export type CitationSignal = 
  | 'case_bound'
  | 'exact_match'
  | 'partial_match'
  | 'fuzzy_case_binding'
  | 'binding_failed'
  | 'unverified'
  | 'recent'
  | 'holding_heuristic'
  | 'dicta_heuristic'
  | 'concurrence_heuristic'
  | 'dissent_heuristic'
  | 'ellipsis_in_quote'
  | 'db_fetched'
  | 'no_case_name'
  | 'fallback_source';

export type Court = 'CAFC' | 'SCOTUS';

export interface ControllingAuthority {
  case_name: string;
  court: Court;
  opinion_id: string;
  release_date: string;
  why_recommended: string;
  doctrine_tag: string;
}

export interface ApplicationBreakdown {
  holding_indicator: number;
  analysis_depth: number;
  framework_reference: number;
  frameworks_detected: string[];
  proximity_score: number;
  application_signal: number;
}

export interface ExplainData {
  relevance_score: number;
  authority_boost: number;
  authority_type: string;
  gravity_factor: number;
  recency_factor: number;
  application_signal: number;
  application_breakdown: ApplicationBreakdown;
  composite_score: number;
}

export interface Citation {
  opinionId: string;
  caseName: string;
  appealNo: string;
  releaseDate: string;
  pageNumber: number;
  quote: string;
  viewerUrl?: string;
  pdfUrl?: string;
  courtlistenerUrl?: string;
  verified?: boolean;
  tier?: ConfidenceTier;
  score?: number;
  signals?: CitationSignal[];
  bindingMethod?: BindingMethod;
  court?: Court;
  explain?: ExplainData;
  applicationReason?: string;
}

export interface Source {
  sid: string;
  opinionId: string;
  caseName: string;
  appealNo: string;
  releaseDate: string;
  pageNumber: number;
  quote: string;
  viewerUrl: string;
  pdfUrl: string;
  courtlistenerUrl: string;
  court?: Court;
  tier?: ConfidenceTier;
  score?: number;
  signals?: CitationSignal[];
  bindingMethod?: BindingMethod;
  explain?: ExplainData;
  applicationReason?: string;
}

export interface Claim {
  id: number;
  text: string;
  citations: Citation[];
}

export interface SupportAudit {
  total_claims: number;
  supported_claims: number;
  unsupported_claims: number;
  unsupported_statements?: number;
}

export interface CitationMetrics {
  total_citations: number;
  verified_citations: number;
  unverified_citations: number;
  unverified_rate_pct: number;
  total_statements: number;
  unsupported_statements: number;
}

export interface StatementSupport {
  sentence_idx: number;
  text: string;
  supported: boolean;
  mentioned_cases: string[];
  supporting_citations: string[];
}

export interface ActionItem {
  id: string;
  label: string;
  appeal_no: string;
  action: string;
}

export interface MessageWithCitations extends Message {
  parsedCitations?: Citation[];
  claims?: Claim[];
  supportAudit?: SupportAudit;
  sources?: Source[];
  answerMarkdown?: string;
  actionItems?: ActionItem[];
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
  webSearchTriggered?: boolean;
  webSearchCases?: string[];
  controllingAuthorities?: ControllingAuthority[];
  statementSupport?: StatementSupport[];
  citationMetrics?: CitationMetrics;
}

// API functions
export async function fetchStatus(): Promise<{ status: string; opinions: OpinionStats }> {
  const res = await apiRequest("GET", "/api/status");
  return res.json();
}

export async function fetchOpinions(options?: {
  status?: string;
  limit?: number;
  offset?: number;
  ingested?: boolean;
  q?: string;
  author?: string;
  includeR36?: boolean;
  year?: number;
}): Promise<{ opinions: Opinion[]; total: number; ingested: number; hasMore: boolean; offset: number; limit: number }> {
  const params = new URLSearchParams();
  if (options?.status) params.set("status", options.status);
  if (options?.limit) params.set("limit", options.limit.toString());
  if (options?.offset) params.set("offset", options.offset.toString());
  if (options?.ingested !== undefined) params.set("ingested", options.ingested.toString());
  if (options?.q) params.set("q", options.q);
  if (options?.author) params.set("author", options.author);
  if (options?.includeR36 !== undefined) params.set("include_r36", options.includeR36.toString());
  if (options?.year) params.set("year", options.year.toString());
  
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

export async function clearAllConversations(): Promise<void> {
  await apiRequest("DELETE", "/api/conversations");
}

export async function sendMessage(conversationId: string, content: string, searchMode: string = "all", attorneyMode: boolean = false): Promise<ChatResult> {
  const res = await apiRequest("POST", `/api/conversations/${conversationId}/messages`, { content, searchMode, attorneyMode });
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
    webSearchTriggered: data.webSearchTriggered ?? false,
    webSearchCases: data.webSearchCases ?? [],
    controllingAuthorities: data.controllingAuthorities ?? [],
  };
}
