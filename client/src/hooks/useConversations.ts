import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { 
  fetchConversations, 
  fetchConversation, 
  createConversation, 
  deleteConversation,
  sendMessage,
  type ConversationWithMessages,
  type MessageWithCitations,
  type Citation,
  type Claim,
  type SupportAudit,
  type Source
} from "@/lib/api";
import type { Conversation, Message } from "@shared/schema";

export function useConversations() {
  return useQuery({
    queryKey: ["conversations"],
    queryFn: fetchConversations,
    staleTime: 30000,
  });
}

export function useConversation(id: string | null) {
  return useQuery({
    queryKey: ["conversation", id],
    queryFn: () => (id ? fetchConversation(id) : null),
    enabled: !!id,
  });
}

export function useCreateConversation() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (title?: string) => createConversation(title),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function useDeleteConversation() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: deleteConversation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function useSendMessage() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ conversationId, content, searchMode = "all" }: { conversationId: string; content: string; searchMode?: string }) => {
      if (!conversationId) throw new Error("No conversation selected");
      return sendMessage(conversationId, content, searchMode);
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["conversation", variables.conversationId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function parseCitations(message: Message): Citation[] {
  if (!message.citations) return [];
  
  try {
    const rawCitations = typeof message.citations === 'string' 
      ? JSON.parse(message.citations) 
      : message.citations;
    
    return rawCitations.map((c: any) => ({
      opinionId: c.opinion_id || c.opinionId || '',
      caseName: c.case_name || c.caseName || '',
      appealNo: c.appeal_no || c.appealNo || '',
      releaseDate: c.release_date || c.releaseDate || '',
      pageNumber: c.page_number || c.pageNumber || 0,
      quote: c.quote || '',
      verified: c.verified ?? true
    }));
  } catch {
    return [];
  }
}

export function parseClaims(message: Message): Claim[] {
  if (!message.citations) return [];
  
  try {
    const data = typeof message.citations === 'string' 
      ? JSON.parse(message.citations) 
      : message.citations;
    
    if (data.claims && Array.isArray(data.claims)) {
      return data.claims.map((claim: any) => ({
        id: claim.id,
        text: claim.text,
        citations: (claim.citations || []).map((c: any) => ({
          opinionId: c.opinion_id || c.opinionId || '',
          caseName: c.case_name || c.caseName || '',
          appealNo: c.appeal_no || c.appealNo || '',
          releaseDate: c.release_date || c.releaseDate || '',
          pageNumber: c.page_number || c.pageNumber || 0,
          quote: c.quote || '',
          verified: c.verified ?? true
        }))
      }));
    }
    return [];
  } catch {
    return [];
  }
}

export function parseSupportAudit(message: Message): SupportAudit | null {
  if (!message.citations) return null;
  
  try {
    const data = typeof message.citations === 'string' 
      ? JSON.parse(message.citations) 
      : message.citations;
    
    if (data.support_audit) {
      return {
        total_claims: data.support_audit.total_claims || 0,
        supported_claims: data.support_audit.supported_claims || 0,
        unsupported_claims: data.support_audit.unsupported_claims || 0
      };
    }
    if (data.debug?.support_audit) {
      return {
        total_claims: data.debug.support_audit.total_claims || 0,
        supported_claims: data.debug.support_audit.supported_claims || 0,
        unsupported_claims: data.debug.support_audit.unsupported_claims || 0
      };
    }
    return null;
  } catch {
    return null;
  }
}

export function parseSources(message: Message): Source[] {
  if (!message.citations) return [];
  
  try {
    const data = typeof message.citations === 'string' 
      ? JSON.parse(message.citations) 
      : message.citations;
    
    if (data.sources && Array.isArray(data.sources)) {
      return data.sources.map((s: any) => ({
        sid: s.sid || '',
        opinionId: s.opinion_id || s.opinionId || '',
        caseName: s.case_name || s.caseName || '',
        appealNo: s.appeal_no || s.appealNo || '',
        releaseDate: s.release_date || s.releaseDate || '',
        pageNumber: s.page_number || s.pageNumber || 0,
        quote: s.quote || '',
        viewerUrl: s.viewer_url || s.viewerUrl || '',
        pdfUrl: s.pdf_url || s.pdfUrl || ''
      }));
    }
    return [];
  } catch {
    return [];
  }
}

export function parseAnswerMarkdown(message: Message): string | null {
  if (!message.citations) return null;
  
  try {
    const data = typeof message.citations === 'string' 
      ? JSON.parse(message.citations) 
      : message.citations;
    
    return data.answer_markdown || data.answerMarkdown || null;
  } catch {
    return null;
  }
}
