import { Database, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface SearchProgressProps {
  isSearching: boolean;
  className?: string;
}

export function SearchProgress({ isSearching, className }: SearchProgressProps) {
  if (!isSearching) return null;

  return (
    <div 
      className={cn("flex items-center gap-3 p-3 rounded-lg border bg-primary/10 border-primary/30", className)} 
      data-testid="search-progress"
    >
      <div className="text-primary animate-pulse">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
      <div className="flex items-center gap-2">
        <Database className="h-4 w-4 text-muted-foreground" />
        <span className="font-medium text-sm text-foreground">
          Searching legal database...
        </span>
      </div>
    </div>
  );
}
