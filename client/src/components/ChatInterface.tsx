import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Send, Scale, Sparkles, Loader2, CheckCircle, ExternalLink, Library, Users, FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState, useRef, useEffect } from "react";
import { useApp } from "@/context/AppContext";
import { useConversation, useSendMessage, useCreateConversation, parseSources, parseAnswerMarkdown, parseActionItems } from "@/hooks/useConversations";
import { useStatus } from "@/hooks/useOpinions";
import type { Citation, Source } from "@/lib/api";
import type { Message } from "@shared/schema";

function LoadingStages() {
  const [stage, setStage] = useState(0);
  const stages = [
    "Finding relevant precedent...",
    "Analyzing citations...",
    "Verifying quotes...",
    "Preparing response..."
  ];
  
  useEffect(() => {
    const interval = setInterval(() => {
      setStage(s => (s < stages.length - 1 ? s + 1 : s));
    }, 2500);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="space-y-1">
      {stages.map((text, i) => (
        <div 
          key={i}
          className={cn(
            "flex items-center gap-2 text-sm transition-all duration-300",
            i < stage ? "text-muted-foreground/50" : i === stage ? "text-foreground" : "text-muted-foreground/30"
          )}
        >
          {i < stage ? (
            <CheckCircle className="h-3.5 w-3.5 text-green-500" />
          ) : i === stage ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <div className="h-3.5 w-3.5" />
          )}
          <span>{text}</span>
        </div>
      ))}
    </div>
  );
}

export function ChatInterface() {
  const [inputValue, setInputValue] = useState("");
  const [searchMode, setSearchMode] = useState<"all" | "parties">("all");
  const scrollRef = useRef<HTMLDivElement>(null);
  const { currentConversationId, setCurrentConversationId, setSelectedCitations, setSourcePanelOpen, setShowOpinionLibrary } = useApp();
  const { data: status } = useStatus();
  
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
      
      await sendMessage.mutateAsync({ conversationId: convId, content: messageContent, searchMode });
    } catch (error) {
      console.error("Failed to send message:", error);
      setInputValue(messageContent);
    }
  };

  const handleSourceClick = (source: Source) => {
    const citation: Citation = {
      opinionId: source.opinionId,
      caseName: source.caseName,
      appealNo: source.appealNo,
      releaseDate: source.releaseDate,
      pageNumber: source.pageNumber,
      quote: source.quote,
      verified: true
    };
    setSelectedCitations([citation]);
    setSourcePanelOpen(true);
  };

  const getSources = (message: Message): Source[] => {
    return parseSources(message);
  };

  const getActionItems = (message: Message) => {
    return parseActionItems(message);
  };

  const handleActionClick = async (action: string) => {
    setInputValue(action);
    // Automatically send the action
    if (currentConversationId) {
      try {
        await sendMessage.mutateAsync({
          conversationId: currentConversationId,
          content: action,
          searchMode
        });
      } catch (error) {
        console.error('Failed to send action:', error);
      }
    }
  };

  const getAnswerMarkdown = (message: Message): string | null => {
    return parseAnswerMarkdown(message);
  };

  const renderMarkdownWithSources = (markdown: string, sources: Source[]) => {
    // Split by citations [1], [2], bold **text**, and italics *text*
    const parts = markdown.split(/(\[\d+\]|\*\*[^*]+\*\*|\*[^*]+\*)/g);
    return parts.map((part, idx) => {
      // Handle citation markers
      const citationMatch = part.match(/\[(\d+)\]/);
      if (citationMatch) {
        const sourceNum = citationMatch[1];
        const source = sources.find(s => s.sid === sourceNum);
        if (source) {
          return (
            <button
              key={idx}
              onClick={() => handleSourceClick(source)}
              className="inline-flex items-center px-1.5 py-0.5 mx-0.5 text-[10px] font-medium bg-primary/10 text-primary rounded hover:bg-primary/20 transition-colors"
              title={`${source.caseName}, p.${source.pageNumber}`}
              data-testid={`source-marker-${source.sid}`}
            >
              [{source.sid}]
            </button>
          );
        }
        return <span key={idx} className="text-muted-foreground">{part}</span>;
      }
      // Handle bold text (must check before italics since ** contains *)
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={idx} className="font-semibold">{part.slice(2, -2)}</strong>;
      }
      // Handle italics (for case names)
      if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
        return <em key={idx} className="italic">{part.slice(1, -1)}</em>;
      }
      return <span key={idx}>{part}</span>;
    });
  };

  const renderMarkdownText = (text: string, sources: Source[]) => {
    const lines = text.split('\n');
    return lines.map((line, lineIdx) => {
      const trimmedLine = line.trim();
      
      // Handle #### headings (h4)
      if (trimmedLine.startsWith('#### ')) {
        const heading = trimmedLine.slice(5);
        return (
          <h4 key={lineIdx} className="text-sm font-semibold text-foreground mt-2 mb-1 first:mt-0">
            {renderInlineMarkdown(heading, sources)}
          </h4>
        );
      }
      // Handle ### headings (h3)
      if (trimmedLine.startsWith('### ')) {
        const heading = trimmedLine.slice(4);
        return (
          <h3 key={lineIdx} className="text-base font-semibold text-foreground mt-3 mb-1 first:mt-0">
            {renderInlineMarkdown(heading, sources)}
          </h3>
        );
      }
      // Handle ## headings (h2)
      if (trimmedLine.startsWith('## ')) {
        const heading = trimmedLine.slice(3);
        return (
          <h2 key={lineIdx} className="text-lg font-bold text-foreground mt-4 mb-2 first:mt-0 border-b border-border/30 pb-1">
            {renderInlineMarkdown(heading, sources)}
          </h2>
        );
      }
      // Handle # headings (h1) - rarely used but handle it
      if (trimmedLine.startsWith('# ') && !trimmedLine.startsWith('## ')) {
        const heading = trimmedLine.slice(2);
        return (
          <h1 key={lineIdx} className="text-xl font-bold text-foreground mt-4 mb-2 first:mt-0">
            {renderInlineMarkdown(heading, sources)}
          </h1>
        );
      }
      // Handle **bold heading** lines (standalone bold lines as section headers)
      if (trimmedLine.startsWith('**') && trimmedLine.endsWith('**') && !trimmedLine.slice(2, -2).includes('**')) {
        const heading = trimmedLine.slice(2, -2);
        return (
          <h3 key={lineIdx} className="text-sm font-semibold text-foreground mt-3 mb-1 first:mt-0">
            {heading}
          </h3>
        );
      }
      // Handle numbered list items (1., 2., etc)
      const numberedMatch = trimmedLine.match(/^(\d+)\.\s+(.+)$/);
      if (numberedMatch) {
        return (
          <div key={lineIdx} className="flex gap-2 mb-1.5 pl-1">
            <span className="text-muted-foreground font-medium text-sm w-5 shrink-0">{numberedMatch[1]}.</span>
            <span className="flex-1">{renderMarkdownWithSources(numberedMatch[2], sources)}</span>
          </div>
        );
      }
      // Handle bullet points (- item or * item)
      const bulletMatch = trimmedLine.match(/^[-*]\s+(.+)$/);
      if (bulletMatch) {
        return (
          <div key={lineIdx} className="flex gap-2 mb-1.5 pl-1">
            <span className="text-muted-foreground">•</span>
            <span className="flex-1">{renderMarkdownWithSources(bulletMatch[1], sources)}</span>
          </div>
        );
      }
      // Handle horizontal rules
      if (trimmedLine === '---' || trimmedLine === '***') {
        return <hr key={lineIdx} className="my-3 border-border/50" />;
      }
      // Skip empty lines to reduce spacing
      if (trimmedLine === '') {
        return null;
      }
      return (
        <p key={lineIdx} className="mb-2 last:mb-0 leading-relaxed">
          {renderMarkdownWithSources(line, sources)}
        </p>
      );
    });
  };

  const renderInlineMarkdown = (text: string, sources: Source[]) => {
    // Handle **bold** text within the line
    const parts = text.split(/(\*\*[^*]+\*\*)/g);
    return parts.map((part, idx) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={idx}>{part.slice(2, -2)}</strong>;
      }
      return <span key={idx}>{part}</span>;
    });
  };

  if (!currentConversationId && messages.length === 0) {
    return (
      <div className="flex flex-col h-full bg-background">
        <div className="flex-1 flex items-center justify-center px-4 py-12">
          <div className="text-center max-w-lg">
            <div className="inline-flex items-center gap-2 px-3 py-1 mb-6 text-xs font-medium bg-primary/10 text-primary rounded-full">
              <Sparkles className="h-3 w-3" />
              AI-Powered Research
            </div>
            
            <h1 className="font-serif text-3xl font-bold mb-3 text-foreground tracking-tight">
              Federal Circuit AI
            </h1>
            <p className="text-base text-muted-foreground mb-6 leading-relaxed">
              Research judicial precedent and CAFC case law efficiently. Get citation-backed answers from precedential opinions.
            </p>
            
            {status && (
              <button
                onClick={() => setShowOpinionLibrary(true)}
                className="inline-flex items-center gap-2 px-4 py-2 mb-8 text-sm font-medium bg-card hover:bg-muted text-foreground rounded-lg border border-border shadow-sm transition-all hover:shadow-md"
                data-testid="button-opinion-status"
              >
                <Library className="h-4 w-4 text-primary" />
                <span>{status.opinions.ingested} of {status.opinions.total} opinions indexed</span>
                <ExternalLink className="h-3 w-3 text-muted-foreground" />
              </button>
            )}
            
            <div className="grid gap-3">
              {[
                { q: "What is the enablement standard for antibody claims?", tag: "Claim Drafting" },
                { q: "Explain the Fintiv factors for PTAB discretionary denial", tag: "IPR Strategy" },
                { q: "What is the Alice/Mayo test for patent eligibility?", tag: "101 Analysis" }
              ].map((item, i) => (
                <button 
                  key={i}
                  onClick={() => setInputValue(item.q)}
                  className="group w-full p-4 text-left bg-card rounded-xl border border-border hover:border-primary/50 hover:shadow-md transition-all"
                  data-testid={`button-example-${i}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <span className="text-sm text-foreground font-medium leading-relaxed">{item.q}</span>
                    <span className="shrink-0 text-[10px] font-medium px-2 py-1 rounded-full bg-primary/10 text-primary">
                      {item.tag}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="p-4 border-t border-border/30">
          <div className="max-w-2xl mx-auto space-y-2">
            <div className="flex items-center gap-2 text-xs">
              <span className="text-muted-foreground">Search:</span>
              <Button
                variant={searchMode === "all" ? "default" : "outline"}
                size="sm"
                className="h-6 text-xs px-2 gap-1"
                onClick={() => setSearchMode("all")}
                title="Search all opinion text and case names"
                data-testid="button-search-all"
              >
                <FileText className="h-3 w-3" />
                All Text
              </Button>
              <Button
                variant={searchMode === "parties" ? "default" : "outline"}
                size="sm"
                className="h-6 text-xs px-2 gap-1"
                onClick={() => setSearchMode("parties")}
                title="Search only case names (party names)"
                data-testid="button-search-parties"
              >
                <Users className="h-3 w-3" />
                Parties Only
              </Button>
            </div>
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
                placeholder={searchMode === "parties" ? "Enter a party name (e.g., Google, Apple, Samsung)..." : "Ask about CAFC precedent..."} 
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
              const sources = getSources(msg);
              const answerMarkdown = getAnswerMarkdown(msg);
              const actionItems = getActionItems(msg);
              const hasSources = sources.length > 0;
              const hasActionItems = actionItems.length > 0;
              
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
                    ) : answerMarkdown ? (
                      <div className="space-y-4 w-full">
                        <div className="text-sm leading-relaxed text-foreground">
                          {renderMarkdownText(answerMarkdown, sources)}
                        </div>
                        
                        {hasActionItems && (
                          <div className="mt-3 pt-3 border-t border-border/30">
                            <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">
                              Select a case
                            </div>
                            <div className="flex flex-wrap gap-2">
                              {actionItems.map((item) => (
                                <Button
                                  key={item.id}
                                  variant="outline"
                                  size="sm"
                                  className="h-auto py-2 px-3 text-left flex flex-col items-start gap-0.5 hover:bg-primary/10 hover:border-primary/50"
                                  onClick={() => handleActionClick(item.action)}
                                  disabled={sendMessage.isPending}
                                  data-testid={`action-item-${item.id}`}
                                >
                                  <span className="text-xs font-medium">{item.label}</span>
                                  <span className="text-[10px] text-muted-foreground">{item.appeal_no}</span>
                                </Button>
                              ))}
                            </div>
                          </div>
                        )}
                        
                        {hasSources && (
                          <div className="mt-4 pt-3 border-t border-border/30">
                            <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">
                              Sources
                            </div>
                            <div className="space-y-1.5">
                              {sources.map((source) => (
                                <div 
                                  key={source.sid}
                                  className="bg-muted/30 border border-border/50 rounded-lg p-2.5"
                                  data-testid={`source-panel-${source.sid}`}
                                >
                                  <div className="flex items-start gap-2">
                                    <div className="flex items-center justify-center h-5 w-5 rounded bg-primary/10 text-primary text-[10px] font-medium shrink-0">
                                      {source.sid}
                                    </div>
                                    <div className="min-w-0 space-y-1 flex-1">
                                      <div className="flex items-center gap-1">
                                        <span className="text-xs font-medium text-foreground truncate">
                                          {source.caseName}
                                        </span>
                                      </div>
                                      <div className="text-[11px] text-muted-foreground line-clamp-2 italic">
                                        "{source.quote}"
                                      </div>
                                      <div className="text-[10px] font-mono text-muted-foreground/60">
                                        {source.appealNo} {source.releaseDate && `• ${source.releaseDate}`} • p.{source.pageNumber}
                                      </div>
                                      <div className="flex items-center gap-2 mt-1">
                                        <button
                                          onClick={() => handleSourceClick(source)}
                                          className="text-[10px] text-primary hover:underline flex items-center gap-0.5"
                                          data-testid={`source-view-${source.sid}`}
                                        >
                                          View in app
                                        </button>
                                        {(source.pdfUrl || source.courtlistenerUrl) && (
                                          <a
                                            href={
                                              source.pdfUrl?.includes('cafc.uscourts.gov')
                                                ? source.pdfUrl
                                                : (source.courtlistenerUrl || source.pdfUrl)
                                            }
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="text-[10px] text-muted-foreground hover:text-primary flex items-center gap-0.5"
                                            data-testid={`source-cafc-${source.sid}`}
                                          >
                                            {source.pdfUrl?.includes('cafc.uscourts.gov') ? 'Open on CAFC' : 'View on CourtListener'} <ExternalLink className="h-2.5 w-2.5" />
                                          </a>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-sm leading-relaxed text-foreground">
                        <div className="whitespace-pre-wrap">{msg.content}</div>
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
              <div className="flex flex-col gap-1">
                <LoadingStages />
              </div>
            </div>
          )}
          
          <div ref={scrollRef} />
        </div>
      </ScrollArea>

      <div className="p-4 border-t border-border/30">
        <div className="max-w-2xl mx-auto space-y-2">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">Search:</span>
            <Button
              variant={searchMode === "all" ? "default" : "outline"}
              size="sm"
              className="h-6 text-xs px-2 gap-1"
              onClick={() => setSearchMode("all")}
              title="Search all opinion text and case names"
              data-testid="button-search-all"
            >
              <FileText className="h-3 w-3" />
              All Text
            </Button>
            <Button
              variant={searchMode === "parties" ? "default" : "outline"}
              size="sm"
              className="h-6 text-xs px-2 gap-1"
              onClick={() => setSearchMode("parties")}
              title="Search only case names (party names)"
              data-testid="button-search-parties"
            >
              <Users className="h-3 w-3" />
              Parties Only
            </Button>
          </div>
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
              placeholder={searchMode === "parties" ? "Enter a party name (e.g., Google, Apple, Samsung)..." : "Ask a follow-up question..."} 
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
