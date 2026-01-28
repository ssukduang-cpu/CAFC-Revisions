import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { 
  ArrowLeft, 
  Play, 
  RefreshCw, 
  CheckCircle, 
  XCircle, 
  Clock,
  Loader2,
  ChevronDown,
  ChevronRight
} from "lucide-react";
import { Link } from "wouter";

interface DoctrineBreakdown {
  count: number;
  avg_verified_rate: number;
  total_citations: number;
  verified_citations: number;
  unverified_citations: number;
  case_attr_unsupported: number;
  case_attr_total: number;
  case_attributed_unsupported_rate: number;
  avg_latency_ms: number;
}

interface EvalRunStatus {
  eval_run_id: string;
  status: string;
  mode: string;
  total_prompts: number;
  completed_prompts: number;
  failed_prompts: number;
  verification_rate: number | null;
  latency_p50: number | null;
  latency_p95: number | null;
  error_summary: string | null;
  created_at: string;
  by_doctrine: Record<string, DoctrineBreakdown> | null;
}

interface EvalResult {
  prompt_id: string;
  prompt_text: string;
  doctrine_tag: string;
  verified_rate: number;
  citations_total: number;
  citations_verified: number;
  citations_unverified: number;
  case_attributed_propositions: number;
  case_attributed_unsupported: number;
  failure_reason_counts: Record<string, number>;
  latency_ms: number;
  created_at: string;
}

interface EvalRun {
  id: string;
  status: string;
  mode: string;
  total_prompts: number;
  completed_prompts: number;
  failed_prompts: number;
  latency_p50: number | null;
  latency_p95: number | null;
  created_at: string;
}

export default function EvalDashboard() {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [activeRun, setActiveRun] = useState<EvalRunStatus | null>(null);
  const [results, setResults] = useState<EvalResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [promptCount, setPromptCount] = useState(50);
  const [mode, setMode] = useState("STRICT");
  const [expandedDoctrine, setExpandedDoctrine] = useState<string | null>(null);
  const [pollingActive, setPollingActive] = useState(false);

  const fetchRuns = useCallback(async () => {
    try {
      const response = await fetch("/api/internal/eval/runs?limit=10");
      if (response.ok) {
        const data = await response.json();
        setRuns(data.runs || []);
      }
    } catch (err) {
      console.error("Failed to fetch runs:", err);
    }
  }, []);

  const fetchStatus = useCallback(async (evalRunId: string) => {
    try {
      const response = await fetch(`/api/internal/eval/status?eval_run_id=${evalRunId}`);
      if (response.ok) {
        const data: EvalRunStatus = await response.json();
        setActiveRun(data);
        
        if (data.status === "RUNNING") {
          setPollingActive(true);
        } else {
          setPollingActive(false);
        }
        
        return data;
      }
    } catch (err) {
      console.error("Failed to fetch status:", err);
    }
    return null;
  }, []);

  const fetchResults = useCallback(async (evalRunId: string) => {
    try {
      const response = await fetch(`/api/internal/eval/results?eval_run_id=${evalRunId}&limit=200`);
      if (response.ok) {
        const data = await response.json();
        setResults(data.results || []);
      }
    } catch (err) {
      console.error("Failed to fetch results:", err);
    }
  }, []);

  const startEval = async () => {
    setStarting(true);
    try {
      const response = await fetch("/api/internal/eval/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ count: promptCount, mode })
      });
      
      if (response.ok) {
        const data = await response.json();
        setPollingActive(true);
        fetchStatus(data.eval_run_id);
        fetchRuns();
      }
    } catch (err) {
      console.error("Failed to start eval:", err);
    } finally {
      setStarting(false);
    }
  };

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  useEffect(() => {
    if (!pollingActive || !activeRun) return;
    
    const interval = setInterval(() => {
      fetchStatus(activeRun.eval_run_id);
      fetchResults(activeRun.eval_run_id);
    }, 3000);
    
    return () => clearInterval(interval);
  }, [pollingActive, activeRun, fetchStatus, fetchResults]);

  const selectRun = (run: EvalRun) => {
    fetchStatus(run.id);
    fetchResults(run.id);
  };

  const progress = activeRun ? 
    ((activeRun.completed_prompts + activeRun.failed_prompts) / activeRun.total_prompts) * 100 : 0;

  return (
    <div className="min-h-screen bg-background p-6" data-testid="eval-dashboard">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center gap-4 mb-6">
          <Link href="/">
            <Button variant="ghost" size="sm" data-testid="button-back">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back
            </Button>
          </Link>
          <h1 className="text-2xl font-bold">Evaluation Runner</h1>
          <Badge variant="outline">Internal</Badge>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  <span>Start New Evaluation</span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-4 items-end">
                  <div>
                    <label className="text-sm font-medium mb-2 block">Prompt Count</label>
                    <select 
                      value={promptCount} 
                      onChange={(e) => setPromptCount(Number(e.target.value))}
                      className="border rounded px-3 py-2 bg-background"
                      data-testid="select-prompt-count"
                    >
                      <option value={10}>10 (test)</option>
                      <option value={50}>50</option>
                      <option value={100}>100</option>
                      <option value={200}>200</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-2 block">Mode</label>
                    <select 
                      value={mode} 
                      onChange={(e) => setMode(e.target.value)}
                      className="border rounded px-3 py-2 bg-background"
                      data-testid="select-mode"
                    >
                      <option value="STRICT">STRICT</option>
                      <option value="RESEARCH">RESEARCH</option>
                    </select>
                  </div>
                  <Button 
                    onClick={startEval} 
                    disabled={starting || pollingActive}
                    data-testid="button-start-eval"
                  >
                    {starting ? (
                      <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Starting...</>
                    ) : (
                      <><Play className="h-4 w-4 mr-2" /> Start Evaluation</>
                    )}
                  </Button>
                </div>
              </CardContent>
            </Card>

            {activeRun && (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center justify-between">
                    <span>Current Run</span>
                    <Badge variant={
                      activeRun.status === "COMPLETE" ? "default" :
                      activeRun.status === "FAILED" ? "destructive" : "secondary"
                    }>
                      {activeRun.status === "RUNNING" && <Loader2 className="h-3 w-3 mr-1 animate-spin" />}
                      {activeRun.status}
                    </Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center gap-4">
                    <div className="flex-1">
                      <div className="flex justify-between text-sm mb-1">
                        <span>Progress</span>
                        <span>{activeRun.completed_prompts + activeRun.failed_prompts} / {activeRun.total_prompts}</span>
                      </div>
                      <Progress value={progress} className="h-2" data-testid="progress-bar" />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="text-center p-3 bg-muted/50 rounded">
                      <div className="text-2xl font-bold text-green-600">
                        {activeRun.completed_prompts}
                      </div>
                      <div className="text-xs text-muted-foreground">Completed</div>
                    </div>
                    <div className="text-center p-3 bg-muted/50 rounded">
                      <div className="text-2xl font-bold text-red-600">
                        {activeRun.failed_prompts}
                      </div>
                      <div className="text-xs text-muted-foreground">Failed</div>
                    </div>
                    <div className="text-center p-3 bg-muted/50 rounded">
                      <div className="text-2xl font-bold">
                        {activeRun.verification_rate?.toFixed(1) ?? "-"}%
                      </div>
                      <div className="text-xs text-muted-foreground">Verified Rate</div>
                    </div>
                    <div className="text-center p-3 bg-muted/50 rounded">
                      <div className="text-2xl font-bold">
                        {activeRun.latency_p50 ? (activeRun.latency_p50 / 1000).toFixed(1) : "-"}s
                      </div>
                      <div className="text-xs text-muted-foreground">p50 Latency</div>
                    </div>
                  </div>

                  {activeRun.error_summary && (
                    <div className="p-3 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded text-sm text-red-700 dark:text-red-300">
                      {activeRun.error_summary}
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            {activeRun?.by_doctrine && Object.keys(activeRun.by_doctrine).length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Results by Doctrine</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b">
                          <th className="text-left py-2 px-3">Doctrine</th>
                          <th className="text-right py-2 px-3">Queries</th>
                          <th className="text-right py-2 px-3">Verified Rate</th>
                          <th className="text-right py-2 px-3">Case Attr Unsup</th>
                          <th className="text-right py-2 px-3">Avg Latency</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(activeRun.by_doctrine).map(([doctrine, data]) => (
                          <tr key={doctrine} className="border-b hover:bg-muted/50">
                            <td className="py-2 px-3 font-medium">{doctrine}</td>
                            <td className="text-right py-2 px-3">{data.count}</td>
                            <td className="text-right py-2 px-3">
                              <span className={data.avg_verified_rate >= 90 ? "text-green-600" : "text-amber-600"}>
                                {data.avg_verified_rate?.toFixed(1)}%
                              </span>
                            </td>
                            <td className="text-right py-2 px-3">
                              <span className={data.case_attributed_unsupported_rate > 0.5 ? "text-red-600" : ""}>
                                {data.case_attributed_unsupported_rate?.toFixed(2)}%
                              </span>
                            </td>
                            <td className="text-right py-2 px-3">
                              {(data.avg_latency_ms / 1000).toFixed(1)}s
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}

            {results.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Individual Results ({results.length})</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2 max-h-96 overflow-y-auto">
                    {results.map((r) => (
                      <div 
                        key={r.prompt_id} 
                        className="p-3 border rounded hover:bg-muted/50 cursor-pointer"
                        onClick={() => setExpandedDoctrine(expandedDoctrine === r.prompt_id ? null : r.prompt_id)}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            {expandedDoctrine === r.prompt_id ? 
                              <ChevronDown className="h-4 w-4" /> : 
                              <ChevronRight className="h-4 w-4" />
                            }
                            <Badge variant="outline" className="text-xs">{r.doctrine_tag}</Badge>
                            <span className="text-sm truncate max-w-md">{r.prompt_text}</span>
                          </div>
                          <div className="flex items-center gap-3 text-sm">
                            <span className={r.verified_rate >= 90 ? "text-green-600" : "text-amber-600"}>
                              {r.verified_rate.toFixed(0)}%
                            </span>
                            <span className="text-muted-foreground">
                              {(r.latency_ms / 1000).toFixed(1)}s
                            </span>
                          </div>
                        </div>
                        {expandedDoctrine === r.prompt_id && (
                          <div className="mt-3 pt-3 border-t text-sm space-y-2">
                            <div className="grid grid-cols-3 gap-4">
                              <div>
                                <span className="text-muted-foreground">Citations:</span>{" "}
                                {r.citations_verified}/{r.citations_total}
                              </div>
                              <div>
                                <span className="text-muted-foreground">Case Attr:</span>{" "}
                                {r.case_attributed_propositions}
                              </div>
                              <div>
                                <span className="text-muted-foreground">Unsupported:</span>{" "}
                                {r.case_attributed_unsupported}
                              </div>
                            </div>
                            {Object.keys(r.failure_reason_counts).length > 0 && (
                              <div>
                                <span className="text-muted-foreground">Failures:</span>{" "}
                                {Object.entries(r.failure_reason_counts).map(([k, v]) => (
                                  <Badge key={k} variant="secondary" className="mr-1 text-xs">
                                    {k}: {v}
                                  </Badge>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  <span>Recent Runs</span>
                  <Button variant="ghost" size="sm" onClick={fetchRuns}>
                    <RefreshCw className="h-4 w-4" />
                  </Button>
                </CardTitle>
              </CardHeader>
              <CardContent>
                {runs.length === 0 ? (
                  <p className="text-muted-foreground text-sm">No evaluation runs yet.</p>
                ) : (
                  <div className="space-y-2">
                    {runs.map((run) => (
                      <div 
                        key={run.id}
                        className={`p-3 border rounded cursor-pointer hover:bg-muted/50 ${
                          activeRun?.eval_run_id === run.id ? "border-primary" : ""
                        }`}
                        onClick={() => selectRun(run)}
                        data-testid={`run-${run.id}`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <Badge variant={
                            run.status === "COMPLETE" ? "default" :
                            run.status === "FAILED" ? "destructive" : "secondary"
                          } className="text-xs">
                            {run.status === "RUNNING" && <Loader2 className="h-3 w-3 mr-1 animate-spin" />}
                            {run.status}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            {new Date(run.created_at).toLocaleString()}
                          </span>
                        </div>
                        <div className="text-sm">
                          <span className="font-medium">{run.completed_prompts}</span>
                          <span className="text-muted-foreground">/{run.total_prompts} prompts</span>
                        </div>
                        {run.latency_p50 && (
                          <div className="text-xs text-muted-foreground mt-1">
                            p50: {(run.latency_p50 / 1000).toFixed(1)}s • p95: {(run.latency_p95 ?? 0 / 1000).toFixed(1)}s
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Target Metrics</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="flex items-center justify-between">
                  <span>Verified Rate (STRICT)</span>
                  <span className="font-medium">≥ 90%</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Case-Attr Unsupported</span>
                  <span className="font-medium">≤ 0.5%</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>p95 Latency</span>
                  <span className="font-medium">≤ 30s</span>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
