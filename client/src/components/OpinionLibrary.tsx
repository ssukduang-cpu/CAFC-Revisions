import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { 
  Dialog, 
  DialogContent, 
  DialogHeader, 
  DialogTitle,
  DialogDescription
} from "@/components/ui/dialog";
import { 
  RefreshCw, 
  Download, 
  Search, 
  CheckCircle2, 
  Circle,
  ExternalLink,
  Loader2,
  ChevronDown
} from "lucide-react";
import { useApp } from "@/context/AppContext";
import { useSyncOpinions, useIngestOpinion, useStatus } from "@/hooks/useOpinions";
import { useState, useCallback, useEffect } from "react";
import { fetchOpinions } from "@/lib/api";
import type { Opinion } from "@shared/schema";

const PAGE_SIZE = 50;

export function OpinionLibrary() {
  const { showOpinionLibrary, setShowOpinionLibrary } = useApp();
  const [searchTerm, setSearchTerm] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [ingestingId, setIngestingId] = useState<string | null>(null);
  const [opinions, setOpinions] = useState<Opinion[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [total, setTotal] = useState(0);
  
  const { data: status } = useStatus();
  const syncOpinions = useSyncOpinions();
  const ingestOpinion = useIngestOpinion();

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchTerm), 300);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  const loadOpinions = useCallback(async (reset = false) => {
    const newOffset = reset ? 0 : offset;
    if (reset) {
      setIsLoading(true);
    } else {
      setIsLoadingMore(true);
    }
    
    try {
      const data = await fetchOpinions({
        limit: PAGE_SIZE,
        offset: newOffset,
        q: debouncedSearch || undefined
      });
      
      if (reset) {
        setOpinions(data.opinions);
      } else {
        setOpinions(prev => [...prev, ...data.opinions]);
      }
      setHasMore(data.hasMore);
      setTotal(data.total);
      setOffset(newOffset + data.opinions.length);
    } catch (error) {
      console.error("Failed to load opinions:", error);
    } finally {
      setIsLoading(false);
      setIsLoadingMore(false);
    }
  }, [offset, debouncedSearch]);

  useEffect(() => {
    if (showOpinionLibrary) {
      loadOpinions(true);
    }
  }, [showOpinionLibrary, debouncedSearch]);

  const handleLoadMore = () => {
    loadOpinions(false);
  };

  const handleSync = async () => {
    try {
      await syncOpinions.mutateAsync();
    } catch (error) {
      console.error("Sync failed:", error);
    }
  };

  const handleIngest = async (opinionId: string) => {
    setIngestingId(opinionId);
    try {
      await ingestOpinion.mutateAsync(opinionId);
    } catch (error) {
      console.error("Ingest failed:", error);
    } finally {
      setIngestingId(null);
    }
  };

  const handleIngestAll = async () => {
    const notIngested = opinions.filter(op => !op.isIngested);
    for (const op of notIngested.slice(0, 5)) {
      await handleIngest(op.id);
    }
  };

  return (
    <Dialog open={showOpinionLibrary} onOpenChange={setShowOpinionLibrary}>
      <DialogContent className="max-w-4xl h-[80vh] flex flex-col p-0">
        <DialogHeader className="p-6 pb-4 border-b border-border">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-xl bg-primary/10 flex items-center justify-center">
                <RefreshCw className="h-5 w-5 text-primary" />
              </div>
              <div>
                <DialogTitle className="text-xl font-bold">Opinion Library</DialogTitle>
                <DialogDescription className="text-sm text-muted-foreground">
                  Manage CAFC precedential opinions for AI-powered research
                </DialogDescription>
              </div>
            </div>
            <Badge variant="secondary" className="font-mono text-xs font-semibold px-3 py-1.5">
              {status?.opinions.ingested ?? 0} / {status?.opinions.total ?? 0} indexed
            </Badge>
          </div>
        </DialogHeader>

        <div className="p-6 space-y-4 flex-1 flex flex-col">
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input 
                placeholder="Search opinions by case name or appeal number..." 
                className="pl-9"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                data-testid="input-search-opinions"
              />
            </div>
            <Button 
              onClick={handleSync}
              disabled={syncOpinions.isPending}
              variant="outline"
              className="gap-2 h-10 rounded-lg font-medium"
              data-testid="button-sync-opinions"
              title="Fetch latest opinion list from CAFC website"
            >
              {syncOpinions.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              Sync List
            </Button>
            <Button 
              onClick={handleIngestAll}
              disabled={ingestOpinion.isPending || opinions.filter(o => !o.isIngested).length === 0}
              className="gap-2 h-10 rounded-lg font-semibold"
              data-testid="button-ingest-all"
              title="Download and process the next 5 opinions for AI search"
            >
              <Download className="h-4 w-4" />
              Ingest Next 5
            </Button>
          </div>

          <ScrollArea className="flex-1 border rounded-lg">
            <div className="divide-y">
              {isLoading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : opinions.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground">
                  {searchTerm ? (
                    <p>No opinions match your search</p>
                  ) : (
                    <div className="space-y-2">
                      <p>No opinions synced yet</p>
                      <Button onClick={handleSync} disabled={syncOpinions.isPending}>
                        Sync opinions from CAFC website
                      </Button>
                    </div>
                  )}
                </div>
              ) : (
                <>
                {opinions.map((opinion) => (
                  <div 
                    key={opinion.id}
                    className="p-3 hover:bg-muted/30 transition-colors grid grid-cols-[auto_1fr_auto] gap-3 items-center"
                    data-testid={`opinion-row-${opinion.id}`}
                  >
                    <a 
                      href={
                        opinion.pdfUrl?.includes('cafc.uscourts.gov') 
                          ? opinion.pdfUrl 
                          : (opinion.courtlistenerUrl || opinion.pdfUrl)
                      }
                      target="_blank"
                      rel="noopener noreferrer"
                      className="shrink-0 hover:scale-110 transition-transform"
                      title="Open opinion"
                    >
                      {opinion.isIngested ? (
                        <CheckCircle2 className="h-4 w-4 text-green-500" />
                      ) : (
                        <Circle className="h-4 w-4 text-muted-foreground/30" />
                      )}
                    </a>
                    <a 
                      href={
                        opinion.pdfUrl?.includes('cafc.uscourts.gov') 
                          ? opinion.pdfUrl 
                          : (opinion.courtlistenerUrl || opinion.pdfUrl)
                      }
                      target="_blank"
                      rel="noopener noreferrer"
                      className="min-w-0 overflow-hidden hover:text-primary transition-colors cursor-pointer"
                      title="Open opinion"
                    >
                      <div className="font-medium text-sm truncate">
                        {opinion.caseName}
                      </div>
                      <div className="text-xs text-muted-foreground truncate">
                        <span className="font-mono">{opinion.appealNo}</span>
                        <span className="mx-1">•</span>
                        <span>{opinion.releaseDate}</span>
                      </div>
                    </a>
                    <div className="flex items-center gap-2 shrink-0">
                      {!opinion.isIngested ? (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleIngest(opinion.id)}
                          disabled={ingestingId === opinion.id}
                          className="gap-1 h-7 text-xs"
                          data-testid={`button-ingest-${opinion.id}`}
                          title="Download PDF and extract text for AI search"
                        >
                          {ingestingId === opinion.id ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Download className="h-3 w-3" />
                          )}
                          Ingest
                        </Button>
                      ) : (
                        <span className="text-[10px] text-green-600 font-medium px-2">Indexed</span>
                      )}
                      <a 
                        href={
                          opinion.pdfUrl?.includes('cafc.uscourts.gov') 
                            ? opinion.pdfUrl 
                            : (opinion.courtlistenerUrl || opinion.pdfUrl)
                        } 
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="p-1.5 hover:bg-muted rounded transition-colors"
                        data-testid={`link-pdf-${opinion.id}`}
                        title={opinion.pdfUrl?.includes('cafc.uscourts.gov') ? "Open PDF on CAFC" : "View on CourtListener"}
                      >
                        <ExternalLink className="h-4 w-4 text-muted-foreground hover:text-foreground" />
                      </a>
                    </div>
                  </div>
                ))}
                {hasMore && (
                  <div className="p-4 text-center">
                    <Button
                      variant="outline"
                      onClick={handleLoadMore}
                      disabled={isLoadingMore}
                      className="gap-2"
                      data-testid="button-load-more"
                    >
                      {isLoadingMore ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <ChevronDown className="h-4 w-4" />
                      )}
                      Load More ({opinions.length} of {total})
                    </Button>
                  </div>
                )}
                </>
              )}
            </div>
          </ScrollArea>

          <div className="text-xs text-muted-foreground">
            <p>
              <strong>Sync:</strong> Fetches opinion metadata from the CAFC website. 
              <strong className="ml-2">Ingest:</strong> Downloads the PDF, extracts text, and indexes it for search.
            </p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
