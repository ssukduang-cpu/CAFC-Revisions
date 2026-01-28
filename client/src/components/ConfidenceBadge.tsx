import { cn } from "@/lib/utils";
import { Shield, ShieldAlert, ShieldCheck, ShieldQuestion, AlertTriangle } from "lucide-react";
import type { ConfidenceTier, CitationSignal } from "@/lib/api";

interface ConfidenceBadgeProps {
  tier: ConfidenceTier;
  signals?: CitationSignal[];
  showLabel?: boolean;
  size?: "sm" | "md";
  className?: string;
}

const tierConfig = {
  strong: {
    label: "Strong",
    icon: ShieldCheck,
    bgColor: "bg-green-500/20",
    textColor: "text-green-700 dark:text-green-400",
    borderColor: "border-green-500/30",
    description: "Verified holding from cited case"
  },
  moderate: {
    label: "Moderate",
    icon: Shield,
    bgColor: "bg-yellow-500/20",
    textColor: "text-yellow-700 dark:text-yellow-400",
    borderColor: "border-yellow-500/30",
    description: "Verified but may have limitations"
  },
  weak: {
    label: "Weak",
    icon: ShieldAlert,
    bgColor: "bg-orange-500/20",
    textColor: "text-orange-700 dark:text-orange-400",
    borderColor: "border-orange-500/30",
    description: "Limited or tangential support"
  },
  unverified: {
    label: "Unverified",
    icon: ShieldQuestion,
    bgColor: "bg-red-500/20",
    textColor: "text-red-700 dark:text-red-400",
    borderColor: "border-red-500/30",
    description: "Could not verify against source"
  }
};

const signalLabels: Record<CitationSignal, string> = {
  case_bound: "Case verified",
  exact_match: "Exact quote match",
  partial_match: "Partial match",
  fuzzy_case_binding: "Fuzzy case match",
  binding_failed: "Binding failed",
  unverified: "Not verified",
  recent: "Recent case (2020+)",
  holding_heuristic: "Likely holding",
  dicta_heuristic: "Likely dicta",
  concurrence_heuristic: "From concurrence",
  dissent_heuristic: "From dissent",
  ellipsis_in_quote: "Quote contains ellipsis",
  db_fetched: "Fetched from database",
  no_case_name: "Missing case name"
};

const warningSignals: CitationSignal[] = [
  'dicta_heuristic',
  'concurrence_heuristic', 
  'dissent_heuristic',
  'fuzzy_case_binding',
  'partial_match',
  'binding_failed'
];

export function ConfidenceBadge({ 
  tier, 
  signals = [], 
  showLabel = false,
  size = "sm",
  className 
}: ConfidenceBadgeProps) {
  const config = tierConfig[tier] || tierConfig.unverified;
  const Icon = config.icon;
  
  const hasWarningSignal = signals.some(s => warningSignals.includes(s));
  
  const sizeClasses = size === "sm" 
    ? "h-4 w-4 text-[10px] px-1 py-0.5" 
    : "h-5 w-5 text-xs px-1.5 py-0.5";
  
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1 rounded border",
        config.bgColor,
        config.textColor,
        config.borderColor,
        sizeClasses,
        className
      )}
      title={`${config.label}: ${config.description}${signals.length > 0 ? `\nSignals: ${signals.map(s => signalLabels[s] || s).join(', ')}` : ''}`}
      data-testid={`badge-confidence-${tier}`}
    >
      <Icon className={size === "sm" ? "h-3 w-3" : "h-4 w-4"} />
      {showLabel && <span className="font-medium">{config.label}</span>}
      {hasWarningSignal && <AlertTriangle className={size === "sm" ? "h-2.5 w-2.5" : "h-3 w-3"} />}
    </div>
  );
}

interface SignalsListProps {
  signals: CitationSignal[];
  className?: string;
}

export function SignalsList({ signals, className }: SignalsListProps) {
  if (!signals || signals.length === 0) return null;
  
  return (
    <div className={cn("flex flex-wrap gap-1", className)}>
      {signals.map((signal, idx) => {
        const isWarning = warningSignals.includes(signal);
        return (
          <span
            key={idx}
            className={cn(
              "text-[10px] px-1.5 py-0.5 rounded",
              isWarning 
                ? "bg-orange-500/10 text-orange-600 dark:text-orange-400" 
                : "bg-muted text-muted-foreground"
            )}
            data-testid={`signal-${signal}`}
          >
            {signalLabels[signal] || signal}
          </span>
        );
      })}
    </div>
  );
}
