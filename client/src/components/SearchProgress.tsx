import { useState, useEffect } from "react";
import { Database, Globe, CheckCircle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

type StageStatus = "pending" | "loading" | "done";

interface LoadingStepProps {
  label: string;
  icon: React.ReactNode;
  status: StageStatus;
}

function LoadingStep({ label, icon, status }: LoadingStepProps) {
  const isDone = status === "done";
  const isLoading = status === "loading";

  return (
    <div
      className={cn(
        "flex items-center gap-3 p-3 rounded-lg border transition-all duration-300",
        isDone
          ? "bg-green-500/10 border-green-500/30"
          : isLoading
          ? "bg-primary/10 border-primary/30"
          : "bg-muted/50 border-border/50"
      )}
      data-testid={`search-stage-${label.toLowerCase().replace(/\s+/g, "-")}`}
    >
      <div
        className={cn(
          "transition-colors",
          isDone
            ? "text-green-500"
            : isLoading
            ? "text-primary animate-pulse"
            : "text-muted-foreground/50"
        )}
      >
        {isDone ? (
          <CheckCircle className="h-5 w-5" />
        ) : isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin" />
        ) : (
          icon
        )}
      </div>
      <span
        className={cn(
          "font-medium text-sm transition-colors",
          isDone
            ? "text-green-600 dark:text-green-400"
            : isLoading
            ? "text-foreground"
            : "text-muted-foreground/60"
        )}
      >
        {label}
      </span>
    </div>
  );
}

interface SearchProgressProps {
  isSearching: boolean;
  className?: string;
}

export function SearchProgress({ isSearching, className }: SearchProgressProps) {
  const [stages, setStages] = useState<{
    local: StageStatus;
    web: StageStatus;
  }>({
    local: "pending",
    web: "pending",
  });

  useEffect(() => {
    if (!isSearching) {
      setStages({ local: "pending", web: "pending" });
      return;
    }

    setStages({ local: "loading", web: "pending" });

    const localDoneTimer = setTimeout(() => {
      setStages({ local: "done", web: "loading" });
    }, 2000);

    const webDoneTimer = setTimeout(() => {
      setStages({ local: "done", web: "done" });
    }, 6000);

    return () => {
      clearTimeout(localDoneTimer);
      clearTimeout(webDoneTimer);
    };
  }, [isSearching]);

  if (!isSearching) return null;

  return (
    <div className={cn("grid grid-cols-2 gap-3", className)} data-testid="search-progress">
      <LoadingStep
        label="Local Repository"
        icon={<Database className="h-5 w-5" />}
        status={stages.local}
      />
      <LoadingStep
        label="Legal Web Search"
        icon={<Globe className="h-5 w-5" />}
        status={stages.web}
      />
    </div>
  );
}
