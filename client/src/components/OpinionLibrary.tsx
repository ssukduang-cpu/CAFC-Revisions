import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { 
  RefreshCw, 
  Download, 
  Search, 
  CheckCircle2, 
  Circle,
  ExternalLink,
  Loader2,
  Scale,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Info
} from "lucide-react";
import { useApp } from "@/context/AppContext";
import { useSyncOpinions, useIngestOpinion, useStatus } from "@/hooks/useOpinions";
import { useState, useCallback, useEffect, useMemo } from "react";
import { fetchOpinions } from "@/lib/api";
import type { Opinion } from "@shared/schema";
import { useToast } from "@/hooks/use-toast";

const PAGE_SIZE = 25;

interface OpinionRowProps {
  opinion: Opinion;
  onIngest: (id: string) => void;
  isIngesting: boolean;
}

function OpinionCard({ opinion, onIngest, isIngesting }: OpinionRowProps) {
  const externalUrl = opinion.pdfUrl?.includes('cafc.uscourts.gov') 
    ? opinion.pdfUrl 
    : (opinion.courtlistenerUrl || opinion.pdfUrl);

  const extractPatentSections = (text: string): string[] => {
    const sections: string[] = [];
    if (/§\s*101|section\s*101/i.test(text)) sections.push('§101');
    if (/§\s*102|section\s*102/i.test(text)) sections.push('§102');
    if (/§\s*103|section\s*103/i.test(text)) sections.push('§103');
    if (/§\s*112|section\s*112/i.test(text)) sections.push('§112');
    return sections;
  };

  const patentSections = useMemo(() => extractPatentSections(opinion.caseName), [opinion.caseName]);

  return (
    <div 
      className="p-3 transition-all duration-150 border-b border-border/50 hover:bg-muted/40"
      data-testid={`opinion-card-${opinion.id}`}
    >
      <div className="flex items-start gap-3">
        <div className="shrink-0 mt-0.5">
          {opinion.isIngested ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          ) : (
            <Circle className="h-4 w-4 text-muted-foreground/30" />
          )}
        </div>
        
        <div className="flex-1 min-w-0 space-y-1.5">
          <h3 className="font-semibold text-sm leading-tight line-clamp-2 text-foreground">
            {opinion.caseName}
          </h3>
          
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="font-mono tracking-tight">{opinion.appealNo}</span>
            <span className="text-muted-foreground/40">•</span>
            <span>{opinion.releaseDate}</span>
          </div>
          
          <div className="flex items-center gap-1.5 flex-wrap">
            {opinion.isIngested && (
              <Badge 
                variant="outline" 
                className="text-[10px] px-1.5 py-0 h-5 border-emerald-500/30 text-emerald-600 font-medium gap-1"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                Indexed
              </Badge>
            )}
            
            {patentSections.map(section => (
              <Badge 
                key={section}
                variant="outline" 
                className="text-[10px] px-1.5 py-0 h-5 border-amber-500/30 text-amber-600 font-medium"
              >
                {section}
              </Badge>
            ))}
            
            {(opinion as any).isLandmark && (
              <Badge 
                variant="outline" 
                className="text-[10px] px-1.5 py-0 h-5 border-amber-500/50 bg-gradient-to-r from-amber-500/20 to-yellow-500/20 text-amber-700 font-semibold gap-1"
              >
                <Scale className="h-2.5 w-2.5" />
                Landmark
              </Badge>
            )}
          </div>
        </div>
        
        <div className="flex items-center gap-1 shrink-0">
          {!opinion.isIngested && (
            <Button
              size="sm"
              variant="ghost"
              onClick={(e) => {
                e.stopPropagation();
                onIngest(opinion.id);
              }}
              disabled={isIngesting}
              className="h-7 w-7 p-0"
              data-testid={`button-ingest-${opinion.id}`}
              title="Index for AI search"
            >
              {isIngesting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Download className="h-3.5 w-3.5" />
              )}
            </Button>
          )}
          <a 
            href={externalUrl} 
            target="_blank" 
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="h-7 w-7 flex items-center justify-center hover:bg-muted rounded transition-colors"
            data-testid={`link-external-${opinion.id}`}
            title="Open on CourtListener"
          >
            <ExternalLink className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
          </a>
        </div>
      </div>
    </div>
  );
}

const YEARS = Array.from({ length: 2026 - 2004 + 1 }, (_, i) => 2026 - i);

export function OpinionLibrary() {
  const { showOpinionLibrary, setShowOpinionLibrary } = useApp();
  const [searchTerm, setSearchTerm] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [ingestingId, setIngestingId] = useState<string | null>(null);
  const [opinions, setOpinions] = useState<Opinion[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [author, setAuthor] = useState("");
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const { toast } = useToast();
  
  const { data: status } = useStatus();
  const syncOpinions = useSyncOpinions();
  const ingestOpinion = useIngestOpinion();

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchTerm);
      setCurrentPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  const loadOpinions = useCallback(async () => {
    setIsLoading(true);
    try {
      const offset = (currentPage - 1) * PAGE_SIZE;
      const data = await fetchOpinions({
        limit: PAGE_SIZE,
        offset,
        q: debouncedSearch || undefined,
        author: author && author !== "all" ? author : undefined,
        includeR36: false,
        year: selectedYear || undefined,
        ingested: undefined  // Show ALL cases (both ingested and not ingested)
      });
      setOpinions(data.opinions);
      setTotal(data.total);
    } catch (error: any) {
      console.error("Failed to load opinions:", error);
      toast({
        title: "Failed to Load Opinions",
        description: error?.message || "Could not load opinions. Please try again.",
        variant: "destructive",
      });
    }
    setIsLoading(false);
  }, [debouncedSearch, author, currentPage, selectedYear, toast]);

  useEffect(() => {
    if (showOpinionLibrary) {
      loadOpinions();
    }
  }, [showOpinionLibrary, loadOpinions]);

  const handleSync = async () => {
    try {
      await syncOpinions.mutateAsync();
      loadOpinions();
      toast({
        title: "Sync Complete",
        description: "Successfully synced opinions from the Federal Circuit website.",
      });
    } catch (error: any) {
      console.error("Sync failed:", error);
      toast({
        title: "Sync Failed",
        description: error?.message || "Could not sync opinions. Please try again later.",
        variant: "destructive",
      });
    }
  };

  const handleIngest = async (opinionId: string) => {
    setIngestingId(opinionId);
    try {
      await ingestOpinion.mutateAsync(opinionId);
      setOpinions(prev => prev.map(op => 
        op.id === opinionId ? { ...op, isIngested: true } : op
      ));
      toast({
        title: "Ingestion Complete",
        description: "Opinion has been successfully ingested and is now searchable.",
      });
    } catch (error: any) {
      console.error("Ingest failed:", error);
      toast({
        title: "Ingestion Failed",
        description: error?.message || "Could not ingest opinion. Please try again.",
        variant: "destructive",
      });
    } finally {
      setIngestingId(null);
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  if (!showOpinionLibrary) return null;

  return (
    <div className="fixed inset-0 z-50 bg-background overflow-hidden">
      <div className="h-full w-full flex flex-col">
        <header className="h-14 border-b flex items-center justify-between px-4 bg-card/80 backdrop-blur-sm shrink-0">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowOpinionLibrary(false)}
              className="gap-2"
              data-testid="button-back"
            >
              <ArrowLeft className="h-4 w-4" />
              <span className="hidden sm:inline">Back to Chat</span>
              <span className="sm:hidden">Back</span>
            </Button>
            <div className="h-6 w-px bg-border hidden sm:block" />
            <div className="flex items-center gap-2">
              <Scale className="h-5 w-5 text-primary" />
              <h1 className="font-semibold text-sm sm:text-base">Opinion Library</h1>
            </div>
          </div>
          
          <a href="/admin" className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors">
            <Info className="h-4 w-4" />
            <span className="hidden sm:inline">Database Info</span>
          </a>
        </header>

        <div className="flex-1 flex flex-col min-h-0 max-w-4xl mx-auto w-full">
          <div className="p-3 sm:p-4 border-b space-y-3 bg-card/30 shrink-0">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input 
                placeholder="Search by case name or appeal number..." 
                className="pl-9 h-10"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                data-testid="input-search-opinions"
              />
            </div>
            
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="flex items-center gap-2 flex-wrap">
                <Button 
                  onClick={handleSync}
                  disabled={syncOpinions.isPending}
                  variant="outline"
                  size="sm"
                  className="gap-1.5 h-8 text-xs sm:text-sm"
                  data-testid="button-sync-opinions"
                >
                  {syncOpinions.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" />
                  )}
                  <span className="hidden sm:inline">Sync from CAFC</span>
                  <span className="sm:hidden">Sync</span>
                </Button>
                
                <select
                  value={selectedYear || ""}
                  onChange={(e) => {
                    const year = e.target.value ? parseInt(e.target.value) : null;
                    setSelectedYear(year);
                    setCurrentPage(1);
                  }}
                  className="h-8 px-2 text-xs sm:text-sm border rounded-md bg-background text-foreground"
                  data-testid="select-year"
                >
                  <option value="">All Years</option>
                  {YEARS.map(year => (
                    <option key={year} value={year}>{year}</option>
                  ))}
                </select>
              </div>
              
              <div className="text-xs sm:text-sm text-muted-foreground">
                {total > 0 ? `${total} opinions` : `${status?.opinions.ingested ?? 0} searchable`}
              </div>
            </div>
          </div>
          
          <div 
            className="flex-1 overflow-y-auto overscroll-contain"
            style={{ WebkitOverflowScrolling: 'touch' }}
          >
            {isLoading ? (
              <div className="flex items-center justify-center h-48">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : opinions.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 text-muted-foreground p-6">
                <p className="text-sm mb-4">
                  {searchTerm ? "No opinions match your search" : "No opinions synced yet"}
                </p>
                {!searchTerm && (
                  <Button onClick={handleSync} disabled={syncOpinions.isPending} size="sm">
                    Sync from CAFC
                  </Button>
                )}
              </div>
            ) : (
              <div className="pb-4">
                {opinions.map((opinion) => (
                  <OpinionCard
                    key={opinion.id}
                    opinion={opinion}
                    onIngest={handleIngest}
                    isIngesting={ingestingId === opinion.id}
                  />
                ))}
              </div>
            )}
          </div>
          
          {totalPages > 1 && (
            <div className="p-3 sm:p-4 border-t flex items-center justify-between shrink-0 bg-background">
              <div className="text-xs sm:text-sm text-muted-foreground">
                <span className="hidden sm:inline">Page {currentPage} of {totalPages} ({total.toLocaleString()} searchable)</span>
                <span className="sm:hidden">{currentPage}/{totalPages}</span>
              </div>
              
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className="gap-1 h-8 px-2 sm:px-3"
                >
                  <ChevronLeft className="h-4 w-4" />
                  <span className="hidden sm:inline">Previous</span>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                  disabled={currentPage === totalPages}
                  className="gap-1 h-8 px-2 sm:px-3"
                >
                  <span className="hidden sm:inline">Next</span>
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
