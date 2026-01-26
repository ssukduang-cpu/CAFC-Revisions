import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { 
  Panel, 
  PanelGroup, 
  PanelResizeHandle 
} from "react-resizable-panels";
import { List as VirtualList, useListRef } from "react-window";
import { 
  RefreshCw, 
  Download, 
  Search, 
  CheckCircle2, 
  Circle,
  ExternalLink,
  Loader2,
  FileText,
  Scale,
  ArrowLeft,
  GripVertical
} from "lucide-react";
import { useApp } from "@/context/AppContext";
import { useSyncOpinions, useIngestOpinion, useStatus } from "@/hooks/useOpinions";
import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { fetchOpinions } from "@/lib/api";
import { SearchFilters } from "./SearchFilters";
import type { Opinion } from "@shared/schema";

const PAGE_SIZE = 100;
const ROW_HEIGHT = 88;

interface OpinionRowProps {
  opinion: Opinion;
  isSelected: boolean;
  onSelect: (opinion: Opinion) => void;
  onIngest: (id: string) => void;
  isIngesting: boolean;
}

function OpinionCard({ opinion, isSelected, onSelect, onIngest, isIngesting }: OpinionRowProps) {
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
      onClick={() => onSelect(opinion)}
      className={`
        p-3 cursor-pointer transition-all duration-150 border-l-2
        ${isSelected 
          ? 'bg-primary/5 border-l-primary shadow-sm' 
          : 'border-l-transparent hover:bg-muted/40 hover:border-l-muted-foreground/20'
        }
      `}
      data-testid={`opinion-card-${opinion.id}`}
    >
      <div className="flex items-start gap-3">
        <div className="shrink-0 mt-0.5">
          {opinion.isIngested ? (
            <div className="relative">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              <span className="absolute -bottom-0.5 -right-0.5 w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
            </div>
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
            <Badge 
              variant="secondary" 
              className="text-[10px] px-1.5 py-0 h-5 bg-blue-500/10 text-blue-600 border-0 font-medium"
            >
              Precedential
            </Badge>
            
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
            
            {(opinion as any).lastError?.toLowerCase().includes('ocr') && (
              <Badge 
                variant="outline" 
                className="text-[10px] px-1.5 py-0 h-5 border-amber-500/50 bg-amber-500/10 text-amber-700 font-medium"
              >
                OCR Required
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

function PDFViewer({ opinion }: { opinion: Opinion | null }) {
  const [pdfError, setPdfError] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (opinion) {
      setPdfError(false);
      setIsLoading(true);
    }
  }, [opinion?.id]);

  if (!opinion) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-muted-foreground bg-muted/20">
        <div className="text-center space-y-4">
          <div className="mx-auto w-16 h-16 rounded-full bg-muted/50 flex items-center justify-center">
            <FileText className="h-8 w-8 text-muted-foreground/50" />
          </div>
          <div className="space-y-1">
            <p className="font-medium text-foreground/70">Select an opinion to preview</p>
            <p className="text-sm text-muted-foreground/60">
              Click any case from the list to view its PDF
            </p>
          </div>
        </div>
      </div>
    );
  }

  const pdfUrl = `/pdf/${opinion.id}`;
  const fallbackUrl = opinion.courtlistenerUrl || opinion.pdfUrl;

  return (
    <div className="h-full flex flex-col">
      <div className="p-3 border-b bg-card/50 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <h2 className="font-semibold text-sm leading-tight line-clamp-2">
              {opinion.caseName}
            </h2>
            <p className="text-xs text-muted-foreground mt-1">
              <span className="font-mono">{opinion.appealNo}</span>
              <span className="mx-1.5">•</span>
              <span>{opinion.releaseDate}</span>
            </p>
          </div>
          {fallbackUrl && (
            <a
              href={fallbackUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="shrink-0"
            >
              <Button size="sm" variant="outline" className="h-7 text-xs gap-1.5">
                <ExternalLink className="h-3 w-3" />
                Source
              </Button>
            </a>
          )}
        </div>
      </div>
      
      <div className="flex-1 relative bg-muted/30">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/80 z-10">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}
        
        {pdfError ? (
          <div className="h-full flex flex-col items-center justify-center text-muted-foreground p-6">
            <div className="text-center space-y-4">
              <p className="text-sm">PDF not available locally</p>
              {fallbackUrl && (
                <a
                  href={fallbackUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Button variant="outline" className="gap-2">
                    <ExternalLink className="h-4 w-4" />
                    View on CourtListener
                  </Button>
                </a>
              )}
            </div>
          </div>
        ) : (
          <iframe
            src={pdfUrl}
            className="w-full h-full border-0"
            title={`PDF: ${opinion.caseName}`}
            onLoad={() => setIsLoading(false)}
            onError={() => {
              setIsLoading(false);
              setPdfError(true);
            }}
          />
        )}
      </div>
    </div>
  );
}

export function OpinionLibrary() {
  const { showOpinionLibrary, setShowOpinionLibrary } = useApp();
  const [searchTerm, setSearchTerm] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [ingestingId, setIngestingId] = useState<string | null>(null);
  const [opinions, setOpinions] = useState<Opinion[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [selectedOpinion, setSelectedOpinion] = useState<Opinion | null>(null);
  const [author, setAuthor] = useState("");
  const [includeR36, setIncludeR36] = useState(true);
  
  const listRef = useListRef(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [listHeight, setListHeight] = useState(600);
  
  const { data: status } = useStatus();
  const syncOpinions = useSyncOpinions();
  const ingestOpinion = useIngestOpinion();

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchTerm), 300);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  useEffect(() => {
    if (containerRef.current) {
      const resizeObserver = new ResizeObserver(entries => {
        for (const entry of entries) {
          setListHeight(entry.contentRect.height);
        }
      });
      resizeObserver.observe(containerRef.current);
      return () => resizeObserver.disconnect();
    }
  }, []);

  const loadAllOpinions = useCallback(async () => {
    setIsLoading(true);
    let allOpinions: Opinion[] = [];
    let offset = 0;
    let more = true;
    
    while (more) {
      try {
        const data = await fetchOpinions({
          limit: PAGE_SIZE,
          offset,
          q: debouncedSearch || undefined,
          author: author && author !== "all" ? author : undefined,
          includeR36
        });
        allOpinions = [...allOpinions, ...data.opinions];
        setOpinions(allOpinions);
        setTotal(data.total);
        more = data.hasMore;
        offset += data.opinions.length;
        
        if (allOpinions.length >= 500) {
          setHasMore(more);
          break;
        }
      } catch (error) {
        console.error("Failed to load opinions:", error);
        break;
      }
    }
    
    setIsLoading(false);
  }, [debouncedSearch, author, includeR36]);

  useEffect(() => {
    if (showOpinionLibrary) {
      loadAllOpinions();
    }
  }, [showOpinionLibrary, debouncedSearch, author, includeR36]);

  const handleSync = async () => {
    try {
      await syncOpinions.mutateAsync();
      loadAllOpinions();
    } catch (error) {
      console.error("Sync failed:", error);
    }
  };

  const handleIngest = async (opinionId: string) => {
    setIngestingId(opinionId);
    try {
      await ingestOpinion.mutateAsync(opinionId);
      setOpinions(prev => prev.map(op => 
        op.id === opinionId ? { ...op, isIngested: true } : op
      ));
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

  const handleSelectOpinion = (opinion: Opinion) => {
    setSelectedOpinion(opinion);
  };

  if (!showOpinionLibrary) return null;

  return (
    <div className="fixed inset-0 z-50 bg-background flex flex-col">
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
            Back to Chat
          </Button>
          <div className="h-6 w-px bg-border" />
          <div className="flex items-center gap-2">
            <Scale className="h-5 w-5 text-primary" />
            <h1 className="font-semibold">Opinion Library</h1>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="font-mono text-xs px-2.5 py-1">
            {status?.opinions.ingested ?? 0} / {status?.opinions.total ?? 0} indexed
          </Badge>
        </div>
      </header>

      <PanelGroup direction="horizontal" className="flex-1">
        <Panel defaultSize={40} minSize={30} maxSize={60}>
          <div className="h-full flex flex-col border-r">
            <div className="p-3 border-b space-y-3 bg-card/30">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input 
                  placeholder="Search by case name or appeal number..." 
                  className="pl-9 h-9"
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  data-testid="input-search-opinions"
                />
              </div>
              
              <SearchFilters
                author={author}
                setAuthor={setAuthor}
                includeR36={includeR36}
                setIncludeR36={setIncludeR36}
              />
              
              <div className="flex items-center gap-2">
                <Button 
                  onClick={handleSync}
                  disabled={syncOpinions.isPending}
                  variant="outline"
                  size="sm"
                  className="gap-1.5 h-8 flex-1"
                  data-testid="button-sync-opinions"
                >
                  {syncOpinions.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" />
                  )}
                  Sync
                </Button>
                <Button 
                  onClick={handleIngestAll}
                  disabled={ingestOpinion.isPending || opinions.filter(o => !o.isIngested).length === 0}
                  size="sm"
                  className="gap-1.5 h-8 flex-1"
                  data-testid="button-ingest-all"
                >
                  <Download className="h-3.5 w-3.5" />
                  Ingest Next 5
                </Button>
              </div>
              
              <div className="text-xs text-muted-foreground">
                Showing {opinions.length} of {total} opinions
              </div>
            </div>
            
            <div ref={containerRef} className="flex-1 overflow-hidden">
              {isLoading && opinions.length === 0 ? (
                <div className="flex items-center justify-center h-full">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : opinions.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-6">
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
                <VirtualList
                  listRef={listRef}
                  rowCount={opinions.length}
                  rowHeight={ROW_HEIGHT}
                  overscanCount={5}
                  style={{ height: listHeight, width: '100%' }}
                  rowProps={{}}
                  rowComponent={({ index, style }) => {
                    const opinion = opinions[index];
                    if (!opinion) return null;
                    return (
                      <div style={style}>
                        <OpinionCard
                          opinion={opinion}
                          isSelected={selectedOpinion?.id === opinion.id}
                          onSelect={handleSelectOpinion}
                          onIngest={handleIngest}
                          isIngesting={ingestingId === opinion.id}
                        />
                      </div>
                    );
                  }}
                />
              )}
            </div>
          </div>
        </Panel>
        
        <PanelResizeHandle className="w-1.5 bg-border hover:bg-primary/20 transition-colors flex items-center justify-center group">
          <GripVertical className="h-4 w-4 text-muted-foreground/50 group-hover:text-primary transition-colors" />
        </PanelResizeHandle>
        
        <Panel defaultSize={60} minSize={40}>
          <PDFViewer opinion={selectedOpinion} />
        </Panel>
      </PanelGroup>
    </div>
  );
}
