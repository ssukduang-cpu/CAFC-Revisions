import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Send, Scale, Sparkles, Loader2, CheckCircle, ExternalLink, Library, Users, FileText, Globe } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState, useRef, useEffect } from "react";
import { useApp } from "@/context/AppContext";
import { useConversation, useSendMessage, useCreateConversation, parseSources, parseAnswerMarkdown, parseActionItems } from "@/hooks/useConversations";
import { useStatus } from "@/hooks/useOpinions";
import { SearchProgress } from "@/components/SearchProgress";
import type { Citation, Source } from "@/lib/api";
import type { Message } from "@shared/schema";

export function ChatInterface() {
  const [inputValue, setInputValue] = useState("");
  const [searchMode, setSearchMode] = useState<"all" | "parties">("all");
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [webSearchCases, setWebSearchCases] = useState<string[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { currentConversationId, setCurrentConversationId, setSelectedCitations, setSourcePanelOpen, setShowOpinionLibrary } = useApp();
  const { data: status } = useStatus();
  
  // Auto-dismiss web search cases after 10 seconds
  useEffect(() => {
    if (webSearchCases.length > 0) {
      const timer = setTimeout(() => setWebSearchCases([]), 10000);
      return () => clearTimeout(timer);
    }
  }, [webSearchCases]);
  
  const { data: conversation, isLoading } = useConversation(currentConversationId);
  const sendMessage = useSendMessage();
  const createConversation = useCreateConversation();

  const serverMessages = conversation?.messages || [];
  // Show pending message while waiting for server response (for new conversations)
  const messages = pendingMessage && !serverMessages.some(m => m.content === pendingMessage)
    ? [...serverMessages, { id: 'pending', conversationId: currentConversationId || '', role: 'user' as const, content: pendingMessage, citations: null, createdAt: new Date() }]
    : serverMessages;

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const handleSend = async () => {
    if (!inputValue.trim()) return;
    
    const messageContent = inputValue;
    setInputValue("");
    setPendingMessage(messageContent); // Show message immediately

    try {
      let convId = currentConversationId;
      
      if (!convId) {
        const newConv = await createConversation.mutateAsync(undefined);
        convId = newConv.id;
        setCurrentConversationId(convId);
      }
      
      const result = await sendMessage.mutateAsync({ conversationId: convId, content: messageContent, searchMode });
      setPendingMessage(null); // Clear pending after success
      
      // Show web search cases if any were ingested
      if (result.webSearchCases && result.webSearchCases.length > 0) {
        setWebSearchCases(result.webSearchCases);
      }
    } catch (error) {
      console.error("Failed to send message:", error);
      setInputValue(messageContent);
      setPendingMessage(null);
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
    setPendingMessage(action); // Show message immediately
    // Automatically send the action
    if (currentConversationId) {
      try {
        await sendMessage.mutateAsync({
          conversationId: currentConversationId,
          content: action,
          searchMode
        });
        setPendingMessage(null);
      } catch (error) {
        console.error('Failed to send action:', error);
        setPendingMessage(null);
      }
    }
  };

  const getAnswerMarkdown = (message: Message): string | null => {
    return parseAnswerMarkdown(message);
  };

  // Parse "Suggested Next Steps" from markdown and extract both the main content and suggestions
  const parseSuggestedNextSteps = (markdown: string): { mainContent: string; suggestions: string[] } => {
    // Look for "## Suggested Next Steps" section
    const suggestionsMatch = markdown.match(/##\s*Suggested Next Steps\s*([\s\S]*?)(?:$|(?=\n##\s))/i);
    
    if (!suggestionsMatch) {
      return { mainContent: markdown, suggestions: [] };
    }
    
    // Extract the numbered list items from suggestions
    const suggestionsBlock = suggestionsMatch[1];
    const suggestions: string[] = [];
    
    // Match numbered items (1. question, 2. question, etc.)
    const lines = suggestionsBlock.split('\n');
    for (const line of lines) {
      const match = line.match(/^\s*\d+\.\s*(.+)$/);
      if (match) {
        let question = match[1].trim();
        // Make sure it ends with a question mark
        if (!question.endsWith('?')) {
          question += '?';
        }
        // Clean up any markdown formatting
        question = question.replace(/\*\*/g, '').replace(/\*/g, '');
        if (question.length > 5) {  // Filter out very short items
          suggestions.push(question);
        }
      }
    }
    
    // Remove the suggestions section from main content
    const mainContent = markdown.replace(/##\s*Suggested Next Steps\s*[\s\S]*?(?:$|(?=\n##\s))/i, '').trim();
    
    return { mainContent, suggestions };
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
        let content = numberedMatch[2];
        // Check if content contains a header (## or ###) - render as header instead
        if (content.startsWith('#### ')) {
          return (
            <h4 key={lineIdx} className="text-sm font-semibold text-foreground mt-2 mb-1">
              {renderInlineMarkdown(content.slice(5), sources)}
            </h4>
          );
        }
        if (content.startsWith('### ')) {
          return (
            <h3 key={lineIdx} className="text-base font-semibold text-foreground mt-3 mb-1">
              {renderInlineMarkdown(content.slice(4), sources)}
            </h3>
          );
        }
        if (content.startsWith('## ')) {
          return (
            <h2 key={lineIdx} className="text-lg font-bold text-foreground mt-4 mb-2 border-b border-border/30 pb-1">
              {renderInlineMarkdown(content.slice(3), sources)}
            </h2>
          );
        }
        return (
          <div key={lineIdx} className="flex gap-2 mb-1.5 pl-1">
            <span className="text-muted-foreground font-medium text-sm w-5 shrink-0">{numberedMatch[1]}.</span>
            <span className="flex-1">{renderMarkdownWithSources(content, sources)}</span>
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
      <div className="flex flex-col h-full bg-background overflow-hidden">
        <div className="flex-1 overflow-y-auto flex items-center justify-center px-4 py-8" style={{ WebkitOverflowScrolling: 'touch' }}>
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
                <span>{status.opinions.ingested.toLocaleString()} searchable precedential opinions (2004-2024)</span>
              </button>
            )}
            
            <div className="grid gap-3">
              {[
                { 
                  q: "What did Amgen v. Sanofi hold about the enablement requirement for functional genus claims?", 
                  tag: "§112 Enablement",
                  preview: "The Federal Circuit held that Amgen's claims to antibodies defined solely by their function (binding to PCSK9) failed the enablement requirement. The court ruled that claims covering potentially millions of undisclosed antibody sequences cannot be enabled by disclosing only 26 examples. This reinforced that the scope of enablement must be commensurate with the scope of the claims."
                },
                { 
                  q: "Explain the claim construction framework from Phillips v. AWH Corp.", 
                  tag: "Claim Construction",
                  preview: "Phillips established that claim terms are given their ordinary meaning as understood by a person of ordinary skill in the art at the time of invention. The specification is the primary source for claim construction, while prosecution history provides context. Dictionaries may inform but cannot override the intrinsic record. The court emphasized that claims must be read in view of the specification, not in a vacuum."
                },
                { 
                  q: "What is the 'motivation to combine' standard for obviousness after KSR?", 
                  tag: "§103 Obviousness",
                  preview: "After KSR v. Teleflex, the Federal Circuit applies a flexible approach to motivation to combine. Courts need not find explicit teaching in the prior art to combine references—common sense, predictable results, and design incentives can supply motivation. The 'teaching, suggestion, motivation' test remains useful but is not mandatory. Courts may consider whether a skilled artisan would have seen a reason to combine known elements."
                }
              ].map((item, i) => (
                <button 
                  key={i}
                  onClick={() => setInputValue(item.q)}
                  className="group w-full p-4 text-left bg-card rounded-xl border border-border hover:border-primary/50 hover:shadow-md transition-all"
                  data-testid={`button-example-${i}`}
                >
                  <div className="flex flex-col gap-2">
                    <div className="flex items-start justify-between gap-3">
                      <span className="text-sm text-foreground font-medium leading-relaxed">{item.q}</span>
                      <span className="shrink-0 text-[10px] font-medium px-2 py-1 rounded-full bg-primary/10 text-primary">
                        {item.tag}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2 group-hover:line-clamp-none transition-all">
                      {item.preview}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="p-3 sm:p-4 border-t border-border/30 shrink-0 bg-background pb-safe">
          <div className="max-w-2xl mx-auto space-y-2">
            <div className="flex items-center gap-2 text-xs flex-wrap">
              <span className="text-muted-foreground">Search:</span>
              <Button
                variant={searchMode === "all" ? "default" : "outline"}
                size="sm"
                className="h-7 text-xs px-2 gap-1"
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
                className="h-7 text-xs px-2 gap-1"
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
                className="min-h-[52px] max-h-[120px] w-full resize-none border-0 bg-transparent py-3 pl-4 pr-12 placeholder:text-muted-foreground/60 focus-visible:ring-0 text-sm"
                rows={1}
                data-testid="input-chat-message"
              />
              <div className="absolute right-2 bottom-2">
                <Button 
                  onClick={handleSend}
                  disabled={!inputValue.trim() || sendMessage.isPending || createConversation.isPending}
                  size="icon" 
                  className={cn(
                    "h-9 w-9 rounded-lg transition-all touch-manipulation",
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
            <p className="text-[10px] text-muted-foreground/60 text-center">
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
                    ) : answerMarkdown ? (() => {
                      const { mainContent, suggestions } = parseSuggestedNextSteps(answerMarkdown);
                      return (
                      <div className="space-y-4 w-full">
                        <div className="text-sm leading-relaxed text-foreground">
                          {renderMarkdownText(mainContent, sources)}
                        </div>
                        
                        {suggestions.length > 0 && (
                          <div className="mt-4 pt-3 border-t border-border/30">
                            <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                              <Sparkles className="h-3 w-3" />
                              Suggested Next Steps
                            </div>
                            <div className="flex flex-col gap-1.5">
                              {suggestions.slice(0, 3).map((suggestion, idx) => (
                                <Button
                                  key={idx}
                                  variant="ghost"
                                  size="sm"
                                  className="h-auto py-2 px-3 text-left justify-start text-xs text-muted-foreground hover:text-foreground hover:bg-primary/5 border border-border/40 hover:border-primary/30 rounded-lg transition-colors"
                                  onClick={() => handleActionClick(suggestion)}
                                  disabled={sendMessage.isPending}
                                  data-testid={`suggested-step-${idx + 1}`}
                                >
                                  <span className="text-primary/60 mr-2">{idx + 1}.</span>
                                  {suggestion}
                                </Button>
                              ))}
                            </div>
                          </div>
                        )}
                        
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
                      );
                    })() : (
                      <div className="text-sm leading-relaxed text-foreground">
                        {renderMarkdownText(msg.content, [])}
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
            <div className="flex flex-col gap-3 justify-start">
              <SearchProgress isSearching={true} className="mb-2" />
              <div className="flex gap-3">
                <div className="h-7 w-7 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                  <Scale className="h-3.5 w-3.5 text-primary" />
                </div>
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>Preparing response...</span>
                </div>
              </div>
            </div>
          )}
          
          {webSearchCases.length > 0 && (
            <div 
              className="flex gap-3 justify-start animate-in fade-in slide-in-from-bottom-2 duration-300 p-3 rounded-lg border border-green-500/30 bg-gradient-to-r from-green-50 to-emerald-50 dark:from-green-950/30 dark:to-emerald-950/30"
              data-testid="web-search-indicator"
            >
              <div className="h-8 w-8 rounded-full bg-green-500/20 flex items-center justify-center shrink-0">
                <Globe className="h-4 w-4 text-green-600 dark:text-green-400" />
              </div>
              <div className="flex flex-col gap-1">
                <p className="text-sm text-green-700 dark:text-green-400 font-semibold flex items-center gap-2">
                  <span>Web Search Complete</span>
                  <span className="text-xs font-normal bg-green-500/20 px-1.5 py-0.5 rounded">
                    +{webSearchCases.length} case{webSearchCases.length > 1 ? 's' : ''}
                  </span>
                </p>
                <ul className="text-xs text-muted-foreground space-y-0.5">
                  {webSearchCases.slice(0, 3).map((name, i) => (
                    <li key={i} className="truncate max-w-xs flex items-center gap-1">
                      <CheckCircle className="h-3 w-3 text-green-500 shrink-0" />
                      {name}
                    </li>
                  ))}
                  {webSearchCases.length > 3 && (
                    <li className="text-muted-foreground/60">+{webSearchCases.length - 3} more</li>
                  )}
                </ul>
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
