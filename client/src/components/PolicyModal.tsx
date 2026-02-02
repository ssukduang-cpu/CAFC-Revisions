import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Scale, AlertTriangle, CheckCircle } from "lucide-react";

interface PolicyModalProps {
  open: boolean;
}

export function PolicyModal({ open }: PolicyModalProps) {
  const queryClient = useQueryClient();
  const [isAccepting, setIsAccepting] = useState(false);

  const acceptMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch("/api/auth/accept-policy", {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to accept policy");
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/auth/user"] });
    },
  });

  const handleAccept = async () => {
    setIsAccepting(true);
    try {
      await acceptMutation.mutateAsync();
    } finally {
      setIsAccepting(false);
    }
  };

  return (
    <Dialog open={open}>
      <DialogContent className="sm:max-w-[500px]" data-testid="policy-modal">
        <DialogHeader className="text-center">
          <div className="flex justify-center mb-4">
            <div className="p-3 bg-muted rounded-lg">
              <Scale className="h-8 w-8 text-foreground" />
            </div>
          </div>
          <DialogTitle className="text-xl font-semibold text-center">
            User Agreement
          </DialogTitle>
          <DialogDescription className="text-center text-muted-foreground">
            Please read and acknowledge the following before proceeding.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 mt-4">
          <div className="p-4 bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 rounded-lg">
            <div className="flex gap-3">
              <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
              <div>
                <h3 className="font-medium text-amber-900 dark:text-amber-200 mb-1">
                  This is an AI-assisted research tool, not legal advice.
                </h3>
                <p className="text-sm text-amber-800 dark:text-amber-300">
                  No attorney-client relationship is formed by using this application. The information provided should not be relied upon as a substitute for consultation with a licensed attorney.
                </p>
              </div>
            </div>
          </div>

          <div className="p-4 bg-muted/50 border rounded-lg">
            <div className="flex gap-3">
              <CheckCircle className="h-5 w-5 text-green-600 dark:text-green-400 flex-shrink-0 mt-0.5" />
              <div>
                <h3 className="font-medium mb-1">Verification Required</h3>
                <p className="text-sm text-muted-foreground">
                  AI-generated summaries and citations may contain errors. Always verify information against official court reporters and primary legal sources before relying on it for any legal matter.
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-6 space-y-3">
          <p className="text-xs text-center text-muted-foreground">
            By clicking "Confirm & Proceed," you acknowledge that you have read and understood these terms.
          </p>
          <Button
            onClick={handleAccept}
            className="w-full"
            disabled={isAccepting}
            data-testid="accept-policy-button"
          >
            {isAccepting ? "Processing..." : "Confirm & Proceed"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
