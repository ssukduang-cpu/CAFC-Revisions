import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { MessageSquare, Plus, Search, Library, Scale, ExternalLink, FileText, Trash2, Moon, Sun, Monitor, Settings } from "lucide-react";
import { useTheme } from "@/context/ThemeContext";
import { cn } from "@/lib/utils";
import { useState } from "react";
import { useApp } from "@/context/AppContext";
import { useConversations, useCreateConversation, useDeleteConversation } from "@/hooks/useConversations";
import { useStatus } from "@/hooks/useOpinions";
import { NewCaseDigest } from "@/components/NewCaseDigest";

export function Sidebar() {
  const [searchTerm, setSearchTerm] = useState("");
  const { currentConversationId, setCurrentConversationId, setShowOpinionLibrary } = useApp();
  
  const { data: conversations, isLoading } = useConversations();
  const { data: status } = useStatus();
  const createConversation = useCreateConversation();
  const deleteConversation = useDeleteConversation();

  const filteredConversations = (conversations || []).filter(conv => 
    conv.title.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleNewConversation = async () => {
    try {
      const conv = await createConversation.mutateAsync(undefined);
      setCurrentConversationId(conv.id);
    } catch (error) {
      console.error("Failed to create conversation:", error);
    }
  };

  const handleDeleteConversation = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await deleteConversation.mutateAsync(id);
      if (currentConversationId === id) {
        setCurrentConversationId(null);
      }
    } catch (error) {
      console.error("Failed to delete conversation:", error);
    }
  };

  const formatDate = (date: Date | string) => {
    const d = new Date(date);
    const now = new Date();
    const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24));
    
    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };

  return (
    <div className="flex flex-col h-full bg-sidebar text-sidebar-foreground">
      <div className="p-4 pb-4 flex items-center gap-3">
        <div className="h-9 w-9 rounded-xl bg-sidebar-primary flex items-center justify-center shrink-0">
          <Scale className="h-4.5 w-4.5 text-sidebar-primary-foreground" />
        </div>
        <div className="flex flex-col min-w-0">
          <span className="font-bold text-sm leading-tight truncate">Federal Circuit AI</span>
          <span className="text-[10px] text-sidebar-foreground/50 uppercase tracking-wider font-medium">Appeals</span>
        </div>
      </div>

      <div className="px-3 pb-2">
        <Button 
          onClick={handleNewConversation}
          disabled={createConversation.isPending}
          className="w-full justify-center gap-2 bg-sidebar-primary text-sidebar-primary-foreground hover:bg-sidebar-primary/90 border-0 transition-all h-10 text-sm font-semibold rounded-xl shadow-sm"
          data-testid="button-new-conversation"
        >
          <Plus className="h-4 w-4 shrink-0" />
          <span className="truncate">New Research</span>
        </Button>
      </div>

      <div className="px-3 py-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-sidebar-foreground/40" />
          <Input 
            placeholder="Search conversations..." 
            className="pl-8 h-9 text-xs bg-sidebar-accent/50 border-transparent focus:bg-sidebar-accent text-sidebar-foreground placeholder:text-sidebar-foreground/30 rounded-md"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            data-testid="input-search-conversations"
          />
        </div>
      </div>

      <div className="px-3 py-2">
        <h3 className="text-[10px] uppercase tracking-wider text-sidebar-foreground/40 font-medium">History</h3>
      </div>
      
      <ScrollArea className="flex-1 px-3">
        <div className="space-y-0.5">
          {isLoading ? (
            <div className="text-center py-4 text-xs text-sidebar-foreground/50">Loading...</div>
          ) : filteredConversations.length === 0 ? (
            <div className="text-center py-4 text-xs text-sidebar-foreground/50">
              {searchTerm ? "No matching conversations" : "No conversations yet"}
            </div>
          ) : (
            filteredConversations.map((conv) => (
              <div
                key={conv.id}
                onClick={() => setCurrentConversationId(conv.id)}
                className={cn(
                  "w-full h-auto py-2.5 px-3 text-sm font-normal text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent/50 transition-all text-left cursor-pointer group rounded-lg",
                  currentConversationId === conv.id && "bg-sidebar-accent text-sidebar-foreground"
                )}
                data-testid={`button-conversation-${conv.id}`}
              >
                <div className="flex items-start gap-3">
                  <MessageSquare className="h-4 w-4 mt-0.5 opacity-50 shrink-0 group-hover:opacity-80" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate w-full text-[13px]">{conv.title}</div>
                    <div className="text-[10px] opacity-40 mt-0.5">{formatDate(conv.updatedAt)}</div>
                  </div>
                  <button
                    onClick={(e) => handleDeleteConversation(e, conv.id)}
                    className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-500/20 rounded transition-all"
                    data-testid={`button-delete-conversation-${conv.id}`}
                  >
                    <Trash2 className="h-3 w-3 text-red-400" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </ScrollArea>

      <NewCaseDigest 
        className="mx-3 mb-2" 
        onCaseClick={(documentId) => {
          setShowOpinionLibrary(true);
        }}
      />

      <div className="p-3 space-y-2">
        <h3 className="text-[10px] uppercase tracking-wider text-sidebar-foreground/40 font-semibold px-2">Resources</h3>
        <div className="space-y-1">
          <Button 
            variant="ghost" 
            size="sm" 
            onClick={() => setShowOpinionLibrary(true)}
            className="w-full justify-between h-9 px-3 text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent rounded-lg"
            data-testid="button-opinion-library"
          >
            <div className="flex items-center gap-2.5">
              <Library className="h-4 w-4" />
              <span className="text-xs font-medium">Opinion Library</span>
            </div>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-sidebar-accent text-sidebar-foreground/60">
              {status ? `${status.opinions.ingested}/${status.opinions.total}` : "--"}
            </span>
          </Button>
          <a 
            href="https://www.cafc.uscourts.gov/home/case-information/opinions-orders/" 
            target="_blank" 
            rel="noopener noreferrer"
          >
            <Button variant="ghost" size="sm" className="w-full justify-between h-9 px-3 text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent rounded-lg">
              <div className="flex items-center gap-2.5">
                <FileText className="h-4 w-4" />
                <span className="text-xs font-medium">CAFC Website</span>
              </div>
              <ExternalLink className="h-3.5 w-3.5 opacity-40" />
            </Button>
          </a>
          <a href="/admin">
            <Button 
              variant="ghost" 
              size="sm" 
              className="w-full justify-start h-9 px-3 text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent rounded-lg"
              data-testid="button-admin"
            >
              <div className="flex items-center gap-2.5">
                <Settings className="h-4 w-4" />
                <span className="text-xs font-medium">Admin / Ingest</span>
              </div>
            </Button>
          </a>
        </div>
      </div>

      <div className="p-4 mt-auto border-t border-sidebar-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-[10px] text-sidebar-foreground/40">
            <div className="h-1.5 w-1.5 rounded-full bg-green-500"></div>
            Precedential Only
          </div>
          <ThemeToggleButton />
        </div>
      </div>
    </div>
  );
}

function ThemeToggleButton() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1.5 px-2 text-sidebar-foreground/60 hover:text-sidebar-foreground"
          data-testid="button-theme-toggle"
        >
          {resolvedTheme === "dark" ? (
            <Moon className="h-3.5 w-3.5" />
          ) : (
            <Sun className="h-3.5 w-3.5" />
          )}
          <span className="text-xs capitalize">{theme === 'system' ? 'Auto' : theme}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-32">
        <DropdownMenuItem onClick={() => setTheme("light")} data-testid="menu-theme-light">
          <Sun className="mr-2 h-4 w-4" />
          Light
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => setTheme("dark")} data-testid="menu-theme-dark">
          <Moon className="mr-2 h-4 w-4" />
          Dark
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => setTheme("system")} data-testid="menu-theme-system">
          <Monitor className="mr-2 h-4 w-4" />
          Auto
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
