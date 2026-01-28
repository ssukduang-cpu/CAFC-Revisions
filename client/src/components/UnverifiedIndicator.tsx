import { AlertTriangle } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

interface UnverifiedIndicatorProps {
  mentionedCases?: string[];
  className?: string;
}

export function UnverifiedIndicator({ mentionedCases = [], className = "" }: UnverifiedIndicatorProps) {
  const casesList = mentionedCases.length > 0 
    ? mentionedCases.slice(0, 3).join(", ") + (mentionedCases.length > 3 ? "..." : "")
    : "";

  return (
    <TooltipProvider>
      <Tooltip delayDuration={200}>
        <TooltipTrigger asChild>
          <span 
            className={`inline-flex items-center ml-1 cursor-help ${className}`}
            data-testid="unverified-indicator"
          >
            <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs">
          <p className="text-xs">
            Could not verify in source documents
            {casesList && (
              <span className="block text-muted-foreground mt-1">
                Referenced: {casesList}
              </span>
            )}
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
