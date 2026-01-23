import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Send, Quote, Scale, User, Paperclip, Bot, Sparkles } from "lucide-react";
import { MOCK_CHAT_HISTORY, Message } from "@/lib/mockData";
import { cn } from "@/lib/utils";
import { useState, useRef, useEffect } from "react";

export function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>(MOCK_CHAT_HISTORY);
  const [inputValue, setInputValue] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const handleSend = () => {
    if (!inputValue.trim()) return;
    
    const newMessage: Message = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: inputValue,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages([...messages, newMessage]);
    setInputValue("");
    
    setTimeout(() => {
      const responseMsg: Message = {
        id: `msg-${Date.now()+1}`,
        role: "assistant",
        content: "I'm searching the provided opinions for an answer...",
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setMessages(prev => [...prev, responseMsg]);
    }, 600);
  };

  return (
    <div className="flex flex-col h-full relative bg-background">
      
      {/* Disclaimer Banner */}
      <div className="bg-sidebar-accent/30 border-b border-border/50 py-1.5 px-4 text-center">
        <p className="text-[10px] text-muted-foreground font-medium tracking-wide">
          <Sparkles className="h-3 w-3 inline mr-1.5 text-amber-500/70" />
          Not Legal Advice: This tool provides general information only based on CAFC opinions.
        </p>
      </div>

      <ScrollArea className="flex-1">
        <div className="max-w-3xl mx-auto py-8 px-4 space-y-8">
          {messages.map((msg, index) => (
            <div 
              key={msg.id} 
              className={cn(
                "flex gap-4",
                msg.role === "user" ? "justify-end" : "justify-start"
              )}
            >
              {/* Assistant Avatar */}
              {msg.role === "assistant" && (
                <div className="h-8 w-8 rounded-lg bg-transparent border border-white/10 flex items-center justify-center shrink-0 mt-1">
                  <Scale className="h-4 w-4 text-primary" />
                </div>
              )}
              
              <div className={cn(
                "flex flex-col max-w-[85%]",
                msg.role === "user" ? "items-end" : "items-start"
              )}>
                
                {/* Message Content */}
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

                {/* Citations (Assistant Only) */}
                {msg.citations && msg.citations.length > 0 && (
                  <div className="mt-4 space-y-3 w-full">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider pl-1">Sources</div>
                    <div className="grid gap-2">
                      {msg.citations.map(cit => (
                        <div 
                          key={cit.id}
                          className="bg-sidebar-accent/40 border border-white/5 rounded-lg p-3 hover:bg-sidebar-accent/60 transition-colors cursor-pointer group"
                        >
                          <div className="flex items-start gap-3">
                            <Quote className="h-4 w-4 text-primary shrink-0 mt-0.5 opacity-70" />
                            <div className="space-y-1">
                                <div className="text-xs font-medium text-foreground group-hover:text-primary transition-colors">
                                  {cit.caseName}
                                </div>
                                <div className="text-[11px] text-muted-foreground line-clamp-2 italic">
                                  "{cit.text}"
                                </div>
                                <div className="text-[10px] font-mono text-muted-foreground/60">
                                  Page {cit.page}
                                </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* User Avatar */}
              {msg.role === "user" && (
                <div className="h-8 w-8 rounded-full bg-sidebar-accent flex items-center justify-center shrink-0 mt-1 border border-white/10 text-xs font-medium text-foreground">
                  JD
                </div>
              )}
            </div>
          ))}
          <div ref={scrollRef} />
        </div>
      </ScrollArea>

      {/* Input Area */}
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
              placeholder="Ask a question about the MPEP..." 
              className="min-h-[56px] max-h-[200px] w-full resize-none border-0 bg-transparent py-4 pl-4 pr-12 placeholder:text-muted-foreground/50 focus-visible:ring-0 text-sm font-medium"
              rows={1}
            />
            <div className="absolute right-2 bottom-2">
              <Button 
                onClick={handleSend}
                disabled={!inputValue.trim()}
                size="icon" 
                className={cn(
                  "h-8 w-8 rounded-lg transition-all",
                  inputValue.trim() ? "bg-primary text-primary-foreground" : "bg-transparent text-muted-foreground hover:bg-white/5"
                )}
              >
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
