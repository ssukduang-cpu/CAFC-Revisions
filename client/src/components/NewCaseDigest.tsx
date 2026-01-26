import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Sparkles, X, ExternalLink, Clock } from "lucide-react";
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
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  const [showAll, setShowAll] = useState(false);

  const recentIngests = data?.recent_ingests || [];
  const visibleIngests = recentIngests.filter(ingest => !dismissed.has(ingest.id));
  const displayIngests = showAll ? visibleIngests : visibleIngests.slice(0, 3);

  if (isLoading || visibleIngests.length === 0) {
    return null;
  }

  const formatTimeAgo = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return "just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
  };

  const handleDismiss = (id: number) => {
    setDismissed(prev => new Set([...prev, id]));
  };

  return (
    <div className={cn("rounded-lg border bg-gradient-to-r from-blue-50 to-purple-50 dark:from-blue-950/30 dark:to-purple-950/30 p-4", className)}>
      <div className="flex items-center gap-2 mb-3">
        <Sparkles className="h-4 w-4 text-blue-500" />
        <h3 className="font-semibold text-sm">New Case Digest</h3>
        <Badge variant="secondary" className="text-xs" data-testid="digest-count">
          {visibleIngests.length} new
        </Badge>
      </div>
      
      <div className="space-y-2">
        {displayIngests.map((ingest) => (
          <div
            key={ingest.id}
            className="flex items-start justify-between gap-2 p-2 rounded-md bg-white/50 dark:bg-gray-800/50"
            data-testid={`digest-case-${ingest.id}`}
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span 
                  className="font-medium text-sm truncate cursor-pointer hover:text-blue-600 hover:underline"
                  onClick={() => onCaseClick?.(ingest.document_id, ingest.case_name)}
                  data-testid={`digest-case-link-${ingest.id}`}
                >
                  {ingest.case_name}
                </span>
                <Badge variant="outline" className="text-xs shrink-0 bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                  Web Search
                </Badge>
              </div>
              <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                <Clock className="h-3 w-3" />
                <span>{formatTimeAgo(ingest.ingested_at)}</span>
                {ingest.search_query && (
                  <>
                    <span>·</span>
                    <span className="truncate">from: "{ingest.search_query.slice(0, 30)}..."</span>
                  </>
                )}
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 shrink-0"
              onClick={() => handleDismiss(ingest.id)}
              data-testid={`digest-dismiss-${ingest.id}`}
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        ))}
      </div>

      {visibleIngests.length > 3 && (
        <Button
          variant="link"
          size="sm"
          className="mt-2 h-auto p-0 text-xs"
          onClick={() => setShowAll(!showAll)}
          data-testid="digest-show-more"
        >
          {showAll ? "Show less" : `Show ${visibleIngests.length - 3} more`}
        </Button>
      )}
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
