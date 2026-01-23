import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ExternalLink, Copy, BookOpen, Quote } from "lucide-react";
import { MOCK_CHAT_HISTORY } from "@/lib/mockData";

export function SourcesPanel() {
  // In a real app, this would come from a selected message context
  const activeMessage = MOCK_CHAT_HISTORY.find(m => m.citations && m.citations.length > 0);
  const citations = activeMessage?.citations || [];

  return (
    <div className="flex flex-col h-full bg-card">
      <div className="p-4 border-b flex items-center justify-between bg-muted/10">
        <div className="flex items-center gap-2 text-primary">
          <BookOpen className="h-4 w-4" />
          <h2 className="font-semibold text-sm tracking-tight">Cited Sources</h2>
        </div>
        <Badge variant="outline" className="font-mono text-[10px]">{citations.length} References</Badge>
      </div>

      <ScrollArea className="flex-1 p-4">
        <div className="space-y-4">
          {citations.length > 0 ? citations.map((citation, index) => (
            <Card key={citation.id} className="shadow-sm border-l-4 border-l-primary/40 hover:border-l-primary transition-all group">
              <CardHeader className="p-3 pb-2 space-y-0">
                <div className="flex justify-between items-start gap-2">
                  <CardTitle className="text-sm font-serif font-bold leading-tight text-primary">
                    {citation.caseName}
                  </CardTitle>
                  <Button variant="ghost" size="icon" className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity">
                    <ExternalLink className="h-3 w-3 text-muted-foreground" />
                  </Button>
                </div>
                <div className="text-[11px] font-mono text-muted-foreground">
                  Page {citation.page} • Opinion ID: {citation.opinionId}
                </div>
              </CardHeader>
              <CardContent className="p-3 pt-2">
                <div className="relative bg-muted/30 p-2.5 rounded text-sm text-foreground/80 leading-relaxed italic border border-muted/50">
                  <Quote className="absolute top-1 left-1 h-3 w-3 text-primary/20 transform -scale-x-100" />
                  <span className="relative z-10">{citation.text}</span>
                </div>
              </CardContent>
            </Card>
          )) : (
            <div className="text-center py-10 text-muted-foreground">
              <p className="text-sm">No citations selected.</p>
              <p className="text-xs opacity-60 mt-1">Click a citation in the chat to view details.</p>
            </div>
          )}
        </div>
      </ScrollArea>
      
      <div className="p-4 border-t bg-muted/10 text-xs text-muted-foreground">
        <p>
          <strong>Note:</strong> All citations are extracted verbatim from official CAFC opinion documents.
        </p>
      </div>
    </div>
  );
}
