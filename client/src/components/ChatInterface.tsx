import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Send, Quote, Scale, Sparkles, Loader2, CheckCircle, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState, useRef, useEffect } from "react";
import { useApp } from "@/context/AppContext";
import { useConversation, useSendMessage, useCreateConversation, parseCitations, parseClaims, parseSupportAudit } from "@/hooks/useConversations";
import type { Citation, Claim, SupportAudit } from "@/lib/api";
import type { Message } from "@shared/schema";

export function ChatInterface() {
  const [inputValue, setInputValue] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const { currentConversationId, setCurrentConversationId, setSelectedCitations } = useApp();
  
  const { data: conversation, isLoading } = useConversation(currentConversationId);
  const sendMessage = useSendMessage();
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
      
      await sendMessage.mutateAsync({ conversationId: convId, content: messageContent });
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

  const getClaims = (message: Message): Claim[] => {
    return parseClaims(message);
  };

  const getAudit = (message: Message): SupportAudit | null => {
    return parseSupportAudit(message);
  };

  const formatCitationText = (cit: Citation) => {
    const parts = [cit.caseName];
    if (cit.appealNo) parts.push(`Appeal No. ${cit.appealNo}`);
    if (cit.releaseDate) parts.push(cit.releaseDate);
    parts.push(`Page ${cit.pageNumber}`);
    return `(${parts.join(", ")})`;
  };

  if (!currentConversationId && messages.length === 0) {
    return (
      <div className="flex flex-col h-full bg-background">
        <div className="flex-1 flex items-center justify-center px-4">
          <div className="text-center max-w-md">
            <div className="h-14 w-14 rounded-xl bg-primary/10 flex items-center justify-center mx-auto mb-5">
              <Scale className="h-7 w-7 text-primary" />
            </div>
            <h2 className="text-xl font-serif font-semibold mb-2 text-foreground">CAFC Copilot</h2>
            <p className="text-sm text-muted-foreground mb-6">
              Ask questions about Federal Circuit patent law with citations from precedential opinions.
            </p>
            <div className="space-y-2 text-left">
              {[
                "What is the enablement standard for antibody claims?",
                "Explain the Fintiv factors for PTAB discretionary denial",
                "What is the Alice/Mayo test for patent eligibility?"
              ].map((q, i) => (
                <button 
                  key={i}
                  onClick={() => setInputValue(q)}
                  className="w-full p-3 text-sm text-left bg-muted/30 rounded-lg border border-border/50 hover:bg-muted/50 hover:border-border transition-colors"
                  data-testid={`button-example-${i}`}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="p-4 border-t border-border/30">
          <div className="max-w-2xl mx-auto">
            <div className="relative rounded-xl bg-muted/40 border border-border/50 focus-within:border-primary/50 transition-colors">
              <Textarea 
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder="Ask about CAFC precedent..." 
                className="min-h-[52px] max-h-[150px] w-full resize-none border-0 bg-transparent py-3.5 pl-4 pr-12 placeholder:text-muted-foreground/60 focus-visible:ring-0 text-sm"
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
                    inputValue.trim() ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
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
            <p className="text-[10px] text-muted-foreground/60 text-center mt-2">
              <Sparkles className="h-3 w-3 inline mr-1" />
              Not legal advice. Answers based on precedential CAFC opinions only.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-background">
      <ScrollArea className="flex-1">
        <div className="max-w-2xl mx-auto py-6 px-4 space-y-6">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (
            messages.map((msg) => {
              const claims = getClaims(msg);
              const citations = getCitations(msg);
              const audit = getAudit(msg);
              const hasClaims = claims.length > 0;
              
              return (
                <div 
                  key={msg.id} 
                  className={cn(
                    "flex gap-3",
                    msg.role === "user" ? "justify-end" : "justify-start"
                  )}
                  data-testid={`message-${msg.id}`}
                >
                  {msg.role === "assistant" && (
                    <div className="h-7 w-7 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                      <Scale className="h-3.5 w-3.5 text-primary" />
                    </div>
                  )}
                  
                  <div className={cn(
                    "flex flex-col max-w-[85%]",
                    msg.role === "user" ? "items-end" : "items-start"
                  )}>
                    {msg.role === "user" ? (
                      <div className="bg-primary text-primary-foreground py-2.5 px-4 rounded-2xl rounded-tr-md text-sm leading-relaxed">
                        <div className="whitespace-pre-wrap">{msg.content}</div>
                      </div>
                    ) : hasClaims ? (
                      <div className="space-y-4 w-full">
                        {claims.map((claim) => (
                          <div key={claim.id} className="space-y-2" data-testid={`claim-${msg.id}-${claim.id}`}>
                            <div className="text-sm leading-relaxed text-foreground">
                              <span className="font-medium text-primary">[Claim {claim.id}]</span>{" "}
                              {claim.text}
                            </div>
                            
                            {claim.citations.filter(c => c.verified !== false && c.pageNumber >= 1).length > 0 ? (
                              <div className="space-y-1.5 pl-3 border-l-2 border-primary/30">
                                {claim.citations.filter(c => c.verified !== false && c.pageNumber >= 1).map((cit, idx) => (
                                  <button 
                                    key={idx}
                                    onClick={() => handleCitationClick([cit])}
                                    className="w-full bg-muted/30 border border-border/50 rounded-lg p-2.5 hover:bg-muted/50 transition-colors text-left group"
                                    data-testid={`citation-${msg.id}-${claim.id}-${idx}`}
                                  >
                                    <div className="flex items-start gap-2">
                                      <CheckCircle className="h-3.5 w-3.5 text-green-500 shrink-0 mt-0.5" />
                                      <div className="min-w-0 space-y-0.5">
                                        <div className="text-xs font-medium text-foreground group-hover:text-primary transition-colors truncate">
                                          {cit.caseName}
                                        </div>
                                        <div className="text-[11px] text-muted-foreground line-clamp-2 italic">
                                          "{cit.quote}"
                                        </div>
                                        <div className="text-[10px] font-mono text-muted-foreground/60">
                                          {cit.appealNo} {cit.releaseDate && `• ${cit.releaseDate}`} • p.{cit.pageNumber}
                                        </div>
                                      </div>
                                    </div>
                                  </button>
                                ))}
                              </div>
                            ) : claim.text.toUpperCase().includes("NOT FOUND") ? (
                              <div className="pl-3 border-l-2 border-muted/50">
                                <div className="text-xs text-muted-foreground italic">
                                  Try ingesting additional relevant opinions or refining your search keywords.
                                </div>
                              </div>
                            ) : (
                              <div className="pl-3 border-l-2 border-amber-500/50">
                                <div className="text-xs text-amber-600 flex items-center gap-1">
                                  <AlertCircle className="h-3 w-3" />
                                  Unable to verify citation
                                </div>
                              </div>
                            )}
                          </div>
                        ))}
                        
                        {audit && (
                          <div className="mt-3 pt-3 border-t border-border/30 flex items-center gap-4 text-[10px] text-muted-foreground">
                            <span>{audit.total_claims} claims</span>
                            <span className="text-green-600">{audit.supported_claims} supported</span>
                            {audit.unsupported_claims > 0 && (
                              <span className="text-amber-600">{audit.unsupported_claims} unsupported</span>
                            )}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-sm leading-relaxed text-foreground">
                        <div className="whitespace-pre-wrap">{msg.content}</div>
                        
                        {citations.length > 0 && (
                          <div className="mt-3 space-y-2 w-full">
                            <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Sources</div>
                            <div className="space-y-1.5">
                              {citations.map((cit, idx) => (
                                <button 
                                  key={idx}
                                  onClick={() => handleCitationClick([cit])}
                                  className="w-full bg-muted/30 border border-border/50 rounded-lg p-2.5 hover:bg-muted/50 transition-colors text-left group"
                                  data-testid={`citation-${msg.id}-${idx}`}
                                >
                                  <div className="flex items-start gap-2">
                                    <Quote className="h-3.5 w-3.5 text-primary shrink-0 mt-0.5" />
                                    <div className="min-w-0 space-y-0.5">
                                      <div className="text-xs font-medium text-foreground group-hover:text-primary transition-colors truncate">
                                        {cit.caseName}
                                      </div>
                                      <div className="text-[11px] text-muted-foreground line-clamp-1 italic">
                                        "{cit.quote}"
                                      </div>
                                      <div className="text-[10px] font-mono text-muted-foreground/60">
                                        {cit.appealNo} {cit.releaseDate && `• ${cit.releaseDate}`} • p.{cit.pageNumber}
                                      </div>
                                    </div>
                                  </div>
                                </button>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {msg.role === "user" && (
                    <div className="h-7 w-7 rounded-full bg-muted flex items-center justify-center shrink-0 mt-0.5 text-xs font-medium text-muted-foreground">
                      U
                    </div>
                  )}
                </div>
              );
            })
          )}
          
          {sendMessage.isPending && (
            <div className="flex gap-3 justify-start">
              <div className="h-7 w-7 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                <Scale className="h-3.5 w-3.5 text-primary" />
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

      <div className="p-4 border-t border-border/30">
        <div className="max-w-2xl mx-auto">
          <div className="relative rounded-xl bg-muted/40 border border-border/50 focus-within:border-primary/50 transition-colors">
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
              className="min-h-[52px] max-h-[150px] w-full resize-none border-0 bg-transparent py-3.5 pl-4 pr-12 placeholder:text-muted-foreground/60 focus-visible:ring-0 text-sm"
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
                  inputValue.trim() ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
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
