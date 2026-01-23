import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MOCK_SESSIONS } from "@/lib/mockData";
import { MessageSquare, Plus, Search, Library, History, Settings, LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState } from "react";
import { Separator } from "@/components/ui/separator";

export function Sidebar() {
  const [searchTerm, setSearchTerm] = useState("");

  const filteredSessions = MOCK_SESSIONS.filter(session => 
    session.query.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="flex flex-col h-full bg-sidebar text-sidebar-foreground">
      {/* App Brand Area */}
      <div className="p-4 flex items-center gap-3 border-b border-sidebar-border/30">
        <div className="h-8 w-8 rounded-lg bg-primary flex items-center justify-center shrink-0">
          <span className="font-serif font-bold text-lg text-primary-foreground">C</span>
        </div>
        <div className="flex flex-col overflow-hidden">
          <span className="font-semibold text-sm truncate">CAFC Assistant</span>
          <span className="text-[10px] text-sidebar-foreground/60 uppercase tracking-wider">Federal Circuit</span>
        </div>
      </div>

      {/* New Chat Button Area */}
      <div className="p-3">
        <Button 
          className="w-full justify-start gap-2 shadow-none bg-sidebar-accent hover:bg-sidebar-accent/80 text-sidebar-foreground border-0 transition-all h-9" 
        >
          <Plus className="h-4 w-4" />
          New Chat
        </Button>
      </div>

      <ScrollArea className="flex-1 px-3">
        <div className="space-y-6 py-2">
          
          <div>
            <h3 className="text-[10px] uppercase tracking-wider text-sidebar-foreground/40 font-semibold mb-2 px-2">
              Recent
            </h3>
            <div className="space-y-0.5">
              {filteredSessions.map((session) => (
                <Button
                  key={session.id}
                  variant="ghost"
                  className={cn(
                    "w-full justify-start h-8 px-2 text-sm font-normal text-sidebar-foreground/80 hover:text-white hover:bg-sidebar-accent/50 transition-all text-left block truncate",
                    session.id === "s-1" && "bg-sidebar-accent text-white"
                  )}
                >
                  <div className="truncate w-full">{session.query}</div>
                </Button>
              ))}
            </div>
          </div>

          <div>
            <h3 className="text-[10px] uppercase tracking-wider text-sidebar-foreground/40 font-semibold mb-2 px-2">
              Tools
            </h3>
            <Button variant="ghost" className="w-full justify-start h-8 px-2 text-sm text-sidebar-foreground/80 hover:text-white hover:bg-sidebar-accent/50">
              <Library className="h-4 w-4 mr-2" />
              Opinion Library
            </Button>
            <Button variant="ghost" className="w-full justify-start h-8 px-2 text-sm text-sidebar-foreground/80 hover:text-white hover:bg-sidebar-accent/50">
              <Search className="h-4 w-4 mr-2" />
              Search All
            </Button>
          </div>

        </div>
      </ScrollArea>

      <div className="p-3 mt-auto border-t border-sidebar-border/30 space-y-1">
        <Button variant="ghost" size="sm" className="w-full justify-start gap-2 text-sidebar-foreground/70 hover:text-white hover:bg-sidebar-accent/50">
          <Settings className="h-4 w-4" />
          Settings
        </Button>
      </div>
    </div>
  );
}
