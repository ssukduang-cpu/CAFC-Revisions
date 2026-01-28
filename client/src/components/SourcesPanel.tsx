import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ExternalLink, BookOpen, Quote, Copy, Check, ChevronDown, ChevronUp, HelpCircle } from "lucide-react";
import { useApp } from "@/context/AppContext";
import { useState } from "react";
import { Link } from "wouter";
import { ConfidenceBadge, SignalsList } from "@/components/ConfidenceBadge";
import type { ConfidenceTier, CitationSignal } from "@/lib/api";

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
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center">
            <BookOpen className="h-4 w-4 text-primary" />
          </div>
          <div>
            <h2 className="font-bold text-sm tracking-tight text-foreground">Cited Sources</h2>
            <p className="text-[10px] text-muted-foreground">Verified citations</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/citation-guide">
            <Button variant="ghost" size="icon" className="h-7 w-7" title="How confidence scoring works" data-testid="link-citation-guide">
              <HelpCircle className="h-4 w-4 text-muted-foreground" />
            </Button>
          </Link>
          <Badge variant="secondary" className="font-mono text-[10px] font-semibold">
            {selectedCitations.length}
          </Badge>
        </div>
      </div>

      <ScrollArea className="flex-1 p-4">
        <div className="space-y-4">
          {selectedCitations.length > 0 ? selectedCitations.map((citation, index) => (
            <Card 
              key={index} 
              className="shadow-sm border border-border hover:border-primary/30 hover:shadow-md transition-all group overflow-hidden"
              data-testid={`source-card-${index}`}
            >
              <CardHeader className="p-4 pb-3 space-y-0 bg-muted/30">
                <div className="flex justify-between items-start gap-2">
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2">
                      <CardTitle className="text-sm font-bold leading-tight text-foreground">
                        {citation.caseName}
                      </CardTitle>
                      {citation.tier && (
                        <ConfidenceBadge 
                          tier={citation.tier as ConfidenceTier} 
                          signals={(citation.signals || []) as CitationSignal[]}
                          showLabel
                          size="sm"
                        />
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-[10px] font-mono text-muted-foreground">
                      {citation.court === 'SCOTUS' && (
                        <span className="px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-700 dark:text-purple-300 font-semibold">Supreme Court</span>
                      )}
                      <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary font-semibold">{citation.appealNo}</span>
                      <span>{citation.releaseDate}</span>
                      <span>•</span>
                      <span>Page {citation.pageNumber}</span>
                    </div>
                    {citation.signals && citation.signals.length > 0 && (
                      <SignalsList signals={(citation.signals || []) as CitationSignal[]} className="mt-1" />
                    )}
                  </div>
                  <Button 
                    variant="ghost" 
                    size="icon" 
                    className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity rounded-lg"
                    onClick={() => handleCopy(citation.quote, index)}
                    data-testid={`button-copy-citation-${index}`}
                  >
                    {copiedIndex === index ? (
                      <Check className="h-3.5 w-3.5 text-green-500" />
                    ) : (
                      <Copy className="h-3.5 w-3.5 text-muted-foreground" />
                    )}
                  </Button>
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
      
      <div className="p-4 border-t border-border">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <div className="h-1.5 w-1.5 rounded-full bg-green-500"></div>
          <p>Citations verified against official CAFC and Supreme Court documents</p>
        </div>
      </div>
    </div>
  );
}
