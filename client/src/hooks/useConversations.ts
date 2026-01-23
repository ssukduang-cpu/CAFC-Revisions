import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { 
  fetchConversations, 
  fetchConversation, 
  createConversation, 
  deleteConversation,
  sendMessage,
  type ConversationWithMessages,
  type MessageWithCitations,
  type Citation
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

export function useSendMessage(conversationId: string | null) {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (content: string) => {
      if (!conversationId) throw new Error("No conversation selected");
      return sendMessage(conversationId, content);
    },
    onSuccess: () => {
      if (conversationId) {
        queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
        queryClient.invalidateQueries({ queryKey: ["conversations"] });
      }
    },
  });
}

export function parseCitations(message: Message): Citation[] {
  if (!message.citations) return [];
  
  try {
    return typeof message.citations === 'string' 
      ? JSON.parse(message.citations) 
      : message.citations;
  } catch {
    return [];
  }
}
