import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ExternalLink, BookOpen, Quote, Copy, Check, ChevronDown, ChevronUp } from "lucide-react";
import { useApp } from "@/context/AppContext";
import { useState } from "react";

function ExpandableQuote({ quote, index }: { quote: string; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = quote.length > 200;
  
  if (!isLong) {
    return <span className="relative z-10">{quote}</span>;
  }
  
  return (
    <div className="relative z-10">
      <span>{expanded ? quote : `${quote.slice(0, 200)}...`}</span>
      <button
        onClick={() => setExpanded(!expanded)}
        className="ml-1 text-primary text-[10px] hover:underline inline-flex items-center gap-0.5"
        data-testid={`button-expand-quote-${index}`}
      >
        {expanded ? (
          <>Show less <ChevronUp className="h-3 w-3" /></>
        ) : (
          <>Show more <ChevronDown className="h-3 w-3" /></>
        )}
      </button>
    </div>
  );
}

export function SourcesPanel() {
  const { selectedCitations } = useApp();
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const handleCopy = async (text: string, index: number) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 2000);
    } catch (error) {
      console.error("Failed to copy:", error);
    }
  };

  return (
    <div className="flex flex-col h-full bg-card">
      <div className="p-4 border-b flex items-center justify-between bg-muted/10">
        <div className="flex items-center gap-2 text-primary">
          <BookOpen className="h-4 w-4" />
          <h2 className="font-semibold text-sm tracking-tight">Cited Sources</h2>
        </div>
        <Badge variant="outline" className="font-mono text-[10px]">
          {selectedCitations.length} Reference{selectedCitations.length !== 1 ? 's' : ''}
        </Badge>
      </div>

      <ScrollArea className="flex-1 p-4">
        <div className="space-y-4">
          {selectedCitations.length > 0 ? selectedCitations.map((citation, index) => (
            <Card 
              key={index} 
              className="shadow-sm border-l-4 border-l-primary/40 hover:border-l-primary transition-all group"
              data-testid={`source-card-${index}`}
            >
              <CardHeader className="p-3 pb-2 space-y-0">
                <div className="flex justify-between items-start gap-2">
                  <CardTitle className="text-sm font-serif font-bold leading-tight text-primary">
                    {citation.caseName}
                  </CardTitle>
                  <Button 
                    variant="ghost" 
                    size="icon" 
                    className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={() => handleCopy(citation.quote, index)}
                    data-testid={`button-copy-citation-${index}`}
                  >
                    {copiedIndex === index ? (
                      <Check className="h-3 w-3 text-green-500" />
                    ) : (
                      <Copy className="h-3 w-3 text-muted-foreground" />
                    )}
                  </Button>
                </div>
                <div className="text-[11px] font-mono text-muted-foreground">
                  {citation.appealNo} • {citation.releaseDate} • Page {citation.pageNumber}
                </div>
              </CardHeader>
              <CardContent className="p-3 pt-2">
                <div className="relative bg-muted/30 p-2.5 rounded text-sm text-foreground/80 leading-relaxed italic border border-muted/50">
                  <Quote className="absolute top-1 left-1 h-3 w-3 text-primary/20 transform -scale-x-100" />
                  <ExpandableQuote quote={citation.quote} index={index} />
                </div>
              </CardContent>
            </Card>
          )) : (
            <div className="text-center py-10 text-muted-foreground">
              <BookOpen className="h-8 w-8 mx-auto mb-3 opacity-30" />
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
