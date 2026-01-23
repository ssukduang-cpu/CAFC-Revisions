import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MOCK_SESSIONS } from "@/lib/mockData";
import { MessageSquare, Plus, Search, Library, Scale, ExternalLink, FileText, Sparkles, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState } from "react";
import { Separator } from "@/components/ui/separator";

export function Sidebar() {
  const [searchTerm, setSearchTerm] = useState("");

  const filteredSessions = MOCK_SESSIONS.filter(session => 
    session.query.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="flex flex-col h-full bg-sidebar text-sidebar-foreground border-r border-sidebar-border/0">
      {/* Brand */}
      <div className="p-5 pb-6 flex items-center gap-3">
        <div className="h-8 w-8 rounded-lg bg-sidebar-foreground/10 flex items-center justify-center shrink-0 border border-white/10">
          <Scale className="h-4 w-4 text-sidebar-foreground" />
        </div>
        <div className="flex flex-col">
          <span className="font-serif font-bold text-base leading-tight">CAFC Copilot</span>
          <span className="text-[10px] text-sidebar-foreground/50 uppercase tracking-widest font-medium">Precedential</span>
        </div>
      </div>

      {/* New Chat Button */}
      <div className="px-4 pb-2">
        <Button 
          className="w-full justify-start gap-2 shadow-sm bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground border-0 transition-all h-10 font-medium" 
        >
          <Plus className="h-4 w-4" />
          New Conversation
        </Button>
      </div>

      {/* Search */}
      <div className="px-4 py-3">
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-sidebar-foreground/40" />
          <Input 
            placeholder="Search conversations..." 
            className="pl-8 h-9 text-xs bg-sidebar-accent/50 border-transparent focus:bg-sidebar-accent text-sidebar-foreground placeholder:text-sidebar-foreground/30 rounded-md"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
      </div>

      {/* History */}
      <div className="px-4 py-2">
        <h3 className="text-[10px] uppercase tracking-wider text-sidebar-foreground/40 font-bold mb-3">History</h3>
      </div>
      
      <ScrollArea className="flex-1 px-3">
        <div className="space-y-0.5">
          {filteredSessions.map((session) => (
            <Button
              key={session.id}
              variant="ghost"
              className={cn(
                "w-full justify-start h-auto py-2.5 px-3 text-sm font-normal text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent/50 transition-all text-left block group rounded-lg",
                session.id === "s-1" && "bg-sidebar-accent text-sidebar-foreground"
              )}
            >
              <div className="flex items-start gap-3">
                <MessageSquare className="h-4 w-4 mt-0.5 opacity-50 shrink-0 group-hover:opacity-80" />
                <div className="min-w-0 flex-1">
                  <div className="truncate w-full text-[13px]">{session.query}</div>
                  <div className="text-[10px] opacity-40 mt-0.5">{session.date}</div>
                </div>
              </div>
            </Button>
          ))}
        </div>
      </ScrollArea>

      {/* Official Resources Section */}
      <div className="p-4 space-y-4">
        <h3 className="text-[10px] uppercase tracking-wider text-sidebar-foreground/40 font-bold px-1">Official Resources</h3>
        <div className="space-y-1">
           <Button variant="ghost" size="sm" className="w-full justify-between h-8 px-2 text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-transparent">
             <div className="flex items-center gap-2">
               <FileText className="h-3.5 w-3.5" />
               <span className="text-xs">CAFC Opinions</span>
             </div>
             <ExternalLink className="h-3 w-3 opacity-30" />
           </Button>
           <Button variant="ghost" size="sm" className="w-full justify-between h-8 px-2 text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-transparent">
             <div className="flex items-center gap-2">
               <Scale className="h-3.5 w-3.5" />
               <span className="text-xs">Court Rules</span>
             </div>
             <ExternalLink className="h-3 w-3 opacity-30" />
           </Button>
        </div>
      </div>

      {/* User Profile */}
      <div className="p-4 mt-auto border-t border-white/5">
        <Button variant="ghost" className="w-full justify-start gap-3 px-2 hover:bg-sidebar-accent/50 h-auto py-2">
           <div className="h-8 w-8 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white font-medium text-xs">
             JD
           </div>
           <div className="flex flex-col items-start text-left min-w-0">
             <span className="text-sm font-medium text-sidebar-foreground truncate w-full">Jane Doe</span>
             <span className="text-[10px] text-sidebar-foreground/50 truncate w-full">jane@lawfirm.com</span>
           </div>
        </Button>
      </div>
    </div>
  );
}
