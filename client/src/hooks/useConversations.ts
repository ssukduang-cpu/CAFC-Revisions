import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { 
  fetchConversations, 
  fetchConversation, 
  createConversation, 
  deleteConversation,
  clearAllConversations,
  sendMessage,
  type ConversationWithMessages,
  type MessageWithCitations,
  type Citation,
  type Claim,
  type SupportAudit,
  type Source,
  type ActionItem
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

export function useClearAllConversations() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: clearAllConversations,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function useSendMessage() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ conversationId, content, searchMode = "all", attorneyMode = true }: { conversationId: string; content: string; searchMode?: string; attorneyMode?: boolean }) => {
      if (!conversationId) throw new Error("No conversation selected");
      return sendMessage(conversationId, content, searchMode, attorneyMode);
    },
    onMutate: async (variables) => {
      // Cancel any outgoing refetches so they don't overwrite our optimistic update
      await queryClient.cancelQueries({ queryKey: ["conversation", variables.conversationId] });
      
      // Snapshot the previous value
      const previousConversation = queryClient.getQueryData<ConversationWithMessages>(["conversation", variables.conversationId]);
      
      // Optimistically add the user's message immediately (including first message in a new conversation)
      const optimisticMessage: Message = {
        id: `temp-${Date.now()}`,
        conversationId: variables.conversationId,
        role: "user",
        content: variables.content,
        citations: null,
        createdAt: new Date(),
      };

      const baseConversation: ConversationWithMessages = previousConversation || {
        id: variables.conversationId,
        title: variables.content.slice(0, 60),
        userId: null,
        createdAt: new Date(),
        updatedAt: new Date(),
        messages: [],
      };

      queryClient.setQueryData<ConversationWithMessages>(["conversation", variables.conversationId], {
        ...baseConversation,
        messages: [...(baseConversation.messages || []), optimisticMessage],
      });
      
      return { previousConversation };
    },
    onError: (err, variables, context) => {
      // Roll back to the previous value on error
      if (context?.previousConversation) {
        queryClient.setQueryData(["conversation", variables.conversationId], context.previousConversation);
      }
    },
    onSettled: (_, __, variables) => {
      // Refetch to get the real data from the server
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
    
    return rawCitations.map((c: any) => {
      const tier = c.tier || 'unverified';
      return {
        opinionId: c.opinion_id || c.opinionId || '',
        caseName: c.case_name || c.caseName || '',
        appealNo: c.appeal_no || c.appealNo || '',
        releaseDate: c.release_date || c.releaseDate || '',
        pageNumber: c.page_number || c.pageNumber || 0,
        quote: c.quote || '',
        verified: tier === 'strong' || tier === 'moderate',
        tier: tier,
        score: c.score ?? 0,
        signals: c.signals || [],
        bindingMethod: c.binding_method || c.bindingMethod || 'failed',
        court: c.court || 'CAFC',
        explain: c.explain,
        applicationReason: c.application_reason || c.applicationReason
      };
    });
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
        citations: (claim.citations || []).map((c: any) => {
          const tier = c.tier || 'unverified';
          return {
            opinionId: c.opinion_id || c.opinionId || '',
            caseName: c.case_name || c.caseName || '',
            appealNo: c.appeal_no || c.appealNo || '',
            releaseDate: c.release_date || c.releaseDate || '',
            pageNumber: c.page_number || c.pageNumber || 0,
            quote: c.quote || '',
            verified: tier === 'strong' || tier === 'moderate',
            tier: tier,
            score: c.score ?? 0,
            signals: c.signals || [],
            bindingMethod: c.binding_method || c.bindingMethod || 'failed'
          };
        })
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
        pdfUrl: s.pdf_url || s.pdfUrl || '',
        courtlistenerUrl: s.courtlistener_url || s.courtlistenerUrl || '',
        tier: s.tier || 'unverified',
        score: s.score ?? 0,
        signals: s.signals || [],
        bindingMethod: s.binding_method || s.bindingMethod || 'failed',
        court: s.court || 'CAFC',
        explain: s.explain,
        applicationReason: s.application_reason || s.applicationReason
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

export function parseActionItems(message: Message): ActionItem[] {
  if (!message.citations) return [];
  
  try {
    const data = typeof message.citations === 'string' 
      ? JSON.parse(message.citations) 
      : message.citations;
    
    if (data.action_items && Array.isArray(data.action_items)) {
      return data.action_items.map((item: any) => ({
        id: item.id || '',
        label: item.label || '',
        appeal_no: item.appeal_no || '',
        action: item.action || ''
      }));
    }
    return [];
  } catch {
    return [];
  }
}

export interface StatementSupport {
  sentenceIdx: number;
  text: string;
  supported: boolean;
  mentionedCases: string[];
  supportingCitations: string[];
}

export function parseStatementSupport(message: Message): StatementSupport[] {
  if (!message.citations) return [];
  
  try {
    const data = typeof message.citations === 'string' 
      ? JSON.parse(message.citations) 
      : message.citations;
    
    if (data.statement_support && Array.isArray(data.statement_support)) {
      return data.statement_support.map((item: any) => ({
        sentenceIdx: item.sentence_idx ?? item.sentenceIdx ?? 0,
        text: item.text || '',
        supported: item.supported !== false,
        mentionedCases: item.mentioned_cases || item.mentionedCases || [],
        supportingCitations: item.supporting_citations || item.supportingCitations || []
      }));
    }
    return [];
  } catch {
    return [];
  }
}
