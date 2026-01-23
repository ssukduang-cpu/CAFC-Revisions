import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Send, Quote, Scale, Sparkles, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState, useRef, useEffect } from "react";
import { useApp } from "@/context/AppContext";
import { useConversation, useSendMessage, useCreateConversation, parseCitations } from "@/hooks/useConversations";
import type { Citation } from "@/lib/api";
import type { Message } from "@shared/schema";

export function ChatInterface() {
  const [inputValue, setInputValue] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const { currentConversationId, setCurrentConversationId, setSelectedCitations } = useApp();
  
  const { data: conversation, isLoading } = useConversation(currentConversationId);
  const sendMessage = useSendMessage(currentConversationId);
  const createConversation = useCreateConversation();

  const messages = conversation?.messages || [];

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const handleSend = async () => {
    if (!inputValue.trim()) return;
    
    const messageContent = inputValue;
    setInputValue("");

    try {
      let convId = currentConversationId;
      
      if (!convId) {
        const newConv = await createConversation.mutateAsync(undefined);
        convId = newConv.id;
        setCurrentConversationId(convId);
      }
      
      await sendMessage.mutateAsync(messageContent);
    } catch (error) {
      console.error("Failed to send message:", error);
      setInputValue(messageContent);
    }
  };

  const handleCitationClick = (citations: Citation[]) => {
    setSelectedCitations(citations);
  };

  const getCitations = (message: Message): Citation[] => {
    return parseCitations(message);
  };

  const formatTimestamp = (date: Date | string) => {
    return new Date(date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  if (!currentConversationId && messages.length === 0) {
    return (
      <div className="flex flex-col h-full relative bg-background">
        <div className="bg-sidebar-accent/30 border-b border-border/50 py-1.5 px-4 text-center">
          <p className="text-[10px] text-muted-foreground font-medium tracking-wide">
            <Sparkles className="h-3 w-3 inline mr-1.5 text-amber-500/70" />
            Not Legal Advice: This tool provides general information only based on CAFC opinions.
          </p>
        </div>

        <div className="flex-1 flex items-center justify-center">
          <div className="text-center max-w-lg px-8">
            <div className="h-16 w-16 rounded-2xl bg-sidebar-accent/50 flex items-center justify-center mx-auto mb-6 border border-white/10">
              <Scale className="h-8 w-8 text-primary" />
            </div>
            <h2 className="text-xl font-serif font-bold mb-3 text-foreground">CAFC Copilot</h2>
            <p className="text-sm text-muted-foreground mb-6 leading-relaxed">
              Ask questions about Federal Circuit patent law. I'll search precedential CAFC opinions and provide answers with accurate citations.
            </p>
            <div className="grid gap-2 text-left">
              <button 
                onClick={() => setInputValue("What is the current standard for enablement of antibody claims?")}
                className="p-3 text-sm text-left bg-sidebar-accent/30 rounded-lg border border-white/5 hover:bg-sidebar-accent/50 transition-colors"
                data-testid="button-example-enablement"
              >
                What is the current standard for enablement of antibody claims?
              </button>
              <button 
                onClick={() => setInputValue("Explain the Fintiv factors for PTAB discretionary denial")}
                className="p-3 text-sm text-left bg-sidebar-accent/30 rounded-lg border border-white/5 hover:bg-sidebar-accent/50 transition-colors"
                data-testid="button-example-fintiv"
              >
                Explain the Fintiv factors for PTAB discretionary denial
              </button>
              <button 
                onClick={() => setInputValue("What is the Alice/Mayo test for patent eligibility?")}
                className="p-3 text-sm text-left bg-sidebar-accent/30 rounded-lg border border-white/5 hover:bg-sidebar-accent/50 transition-colors"
                data-testid="button-example-alice"
              >
                What is the Alice/Mayo test for patent eligibility?
              </button>
            </div>
          </div>
        </div>

        <div className="p-4 bg-background">
          <div className="max-w-3xl mx-auto">
            <div className="relative rounded-2xl bg-sidebar-accent border border-white/5 focus-within:ring-1 focus-within:ring-white/20 transition-all shadow-sm">
              <Textarea 
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder="Ask a question about CAFC precedent..." 
                className="min-h-[56px] max-h-[200px] w-full resize-none border-0 bg-transparent py-4 pl-4 pr-12 placeholder:text-muted-foreground/50 focus-visible:ring-0 text-sm font-medium"
                rows={1}
                data-testid="input-chat-message"
              />
              <div className="absolute right-2 bottom-2">
                <Button 
                  onClick={handleSend}
                  disabled={!inputValue.trim() || sendMessage.isPending || createConversation.isPending}
                  size="icon" 
                  className={cn(
                    "h-8 w-8 rounded-lg transition-all",
                    inputValue.trim() ? "bg-primary text-primary-foreground" : "bg-transparent text-muted-foreground hover:bg-white/5"
                  )}
                  data-testid="button-send-message"
                >
                  {sendMessage.isPending || createConversation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full relative bg-background">
      <div className="bg-sidebar-accent/30 border-b border-border/50 py-1.5 px-4 text-center">
        <p className="text-[10px] text-muted-foreground font-medium tracking-wide">
          <Sparkles className="h-3 w-3 inline mr-1.5 text-amber-500/70" />
          Not Legal Advice: This tool provides general information only based on CAFC opinions.
        </p>
      </div>

      <ScrollArea className="flex-1">
        <div className="max-w-3xl mx-auto py-8 px-4 space-y-8">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            messages.map((msg) => {
              const citations = getCitations(msg);
              
              return (
                <div 
                  key={msg.id} 
                  className={cn(
                    "flex gap-4",
                    msg.role === "user" ? "justify-end" : "justify-start"
                  )}
                  data-testid={`message-${msg.id}`}
                >
                  {msg.role === "assistant" && (
                    <div className="h-8 w-8 rounded-lg bg-transparent border border-white/10 flex items-center justify-center shrink-0 mt-1">
                      <Scale className="h-4 w-4 text-primary" />
                    </div>
                  )}
                  
                  <div className={cn(
                    "flex flex-col max-w-[85%]",
                    msg.role === "user" ? "items-end" : "items-start"
                  )}>
                    <div className={cn(
                      "text-sm leading-7",
                      msg.role === "user" 
                        ? "bg-primary text-primary-foreground py-2.5 px-4 rounded-2xl rounded-tr-sm font-sans" 
                        : "text-foreground font-sans"
                    )}>
                      {msg.role === "assistant" && (
                        <div className="mb-4">
                          <span className="text-sm font-medium text-foreground">Answer</span>
                        </div>
                      )}
                      <div className="whitespace-pre-wrap">{msg.content}</div>
                    </div>

                    {citations.length > 0 && (
                      <div className="mt-4 space-y-3 w-full">
                        <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider pl-1">Sources</div>
                        <div className="grid gap-2">
                          {citations.map((cit, idx) => (
                            <button 
                              key={idx}
                              onClick={() => handleCitationClick([cit])}
                              className="bg-sidebar-accent/40 border border-white/5 rounded-lg p-3 hover:bg-sidebar-accent/60 transition-colors cursor-pointer group text-left w-full"
                              data-testid={`citation-${msg.id}-${idx}`}
                            >
                              <div className="flex items-start gap-3">
                                <Quote className="h-4 w-4 text-primary shrink-0 mt-0.5 opacity-70" />
                                <div className="space-y-1 min-w-0">
                                  <div className="text-xs font-medium text-foreground group-hover:text-primary transition-colors">
                                    {cit.caseName}
                                  </div>
                                  <div className="text-[11px] text-muted-foreground line-clamp-2 italic">
                                    "{cit.quote}"
                                  </div>
                                  <div className="text-[10px] font-mono text-muted-foreground/60">
                                    {cit.appealNo} • Page {cit.pageNumber}
                                  </div>
                                </div>
                              </div>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  {msg.role === "user" && (
                    <div className="h-8 w-8 rounded-full bg-sidebar-accent flex items-center justify-center shrink-0 mt-1 border border-white/10 text-xs font-medium text-foreground">
                      U
                    </div>
                  )}
                </div>
              );
            })
          )}
          
          {sendMessage.isPending && (
            <div className="flex gap-4 justify-start">
              <div className="h-8 w-8 rounded-lg bg-transparent border border-white/10 flex items-center justify-center shrink-0 mt-1">
                <Scale className="h-4 w-4 text-primary" />
              </div>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Searching opinions...
              </div>
            </div>
          )}
          
          <div ref={scrollRef} />
        </div>
      </ScrollArea>

      <div className="p-4 bg-background">
        <div className="max-w-3xl mx-auto">
          <div className="relative rounded-2xl bg-sidebar-accent border border-white/5 focus-within:ring-1 focus-within:ring-white/20 transition-all shadow-sm">
            <Textarea 
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="Ask a follow-up question..." 
              className="min-h-[56px] max-h-[200px] w-full resize-none border-0 bg-transparent py-4 pl-4 pr-12 placeholder:text-muted-foreground/50 focus-visible:ring-0 text-sm font-medium"
              rows={1}
              data-testid="input-chat-message"
            />
            <div className="absolute right-2 bottom-2">
              <Button 
                onClick={handleSend}
                disabled={!inputValue.trim() || sendMessage.isPending}
                size="icon" 
                className={cn(
                  "h-8 w-8 rounded-lg transition-all",
                  inputValue.trim() ? "bg-primary text-primary-foreground" : "bg-transparent text-muted-foreground hover:bg-white/5"
                )}
                data-testid="button-send-message"
              >
                {sendMessage.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
