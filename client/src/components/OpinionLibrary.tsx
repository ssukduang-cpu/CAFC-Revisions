import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
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
  Loader2
} from "lucide-react";
import { useApp } from "@/context/AppContext";
import { useOpinions, useSyncOpinions, useIngestOpinion } from "@/hooks/useOpinions";
import { useState } from "react";

export function OpinionLibrary() {
  const { showOpinionLibrary, setShowOpinionLibrary } = useApp();
  const [searchTerm, setSearchTerm] = useState("");
  const [ingestingId, setIngestingId] = useState<string | null>(null);
  
  const { data, isLoading } = useOpinions();
  const syncOpinions = useSyncOpinions();
  const ingestOpinion = useIngestOpinion();

  const opinions = data?.opinions || [];
  const filteredOpinions = opinions.filter(op => 
    op.caseName.toLowerCase().includes(searchTerm.toLowerCase()) ||
    op.appealNo.toLowerCase().includes(searchTerm.toLowerCase())
  );

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
              {data?.ingested || 0} / {data?.total || 0}
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
            >
              {syncOpinions.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              Sync from CAFC
            </Button>
            <Button 
              onClick={handleIngestAll}
              disabled={ingestOpinion.isPending || opinions.filter(o => !o.isIngested).length === 0}
              className="gap-2 h-10 rounded-lg font-semibold"
              data-testid="button-ingest-all"
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
              ) : filteredOpinions.length === 0 ? (
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
                filteredOpinions.map((opinion) => (
                  <div 
                    key={opinion.id}
                    className="p-4 hover:bg-muted/30 transition-colors flex items-center justify-between gap-4"
                    data-testid={`opinion-row-${opinion.id}`}
                  >
                    <div className="flex items-start gap-3 min-w-0 flex-1">
                      {opinion.isIngested ? (
                        <CheckCircle2 className="h-5 w-5 text-green-500 mt-0.5 shrink-0" />
                      ) : (
                        <Circle className="h-5 w-5 text-muted-foreground/30 mt-0.5 shrink-0" />
                      )}
                      <div className="min-w-0">
                        <div className="font-medium text-sm truncate">{opinion.caseName}</div>
                        <div className="text-xs text-muted-foreground space-x-2">
                          <span className="font-mono">{opinion.appealNo}</span>
                          <span>•</span>
                          <span>{opinion.releaseDate}</span>
                          <span>•</span>
                          <span>{opinion.origin}</span>
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Badge 
                        variant={opinion.status === "Precedential" ? "default" : "secondary"}
                        className="text-[10px]"
                      >
                        {opinion.status}
                      </Badge>
                      {!opinion.isIngested && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleIngest(opinion.id)}
                          disabled={ingestingId === opinion.id}
                          className="gap-1"
                          data-testid={`button-ingest-${opinion.id}`}
                        >
                          {ingestingId === opinion.id ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Download className="h-3 w-3" />
                          )}
                          Ingest
                        </Button>
                      )}
                      <a 
                        href={opinion.pdfUrl} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="p-2 hover:bg-muted rounded-md transition-colors"
                        data-testid={`link-pdf-${opinion.id}`}
                      >
                        <ExternalLink className="h-4 w-4 text-muted-foreground" />
                      </a>
                    </div>
                  </div>
                ))
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
