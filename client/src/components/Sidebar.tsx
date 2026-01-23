import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MOCK_SESSIONS } from "@/lib/mockData";
import { MessageSquare, Plus, Search, Library, History } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState } from "react";
import { Separator } from "@/components/ui/separator";

export function Sidebar() {
  const [searchTerm, setSearchTerm] = useState("");

  const filteredSessions = MOCK_SESSIONS.filter(session => 
    session.query.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="flex flex-col h-full bg-sidebar/5">
      {/* New Chat Button Area */}
      <div className="p-4 pb-2">
        <Button 
          className="w-full justify-start gap-2 shadow-sm font-medium border border-sidebar-border/50 hover:bg-background/80 transition-all" 
          variant="outline"
        >
          <Plus className="h-4 w-4" />
          New Research
        </Button>
      </div>

      <div className="px-4 py-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <Input 
            placeholder="Filter history..." 
            className="pl-8 h-8 text-xs bg-background/50 border-sidebar-border focus:bg-background transition-colors"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
      </div>

      <ScrollArea className="flex-1 px-2">
        <div className="py-2 space-y-4">
          
          <div className="px-2">
            <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2 flex items-center gap-1.5">
              <History className="h-3 w-3" />
              Recent Research
            </h3>
            <div className="space-y-1">
              {filteredSessions.map((session) => (
                <Button
                  key={session.id}
                  variant="ghost"
                  className={cn(
                    "w-full justify-start h-auto py-2 px-2.5 text-sm font-normal text-muted-foreground hover:text-foreground hover:bg-sidebar/10 transition-all text-left block truncate",
                    session.id === "s-1" && "bg-sidebar/10 text-foreground font-medium border-l-2 border-primary rounded-l-none"
                  )}
                >
                  <div className="truncate w-full font-serif text-[13px]">{session.query}</div>
                  <div className="flex justify-between items-center mt-1 opacity-70">
                    <span className="text-[10px] font-sans">{session.date}</span>
                    <span className="text-[10px] font-sans bg-muted px-1 rounded">{session.messageCount}</span>
                  </div>
                </Button>
              ))}
            </div>
          </div>

        </div>
      </ScrollArea>

      <div className="p-3 mt-auto border-t bg-sidebar/10">
        <Button variant="ghost" size="sm" className="w-full justify-start gap-2 text-muted-foreground hover:text-foreground">
          <Library className="h-4 w-4" />
          Opinion Library
        </Button>
      </div>
    </div>
  );
}
