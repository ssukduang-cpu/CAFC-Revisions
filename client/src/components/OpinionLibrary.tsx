import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Search, FileText, Download, CheckCircle, Plus } from "lucide-react";
import { MOCK_OPINIONS } from "@/lib/mockData";
import { useState } from "react";
import { cn } from "@/lib/utils";

export function OpinionLibrary() {
  const [searchTerm, setSearchTerm] = useState("");

  const filteredOpinions = MOCK_OPINIONS.filter(op => 
    op.caseName.toLowerCase().includes(searchTerm.toLowerCase()) ||
    op.appealNo.includes(searchTerm)
  );

  return (
    <div className="flex flex-col h-full bg-sidebar/30">
      <div className="p-4 border-b bg-sidebar/10 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground">Opinion Library</h2>
          <Button variant="outline" size="icon" className="h-7 w-7">
            <Plus className="h-4 w-4" />
          </Button>
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input 
            placeholder="Search cases..." 
            className="pl-9 h-9 bg-background/50 border-sidebar-border focus:bg-background transition-colors"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {filteredOpinions.map((op) => (
            <div 
              key={op.id}
              className={cn(
                "group flex flex-col gap-1 p-3 rounded-md border border-transparent hover:bg-sidebar/10 hover:border-sidebar-border/50 transition-all cursor-pointer",
                !op.isIngested && "opacity-70"
              )}
            >
              <div className="flex items-start justify-between">
                <div className="font-serif font-medium text-sm text-foreground leading-tight">
                  {op.caseName}
                </div>
                {op.isIngested ? (
                  <CheckCircle className="h-3.5 w-3.5 text-emerald-600 shrink-0 mt-0.5" />
                ) : (
                  <Button variant="ghost" size="icon" className="h-5 w-5 -mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Download className="h-3.5 w-3.5 text-muted-foreground" />
                  </Button>
                )}
              </div>
              
              <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
                <span>{op.appealNo}</span>
                <span>•</span>
                <span>{op.date}</span>
              </div>

              <p className="text-xs text-muted-foreground line-clamp-2 mt-1">
                {op.summary}
              </p>
            </div>
          ))}
        </div>
      </ScrollArea>
      
      <div className="p-3 border-t bg-sidebar/10 text-xs text-center text-muted-foreground">
        {filteredOpinions.length} opinions found
      </div>
    </div>
  );
}
