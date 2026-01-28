import { Link } from "wouter";
import { ArrowLeft, Shield, ShieldCheck, ShieldAlert, ShieldQuestion, AlertTriangle, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function CitationGuide() {
  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-3xl mx-auto px-4 py-8">
        <Link href="/">
          <Button variant="ghost" size="sm" className="mb-6" data-testid="link-back-home">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Assistant
          </Button>
        </Link>

        <h1 className="text-2xl font-bold mb-2" data-testid="text-guide-title">Understanding Citation Confidence</h1>
        <p className="text-muted-foreground mb-8">
          This guide explains how the system verifies citations and what the confidence indicators mean.
        </p>

        <section className="mb-10">
          <h2 className="text-xl font-semibold mb-4">Confidence Tiers</h2>
          <p className="text-muted-foreground mb-4">
            Every citation is assigned a confidence tier based on how well it can be verified against the source case.
          </p>
          
          <div className="space-y-3">
            <Card className="border-green-500/30 bg-green-500/5">
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <ShieldCheck className="h-5 w-5 text-green-600" />
                  <span className="text-green-700 dark:text-green-400">Strong (Score 70+)</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                The quote was found verbatim in the claimed case. The citation is verified with high confidence.
              </CardContent>
            </Card>

            <Card className="border-yellow-500/30 bg-yellow-500/5">
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Shield className="h-5 w-5 text-yellow-600" />
                  <span className="text-yellow-700 dark:text-yellow-400">Moderate (Score 50-69)</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                The quote was verified but with some limitations. This may occur when the case was matched by name rather than unique ID, or when the quote is a partial match.
              </CardContent>
            </Card>

            <Card className="border-orange-500/30 bg-orange-500/5">
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <ShieldAlert className="h-5 w-5 text-orange-600" />
                  <span className="text-orange-700 dark:text-orange-400">Weak (Score 30-49)</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                The citation has limited support. The quote may be from dicta, a concurrence, or have other factors reducing reliability. Use with caution.
              </CardContent>
            </Card>

            <Card className="border-red-500/30 bg-red-500/5">
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <ShieldQuestion className="h-5 w-5 text-red-600" />
                  <span className="text-red-700 dark:text-red-400">Unverified (Score &lt;30)</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                The system could not verify this citation against the claimed case. The quote may not exist in the opinion, or may have been attributed to the wrong case. Do not rely on this citation without independent verification.
              </CardContent>
            </Card>
          </div>
        </section>

        <section className="mb-10">
          <h2 className="text-xl font-semibold mb-4">Signals</h2>
          <p className="text-muted-foreground mb-4">
            Signals provide additional context about how a citation was verified. Signals ending in "_heuristic" indicate automated detection that should be independently confirmed.
          </p>
          
          <div className="grid gap-2">
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30">
              <div className="text-xs font-medium px-2 py-1 rounded bg-green-500/10 text-green-600">case_bound</div>
              <p className="text-sm text-muted-foreground">Quote verified in the specific claimed case by unique ID.</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30">
              <div className="text-xs font-medium px-2 py-1 rounded bg-green-500/10 text-green-600">exact_match</div>
              <p className="text-sm text-muted-foreground">The quote matches the source text exactly.</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30">
              <div className="text-xs font-medium px-2 py-1 rounded bg-yellow-500/10 text-yellow-600">fuzzy_case_binding</div>
              <p className="text-sm text-muted-foreground">Case matched by name rather than unique ID. Confidence capped at Moderate.</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30">
              <div className="text-xs font-medium px-2 py-1 rounded bg-yellow-500/10 text-yellow-600">partial_match</div>
              <p className="text-sm text-muted-foreground">Quote partially matches the source. Some text may differ.</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30">
              <div className="text-xs font-medium px-2 py-1 rounded bg-red-500/10 text-red-600">binding_failed</div>
              <p className="text-sm text-muted-foreground">Could not verify quote in the claimed case.</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30">
              <div className="text-xs font-medium px-2 py-1 rounded bg-blue-500/10 text-blue-600">holding_heuristic</div>
              <p className="text-sm text-muted-foreground">Detected language suggesting this is from the court's holding.</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30">
              <div className="text-xs font-medium px-2 py-1 rounded bg-orange-500/10 text-orange-600">dicta_heuristic</div>
              <p className="text-sm text-muted-foreground">Detected language suggesting this may be dicta (non-binding).</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30">
              <div className="text-xs font-medium px-2 py-1 rounded bg-orange-500/10 text-orange-600">concurrence_heuristic</div>
              <p className="text-sm text-muted-foreground">Quote may be from a concurring opinion, not the majority.</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30">
              <div className="text-xs font-medium px-2 py-1 rounded bg-orange-500/10 text-orange-600">dissent_heuristic</div>
              <p className="text-sm text-muted-foreground">Quote may be from a dissenting opinion, not the majority.</p>
            </div>
          </div>
        </section>

        <section className="mb-10">
          <h2 className="text-xl font-semibold mb-4">How Scoring Works</h2>
          <p className="text-muted-foreground mb-4">
            The confidence score (0-100) is calculated from multiple factors:
          </p>
          
          <Card>
            <CardContent className="pt-4">
              <ul className="space-y-2 text-sm">
                <li className="flex justify-between">
                  <span>Strict case binding (by unique ID)</span>
                  <span className="font-mono text-green-600">+40 points</span>
                </li>
                <li className="flex justify-between">
                  <span>Fuzzy case binding (by name match)</span>
                  <span className="font-mono text-yellow-600">+25 points</span>
                </li>
                <li className="flex justify-between">
                  <span>Exact quote match</span>
                  <span className="font-mono text-green-600">+30 points</span>
                </li>
                <li className="flex justify-between">
                  <span>Partial quote match</span>
                  <span className="font-mono text-yellow-600">+15 points</span>
                </li>
                <li className="flex justify-between">
                  <span>Recent case (2020 or later)</span>
                  <span className="font-mono text-blue-600">+10 points</span>
                </li>
                <li className="flex justify-between">
                  <span>From holding section</span>
                  <span className="font-mono text-green-600">+15 points</span>
                </li>
                <li className="flex justify-between">
                  <span>From dicta/concurrence/dissent</span>
                  <span className="font-mono text-orange-600">-5 to -15 points</span>
                </li>
              </ul>
            </CardContent>
          </Card>
        </section>

        <section className="mb-10">
          <h2 className="text-xl font-semibold mb-4">Limitations</h2>
          
          <Card className="border-orange-500/30">
            <CardContent className="pt-4">
              <div className="flex gap-3">
                <AlertTriangle className="h-5 w-5 text-orange-500 flex-shrink-0 mt-0.5" />
                <div className="space-y-3 text-sm text-muted-foreground">
                  <p><strong>This is not legal advice.</strong> The confidence system is a research aid, not a substitute for professional judgment.</p>
                  <p><strong>Heuristic signals are estimates.</strong> Detection of holdings, dicta, and opinion types uses pattern matching that may be incorrect. Always verify against the original opinion.</p>
                  <p><strong>PDF quality affects accuracy.</strong> Some older opinions may have OCR errors that prevent proper quote matching.</p>
                  <p><strong>Not all cases are indexed.</strong> The system only searches opinions that have been ingested. A "not found" result doesn't mean the case doesn't exist.</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </section>

        <section className="mb-10">
          <h2 className="text-xl font-semibold mb-4">Recommended Workflow</h2>
          
          <ol className="space-y-4 text-sm">
            <li className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center font-medium">1</span>
              <div>
                <p className="font-medium">Review the confidence tier</p>
                <p className="text-muted-foreground">Strong citations are generally reliable. Moderate or lower tiers require additional scrutiny.</p>
              </div>
            </li>
            <li className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center font-medium">2</span>
              <div>
                <p className="font-medium">Check the signals</p>
                <p className="text-muted-foreground">Look for warning signals like fuzzy_case_binding, dicta_heuristic, or dissent_heuristic.</p>
              </div>
            </li>
            <li className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center font-medium">3</span>
              <div>
                <p className="font-medium">Click to view the source</p>
                <p className="text-muted-foreground">Each citation links to the specific page in the opinion PDF where the quote appears.</p>
              </div>
            </li>
            <li className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center font-medium">4</span>
              <div>
                <p className="font-medium">Verify independently</p>
                <p className="text-muted-foreground">For anything you cite in a filing, confirm the quote and context in the original opinion.</p>
              </div>
            </li>
          </ol>
        </section>

        <div className="border-t pt-6">
          <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/30">
            <Info className="h-5 w-5 text-primary flex-shrink-0 mt-0.5" />
            <p className="text-sm text-muted-foreground">
              The citation confidence system is designed to prevent misattribution by verifying that quotes actually appear in the claimed cases. When verification fails, citations are flagged as Unverified rather than silently corrected.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
