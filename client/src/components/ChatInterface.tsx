import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Send, Sparkles, Quote, Scale, User } from "lucide-react";
import { MOCK_CHAT_HISTORY, Message } from "@/lib/mockData";
import { cn } from "@/lib/utils";
import { useState } from "react";

export function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>(MOCK_CHAT_HISTORY);
  const [inputValue, setInputValue] = useState("");

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
    
    // Simulate thinking state (would be real streaming in full implementation)
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
    <div className="flex flex-col h-full relative">
      <ScrollArea className="flex-1 p-4 md:p-6 space-y-6">
        <div className="space-y-8 max-w-3xl mx-auto pb-4">
          {messages.map((msg) => (
            <div 
              key={msg.id} 
              className={cn(
                "flex gap-4 animate-in fade-in slide-in-from-bottom-2 duration-500",
                msg.role === "user" ? "flex-row-reverse" : "flex-row"
              )}
            >
              <Avatar className={cn(
                "h-8 w-8 shrink-0 border",
                msg.role === "assistant" ? "bg-primary text-primary-foreground border-primary" : "bg-muted text-muted-foreground"
              )}>
                {msg.role === "assistant" ? (
                  <Scale className="h-4 w-4" />
                ) : (
                  <User className="h-4 w-4" />
                )}
              </Avatar>
              
              <div className={cn(
                "flex flex-col gap-2 max-w-[85%]",
                msg.role === "user" ? "items-end" : "items-start"
              )}>
                <div className={cn(
                  "rounded-lg p-4 text-sm leading-relaxed shadow-sm",
                  msg.role === "user" 
                    ? "bg-primary text-primary-foreground rounded-tr-none" 
                    : "bg-card border rounded-tl-none font-serif text-foreground/90"
                )}>
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                </div>

                {msg.citations && msg.citations.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-1">
                    {msg.citations.map(cit => (
                      <Button 
                        key={cit.id}
                        variant="secondary" 
                        size="sm" 
                        className="h-6 text-[10px] bg-secondary/50 hover:bg-secondary text-secondary-foreground border border-transparent hover:border-secondary-foreground/20 transition-all font-mono"
                      >
                        <Quote className="h-3 w-3 mr-1.5 opacity-50" />
                        {cit.caseName}, p.{cit.page}
                      </Button>
                    ))}
                  </div>
                )}
                
                <span className="text-[10px] text-muted-foreground opacity-50 px-1">
                  {msg.timestamp}
                </span>
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>

      <div className="p-4 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="max-w-3xl mx-auto relative">
          <div className="relative rounded-xl border bg-card shadow-sm focus-within:ring-1 focus-within:ring-ring transition-all overflow-hidden">
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
              className="min-h-[60px] w-full resize-none border-0 bg-transparent p-4 placeholder:text-muted-foreground/50 focus-visible:ring-0 font-serif text-sm"
            />
            <div className="flex justify-between items-center p-2 bg-muted/20 border-t border-border/40">
              <div className="flex gap-1">
                <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground">
                  <Sparkles className="h-4 w-4" />
                </Button>
              </div>
              <Button 
                onClick={handleSend}
                disabled={!inputValue.trim()}
                size="sm" 
                className="h-7 px-3 text-xs gap-2 transition-all"
              >
                Send <Send className="h-3 w-3" />
              </Button>
            </div>
          </div>
          <p className="text-[10px] text-center text-muted-foreground mt-2">
            AI can make mistakes. Verify citations with provided sources.
          </p>
        </div>
      </div>
    </div>
  );
}
