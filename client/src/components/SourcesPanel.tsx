import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ExternalLink, BookOpen, Quote, Copy, Check, ChevronDown, ChevronUp, Scale, Gavel, Search, AlertTriangle } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useApp } from "@/context/AppContext";
import { useState } from "react";
import { Link } from "wouter";
import { ConfidenceBadge, SignalsList } from "@/components/ConfidenceBadge";
import type { ConfidenceTier, CitationSignal, ControllingAuthority } from "@/lib/api";

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

function ControllingAuthoritiesSection({ authorities }: { authorities: ControllingAuthority[] }) {
  if (authorities.length === 0) return null;
  
  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <div className="h-6 w-6 rounded bg-purple-500/20 flex items-center justify-center">
          <Scale className="h-3.5 w-3.5 text-purple-600 dark:text-purple-400" />
        </div>
        <div>
          <h3 className="font-semibold text-xs text-foreground">Controlling Authorities</h3>
          <p className="text-[9px] text-muted-foreground">Recommended framework cases; not necessarily cited in answer</p>
        </div>
      </div>
      <div className="space-y-2">
        {authorities.map((auth, index) => (
          <Card 
            key={`${auth.opinion_id}-${index}`}
            className="border border-purple-200 dark:border-purple-800/50 bg-purple-50/30 dark:bg-purple-900/10"
            data-testid={`controlling-authority-${index}`}
          >
            <CardContent className="p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Gavel className="h-3.5 w-3.5 text-purple-600 dark:text-purple-400" />
                    <span className="font-semibold text-sm text-foreground">{auth.case_name}</span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                    <span className="px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-700 dark:text-purple-300 font-semibold">
                      {auth.court === 'SCOTUS' ? 'Supreme Court' : auth.court}
                    </span>
                    {auth.release_date && <span>{auth.release_date}</span>}
                  </div>
                  <p className="text-[10px] text-muted-foreground italic">{auth.why_recommended}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

export function SourcesPanel() {
  const { selectedCitations, controllingAuthorities } = useApp();
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
  const handleOpenSource = (citation: any) => {
    let url = citation.viewerUrl || citation.courtlistenerUrl || citation.pdfUrl;
    if (url && typeof url === 'string' && url.startsWith('/pdf/') && !url.includes('redirect=')) {
      url += (url.includes('?') ? '&' : '?') + 'redirect=1';
    }
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer');
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
            <h2 className="font-bold text-sm tracking-tight text-foreground">Sources</h2>
            <p className="text-[10px] text-muted-foreground">Framework & cited references</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="font-mono text-[10px] font-semibold">
            {selectedCitations.length}
          </Badge>
        </div>
      </div>

      <ScrollArea className="flex-1 p-4">
        <div className="space-y-4">
          <ControllingAuthoritiesSection authorities={controllingAuthorities} />
          
          {selectedCitations.length > 0 && (
            <div className="flex items-center gap-2 mb-2">
              <div className="h-6 w-6 rounded bg-primary/10 flex items-center justify-center">
                <BookOpen className="h-3.5 w-3.5 text-primary" />
              </div>
              <div>
                <h3 className="font-semibold text-xs text-foreground">Cited Sources</h3>
                <p className="text-[9px] text-muted-foreground">Referenced in the answer with verification</p>
                <p className="text-[9px] text-muted-foreground">Tier guide: STRONG/MODERATE = safer authority; WEAK/UNVERIFIED = background only.</p>
              </div>
            </div>
          )}
          
          {selectedCitations.length > 0 ? selectedCitations.map((citation, index) => {
            const cardTier = (citation.tier || 'unverified') as string;
            const cardBorderClass = cardTier === 'strong' ? 'border-l-green-500' 
              : cardTier === 'moderate' ? 'border-l-yellow-500'
              : cardTier === 'weak' ? 'border-l-orange-500'
              : 'border-l-red-500';
            return (
            <Card 
              key={index} 
              className={`shadow-sm border border-border hover:border-primary/30 hover:shadow-md transition-all group overflow-hidden border-l-[3px] ${cardBorderClass}`}
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
                    {citation.applicationReason && (
                      <div className="mt-2 text-[10px] text-muted-foreground bg-primary/5 px-2 py-1 rounded border border-primary/10">
                        <span className="font-semibold text-primary">Why this case: </span>
                        {citation.applicationReason}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    {(citation.viewerUrl || citation.courtlistenerUrl || citation.pdfUrl) && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity rounded-lg"
                        onClick={() => handleOpenSource(citation)}
                        data-testid={`button-open-citation-${index}`}
                        title="Open source document"
                      >
                        <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
                      </Button>
                    )}
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
                </div>
              </CardHeader>
              <CardContent className="p-3 pt-2 space-y-2">
                <div className="relative bg-muted/30 p-2.5 rounded text-sm text-foreground/80 leading-relaxed italic border border-muted/50">
                  <Quote className="absolute top-1 left-1 h-3 w-3 text-primary/20 transform -scale-x-100" />
                  <ExpandableQuote quote={citation.quote} index={index} />
                </div>
                
                {citation.tier?.toUpperCase() === 'UNVERIFIED' && (
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Dialog>
                          <DialogTrigger asChild>
                            <Button 
                              variant="outline" 
                              size="sm" 
                              className="w-full gap-2 text-xs border-red-200 text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-900/20"
                              data-testid={`button-show-passages-${index}`}
                            >
                              <Search className="h-3.5 w-3.5" />
                              Show Candidate Passages
                            </Button>
                          </DialogTrigger>
                          <DialogContent className="max-w-lg">
                            <DialogHeader>
                              <DialogTitle className="flex items-center gap-2">
                                <AlertTriangle className="h-5 w-5 text-red-500" />
                                Unverified Citation
                              </DialogTitle>
                            </DialogHeader>
                            <div className="space-y-4 text-sm">
                              <div className="p-3 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
                                <p className="text-red-700 dark:text-red-300 text-xs mb-2">
                                  <strong>Case:</strong> {citation.caseName}
                                </p>
                                <p className="text-red-600 dark:text-red-400 text-xs italic">
                                  "{citation.quote.slice(0, 200)}{citation.quote.length > 200 ? '...' : ''}"
                                </p>
                              </div>
                              <p className="text-muted-foreground">
                                This quote could not be verified in the source document. 
                                You may need to manually locate the passage in the PDF.
                              </p>
                              {(citation as any).pdfUrl && (
                                <Button 
                                  variant="outline" 
                                  className="w-full gap-2"
                                  onClick={() => window.open((citation as any).pdfUrl, '_blank')}
                                >
                                  <ExternalLink className="h-4 w-4" />
                                  Open Source PDF
                                </Button>
                              )}
                              <p className="text-xs text-muted-foreground">
                                Tip: Search for key phrases in the PDF to locate the passage.
                              </p>
                            </div>
                          </DialogContent>
                        </Dialog>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p className="text-xs">View candidate passages and PDF link</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                )}
              </CardContent>
            </Card>
            );
          }) : (
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
