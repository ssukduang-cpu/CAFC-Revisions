import { useState, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Sparkles, X, CheckCircle } from "lucide-react";
import { cn } from "@/lib/utils";

interface WebSearchIngest {
  id: number;
  case_name: string;
  cluster_id: number;
  search_query: string;
  ingested_at: string;
  document_id: string;
}

interface DigestResponse {
  success: boolean;
  recent_ingests: WebSearchIngest[];
}

const DISMISSED_KEY = "dismissed_case_digests";
const AUTO_DISMISS_DELAY = 8000;

function getDismissedIds(): Set<number> {
  if (typeof window === 'undefined') return new Set();
  try {
    const stored = localStorage.getItem(DISMISSED_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      return new Set(parsed);
    }
  } catch {
    // ignore parse errors
  }
  return new Set();
}

function saveDismissedIds(ids: Set<number>) {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(DISMISSED_KEY, JSON.stringify(Array.from(ids)));
  } catch {
    // ignore storage errors
  }
}

export function useRecentDigest() {
  return useQuery<DigestResponse>({
    queryKey: ["digest", "recent"],
    queryFn: async () => {
      const response = await fetch("/api/digest/recent");
      if (!response.ok) throw new Error("Failed to fetch digest");
      return response.json();
    },
    refetchInterval: 30000,
    staleTime: 10000,
  });
}

interface NewCaseDigestProps {
  className?: string;
  onCaseClick?: (documentId: string, caseName: string) => void;
}

export function NewCaseDigest({ className, onCaseClick }: NewCaseDigestProps) {
  const { data, isLoading } = useRecentDigest();
  const [dismissed, setDismissed] = useState<Set<number>>(() => getDismissedIds());
  const [manuallyHidden, setManuallyHidden] = useState(false);

  const recentIngests = data?.recent_ingests || [];
  const visibleIngests = recentIngests.filter(ingest => !dismissed.has(ingest.id));
  const latestIngest = visibleIngests[0];

  const handleDismiss = useCallback(() => {
    if (visibleIngests.length > 0) {
      const allIds = [...Array.from(dismissed), ...visibleIngests.map(i => i.id)];
      const newDismissed = new Set(allIds);
      setDismissed(newDismissed);
      saveDismissedIds(newDismissed);
    }
    setManuallyHidden(true);
  }, [dismissed, visibleIngests]);

  // Auto-dismiss after delay - only runs once per unique latestIngest
  useEffect(() => {
    if (latestIngest && !manuallyHidden) {
      const timer = setTimeout(() => {
        handleDismiss();
      }, AUTO_DISMISS_DELAY);
      return () => clearTimeout(timer);
    }
  }, [latestIngest?.id]);

  // Reset manual hide when new cases arrive
  useEffect(() => {
    if (latestIngest && !dismissed.has(latestIngest.id)) {
      setManuallyHidden(false);
    }
  }, [latestIngest?.id, dismissed]);

  if (isLoading || manuallyHidden || visibleIngests.length === 0 || !latestIngest) {
    return null;
  }

  return (
    <div 
      className={cn(
        "flex items-center gap-3 p-2.5 rounded-lg border bg-gradient-to-r from-green-50 to-emerald-50 dark:from-green-950/30 dark:to-emerald-950/30 border-green-200 dark:border-green-800/50 animate-in slide-in-from-bottom-2 duration-300",
        className
      )}
      data-testid="new-case-digest"
    >
      <div className="flex items-center justify-center h-7 w-7 rounded-full bg-green-100 dark:bg-green-900/50 shrink-0">
        <CheckCircle className="h-4 w-4 text-green-600 dark:text-green-400" />
      </div>
      
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-green-800 dark:text-green-300">
            Case Added
          </span>
          {visibleIngests.length > 1 && (
            <Badge variant="secondary" className="text-[10px] h-4 px-1.5" data-testid="digest-count">
              +{visibleIngests.length - 1} more
            </Badge>
          )}
        </div>
        <button
          className="text-sm font-medium text-foreground truncate block hover:underline cursor-pointer max-w-[180px]"
          onClick={() => onCaseClick?.(latestIngest.document_id, latestIngest.case_name)}
          title={latestIngest.case_name}
          data-testid={`digest-case-link-${latestIngest.id}`}
        >
          {latestIngest.case_name.length > 25 
            ? latestIngest.case_name.slice(0, 25) + "..." 
            : latestIngest.case_name}
        </button>
      </div>

      <Button
        variant="ghost"
        size="icon"
        className="h-6 w-6 shrink-0 text-muted-foreground hover:text-foreground"
        onClick={handleDismiss}
        data-testid="digest-dismiss"
      >
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

interface SourceVerifiedBadgeProps {
  isWebSearchSource?: boolean;
  className?: string;
}

export function SourceVerifiedBadge({ isWebSearchSource, className }: SourceVerifiedBadgeProps) {
  if (!isWebSearchSource) return null;
  
  return (
    <Badge 
      variant="outline" 
      className={cn("text-xs bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400", className)}
      data-testid="source-verified-badge"
    >
      <Sparkles className="h-3 w-3 mr-1" />
      Web Discovered
    </Badge>
  );
}
