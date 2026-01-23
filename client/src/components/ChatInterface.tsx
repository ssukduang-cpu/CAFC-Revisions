import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Send, Sparkles, Quote, Scale, User, Paperclip } from "lucide-react";
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
    <div className="flex flex-col h-full relative bg-white dark:bg-zinc-950">
      <ScrollArea className="flex-1 p-4 md:p-0">
        <div className="max-w-3xl mx-auto py-6 space-y-6">
          {messages.map((msg) => (
            <div 
              key={msg.id} 
              className={cn(
                "flex gap-4 px-4 py-2 group",
                // msg.role === "assistant" ? "bg-muted/30 -mx-4 px-8 py-6" : "" 
              )}
            >
              <Avatar className={cn(
                "h-8 w-8 shrink-0 border mt-1",
                msg.role === "assistant" ? "bg-primary text-primary-foreground border-primary" : "bg-zinc-200 text-zinc-600 border-transparent"
              )}>
                {msg.role === "assistant" ? (
                  <Scale className="h-4 w-4" />
                ) : (
                  <User className="h-4 w-4" />
                )}
              </Avatar>
              
              <div className="flex flex-col gap-1.5 flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-foreground">
                    {msg.role === "assistant" ? "CAFC Assistant" : "You"}
                  </span>
                  <span className="text-[10px] text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity">
                    {msg.timestamp}
                  </span>
                </div>
                
                <div className="text-sm leading-7 text-foreground/90 whitespace-pre-wrap">
                  {msg.content}
                </div>

                {msg.citations && msg.citations.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-3 pt-2 border-t border-border/50">
                    {msg.citations.map(cit => (
                      <Button 
                        key={cit.id}
                        variant="outline" 
                        size="sm" 
                        className="h-7 text-xs bg-background hover:bg-muted text-primary border-primary/20 hover:border-primary/50 transition-all gap-1.5 shadow-sm"
                      >
                        <Quote className="h-3 w-3 opacity-70" />
                        <span className="font-medium truncate max-w-[200px]">{cit.caseName}</span>
                        <span className="text-muted-foreground opacity-70">p.{cit.page}</span>
                      </Button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>

      <div className="p-4 bg-background border-t">
        <div className="max-w-3xl mx-auto">
          <div className="relative rounded-xl border shadow-sm bg-card focus-within:ring-2 focus-within:ring-primary/20 transition-all">
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
              className="min-h-[50px] max-h-[200px] w-full resize-none border-0 bg-transparent p-3 pr-12 placeholder:text-muted-foreground/60 focus-visible:ring-0 text-sm"
              rows={1}
            />
            <div className="absolute right-2 bottom-2 flex gap-1">
              <Button 
                variant="ghost" 
                size="icon" 
                className="h-8 w-8 text-muted-foreground hover:text-foreground"
              >
                <Paperclip className="h-4 w-4" />
              </Button>
              <Button 
                onClick={handleSend}
                disabled={!inputValue.trim()}
                size="icon" 
                className={cn(
                  "h-8 w-8 transition-all",
                  inputValue.trim() ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                )}
              >
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <p className="text-[10px] text-center text-muted-foreground mt-2">
            AI responses generated from precedential CAFC opinions only.
          </p>
        </div>
      </div>
    </div>
  );
}
