import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { HelpCircle, Shield, AlertTriangle, CheckCircle, XCircle, Info } from "lucide-react";

export function HelpModal() {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button 
          variant="ghost" 
          size="sm" 
          className="gap-1.5 h-7 px-2 text-sidebar-foreground/60 hover:text-sidebar-foreground"
          data-testid="button-help"
        >
          <HelpCircle className="h-3.5 w-3.5" />
          <span className="text-xs">Help</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Info className="h-5 w-5 text-primary" />
            How to Read Citations
          </DialogTitle>
        </DialogHeader>
        
        <div className="space-y-4 text-sm">
          <p className="text-muted-foreground">
            This assistant provides citation-backed answers from Federal Circuit opinions. 
            Each citation is verified against the source text to ensure accuracy. 
            Color-coded badges indicate the reliability of each citation.
          </p>
          
          <div className="space-y-3">
            <h4 className="font-semibold">Citation Confidence Tiers</h4>
            
            <div className="space-y-2">
              <div className="flex items-start gap-3 p-2 rounded-lg bg-green-500/10 border border-green-500/20">
                <CheckCircle className="h-4 w-4 text-green-600 mt-0.5 shrink-0" />
                <div>
                  <span className="font-medium text-green-700 dark:text-green-400">STRONG</span>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Quote verified as exact match in the claimed opinion. High confidence.
                  </p>
                </div>
              </div>
              
              <div className="flex items-start gap-3 p-2 rounded-lg bg-blue-500/10 border border-blue-500/20">
                <CheckCircle className="h-4 w-4 text-blue-600 mt-0.5 shrink-0" />
                <div>
                  <span className="font-medium text-blue-700 dark:text-blue-400">MODERATE</span>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Quote verified with fuzzy case-name matching. Reasonable confidence.
                  </p>
                </div>
              </div>
              
              <div className="flex items-start gap-3 p-2 rounded-lg bg-yellow-500/10 border border-yellow-500/20">
                <AlertTriangle className="h-4 w-4 text-yellow-600 mt-0.5 shrink-0" />
                <div>
                  <span className="font-medium text-yellow-700 dark:text-yellow-400">WEAK</span>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Quote found in context but with lower verification confidence. Use with caution.
                  </p>
                </div>
              </div>
              
              <div className="flex items-start gap-3 p-2 rounded-lg bg-red-500/10 border border-red-500/20">
                <XCircle className="h-4 w-4 text-red-600 mt-0.5 shrink-0" />
                <div>
                  <span className="font-medium text-red-700 dark:text-red-400">UNVERIFIED</span>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Quote could not be verified in the source text. Do not rely on this citation without manual verification.
                  </p>
                </div>
              </div>
            </div>
          </div>
          
          <div className="space-y-2">
            <h4 className="font-semibold flex items-center gap-2">
              <Shield className="h-4 w-4 text-green-600" />
              Attorney Mode
            </h4>
            <p className="text-muted-foreground text-xs">
              When enabled (default), statements that cannot be verified against source text 
              are flagged with a warning notice below the response. 
              This ensures you can identify which claims require additional verification 
              before use in legal proceedings.
            </p>
          </div>
          
          <div className="space-y-2">
            <h4 className="font-semibold">Controlling Authorities Panel</h4>
            <p className="text-muted-foreground text-xs">
              For doctrine-specific queries, the sources panel displays relevant SCOTUS and 
              en banc CAFC precedent that controls the legal issue. These are surfaced 
              automatically based on the query classification.
            </p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
