import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ArrowLeft, AlertTriangle, CheckCircle, XCircle, RefreshCw, ChevronDown, ChevronRight, Shield, ShieldOff } from "lucide-react";
import { Link } from "wouter";

interface LatencyMetrics {
  p50_ms: number;
  p95_ms: number;
  avg_ms: number;
}

interface PropositionMetrics {
  total: number;
  case_attributed: number;
  unsupported: number;
  case_attributed_unsupported: number;
  unsupported_rate: number;
  case_attributed_unsupported_rate: number;
}

interface DoctrineMetrics {
  doctrine: string;
  verification_rate: number;
  total_queries: number;
  total_citations: number;
  verified_citations: number;
  unverified_citations: number;
  unsupported_rate: number;
  case_attributed_unsupported_rate: number;
  avg_latency_ms: number;
  alert: boolean;
  alert_reasons: string[];
}

interface FailureReason {
  reason: string;
  count: number;
  percentage: number;
}

interface DashboardData {
  mode: string;
  overall_verification_rate: number;
  overall_unverified_rate: number;
  total_queries: number;
  total_citations: number;
  verified_citations: number;
  unverified_citations: number;
  latency: LatencyMetrics;
  propositions: PropositionMetrics;
  by_doctrine: DoctrineMetrics[];
  failure_reasons: FailureReason[];
  alerts: string[];
  period_start: string;
  period_end: string;
}

interface DrilldownData {
  doctrine: string;
  failure_reasons: FailureReason[];
  failing_responses: Array<{
    response_id: string;
    created_at: string;
    total_citations: number;
    verified_citations: number;
  }>;
  total_failures: number;
}

export default function TelemetryDashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(7);
  const [mode, setMode] = useState<string>("STRICT");
  const [expandedDoctrine, setExpandedDoctrine] = useState<string | null>(null);
  const [drilldownData, setDrilldownData] = useState<DrilldownData | null>(null);
  const [drilldownLoading, setDrilldownLoading] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const modeParam = mode ? `&mode=${mode}` : "";
      const response = await fetch(`/api/telemetry/dashboard?days=${days}${modeParam}`);
      if (!response.ok) throw new Error("Failed to fetch telemetry data");
      const result = await response.json();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  const fetchDrilldown = async (doctrine: string) => {
    if (expandedDoctrine === doctrine) {
      setExpandedDoctrine(null);
      setDrilldownData(null);
      return;
    }
    
    setDrilldownLoading(true);
    setExpandedDoctrine(doctrine);
    try {
      const modeParam = mode ? `&mode=${mode}` : "";
      const response = await fetch(`/api/telemetry/drilldown/${encodeURIComponent(doctrine)}?days=${days}${modeParam}`);
      if (!response.ok) throw new Error("Failed to fetch drilldown");
      const result = await response.json();
      setDrilldownData(result);
    } catch (err) {
      console.error("Drilldown error:", err);
    } finally {
      setDrilldownLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [days, mode]);

  const getVerificationColor = (rate: number) => {
    if (rate >= 90) return "text-green-600 dark:text-green-400";
    if (rate >= 80) return "text-yellow-600 dark:text-yellow-400";
    if (rate >= 70) return "text-orange-600 dark:text-orange-400";
    return "text-red-600 dark:text-red-400";
  };

  const getVerificationBadge = (rate: number) => {
    if (rate >= 90) return <Badge className="bg-green-500">Excellent</Badge>;
    if (rate >= 80) return <Badge className="bg-yellow-500">Good</Badge>;
    if (rate >= 70) return <Badge className="bg-orange-500">Needs Work</Badge>;
    return <Badge variant="destructive">Critical</Badge>;
  };

  const formatLatency = (ms: number) => {
    if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
    return `${ms.toFixed(0)}ms`;
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-background p-6" data-testid="telemetry-loading">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-muted rounded w-1/4"></div>
          <div className="grid grid-cols-4 gap-4">
            {[1, 2, 3, 4].map(i => (
              <div key={i} className="h-32 bg-muted rounded"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-background p-6" data-testid="telemetry-error">
        <Card className="border-destructive">
          <CardContent className="p-6">
            <div className="flex items-center gap-2 text-destructive">
              <XCircle className="h-5 w-5" />
              <span>Error loading telemetry: {error}</span>
            </div>
            <Button onClick={fetchData} className="mt-4">Retry</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background p-6" data-testid="telemetry-dashboard">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div className="flex items-center gap-4">
            <Link href="/">
              <Button variant="ghost" size="sm" data-testid="back-button">
                <ArrowLeft className="h-4 w-4 mr-2" />
                Back to Chat
              </Button>
            </Link>
            <h1 className="text-2xl font-bold">Citation Verification Dashboard</h1>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 border rounded-lg p-1">
              <Button
                variant={mode === "STRICT" ? "default" : "ghost"}
                size="sm"
                onClick={() => setMode("STRICT")}
                className="gap-1"
                data-testid="mode-strict"
              >
                <Shield className="h-4 w-4" />
                STRICT
              </Button>
              <Button
                variant={mode === "RESEARCH" ? "default" : "ghost"}
                size="sm"
                onClick={() => setMode("RESEARCH")}
                className="gap-1"
                data-testid="mode-research"
              >
                <ShieldOff className="h-4 w-4" />
                RESEARCH
              </Button>
            </div>
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="border rounded px-3 py-2 bg-background"
              data-testid="days-select"
            >
              <option value={1}>Last 24 hours</option>
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
            </select>
            <Button variant="outline" onClick={fetchData} data-testid="refresh-button">
              <RefreshCw className="h-4 w-4 mr-2" />
              Refresh
            </Button>
          </div>
        </div>

        {data?.alerts && data.alerts.length > 0 && (
          <Card className="border-yellow-500 bg-yellow-50 dark:bg-yellow-900/20" data-testid="alerts-card">
            <CardContent className="p-4">
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-5 w-5 text-yellow-600 mt-0.5" />
                <div>
                  <h3 className="font-semibold text-yellow-800 dark:text-yellow-200">Risk Alerts</h3>
                  <ul className="text-sm text-yellow-700 dark:text-yellow-300 mt-1 space-y-1">
                    {data.alerts.map((alert, i) => (
                      <li key={i}>{alert}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <Card data-testid="overall-rate-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Verified Rate ({mode})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className={`text-3xl font-bold ${getVerificationColor(data?.overall_verification_rate || 0)}`}>
                {data?.overall_verification_rate?.toFixed(1)}%
              </div>
              <div className="mt-2">
                {getVerificationBadge(data?.overall_verification_rate || 0)}
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                Target: ≥90% in STRICT mode
              </p>
            </CardContent>
          </Card>

          <Card data-testid="case-attributed-unsupported-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Case-Attributed Unsupported
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className={`text-3xl font-bold ${(data?.propositions.case_attributed_unsupported_rate || 0) > 0.5 ? "text-red-600" : "text-green-600"}`}>
                {data?.propositions.case_attributed_unsupported_rate?.toFixed(2)}%
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                Target: ≤0.5% in STRICT mode
              </p>
              <p className="text-xs mt-1">
                {data?.propositions.case_attributed_unsupported || 0} / {data?.propositions.case_attributed || 0} propositions
              </p>
            </CardContent>
          </Card>

          <Card data-testid="latency-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Latency (p50 / p95)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">
                {formatLatency(data?.latency.p50_ms || 0)} / {formatLatency(data?.latency.p95_ms || 0)}
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                Avg: {formatLatency(data?.latency.avg_ms || 0)}
              </p>
            </CardContent>
          </Card>

          <Card data-testid="citations-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Citations Verified
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">
                {data?.verified_citations || 0} / {data?.total_citations || 0}
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                {data?.total_queries || 0} queries total
              </p>
            </CardContent>
          </Card>
        </div>

        {data?.failure_reasons && data.failure_reasons.length > 0 && (
          <Card data-testid="failure-reasons-card">
            <CardHeader>
              <CardTitle>Failure Reason Breakdown</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {data.failure_reasons.map((fr, i) => (
                  <div key={i} className="border rounded p-3">
                    <p className="text-xs font-mono text-muted-foreground">{fr.reason}</p>
                    <p className="text-lg font-bold">{fr.count}</p>
                    <p className="text-xs text-muted-foreground">{fr.percentage.toFixed(1)}%</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        <Card data-testid="doctrine-breakdown-card">
          <CardHeader>
            <CardTitle>Verification by Doctrine</CardTitle>
          </CardHeader>
          <CardContent>
            {data?.by_doctrine && data.by_doctrine.length > 0 ? (
              <div className="space-y-2">
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b text-sm">
                        <th className="text-left py-2 px-2"></th>
                        <th className="text-left py-2 px-2">Doctrine</th>
                        <th className="text-right py-2 px-2">Verified Rate</th>
                        <th className="text-right py-2 px-2">Case-Attr Unsup</th>
                        <th className="text-right py-2 px-2">Citations</th>
                        <th className="text-right py-2 px-2">Latency</th>
                        <th className="text-center py-2 px-2">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.by_doctrine.map((doc, i) => (
                        <>
                          <tr 
                            key={i} 
                            className={`border-b cursor-pointer hover:bg-muted/50 ${doc.alert ? "bg-red-50 dark:bg-red-900/20" : ""}`}
                            onClick={() => fetchDrilldown(doc.doctrine)}
                          >
                            <td className="py-2 px-2">
                              {expandedDoctrine === doc.doctrine ? (
                                <ChevronDown className="h-4 w-4" />
                              ) : (
                                <ChevronRight className="h-4 w-4" />
                              )}
                            </td>
                            <td className="py-2 px-2 font-medium">{doc.doctrine}</td>
                            <td className={`py-2 px-2 text-right font-bold ${getVerificationColor(doc.verification_rate)}`}>
                              {doc.verification_rate.toFixed(1)}%
                            </td>
                            <td className={`py-2 px-2 text-right ${doc.case_attributed_unsupported_rate > 0.5 ? "text-red-600 font-bold" : ""}`}>
                              {doc.case_attributed_unsupported_rate.toFixed(2)}%
                            </td>
                            <td className="py-2 px-2 text-right">
                              {doc.verified_citations}/{doc.total_citations}
                            </td>
                            <td className="py-2 px-2 text-right">
                              {formatLatency(doc.avg_latency_ms)}
                            </td>
                            <td className="py-2 px-2 text-center">
                              {doc.alert ? (
                                <AlertTriangle className="h-4 w-4 text-red-500 inline" />
                              ) : (
                                <CheckCircle className="h-4 w-4 text-green-500 inline" />
                              )}
                            </td>
                          </tr>
                          {expandedDoctrine === doc.doctrine && (
                            <tr>
                              <td colSpan={7} className="bg-muted/30 p-4">
                                {drilldownLoading ? (
                                  <div className="animate-pulse h-20 bg-muted rounded"></div>
                                ) : drilldownData ? (
                                  <div className="space-y-4">
                                    {doc.alert_reasons.length > 0 && (
                                      <div className="text-sm">
                                        <p className="font-medium text-red-600">Alert Reasons:</p>
                                        <ul className="list-disc list-inside">
                                          {doc.alert_reasons.map((r, j) => (
                                            <li key={j}>{r}</li>
                                          ))}
                                        </ul>
                                      </div>
                                    )}
                                    
                                    {drilldownData.failure_reasons.length > 0 && (
                                      <div>
                                        <p className="font-medium text-sm mb-2">Failure Reasons:</p>
                                        <div className="flex flex-wrap gap-2">
                                          {drilldownData.failure_reasons.slice(0, 5).map((fr, j) => (
                                            <Badge key={j} variant="outline" className="text-xs">
                                              {fr.reason}: {fr.count} ({fr.percentage.toFixed(0)}%)
                                            </Badge>
                                          ))}
                                        </div>
                                      </div>
                                    )}
                                    
                                    {drilldownData.failing_responses.length > 0 && (
                                      <div>
                                        <p className="font-medium text-sm mb-2">Recent Failing Responses:</p>
                                        <div className="text-xs font-mono space-y-1 max-h-40 overflow-y-auto">
                                          {drilldownData.failing_responses.slice(0, 10).map((r, j) => (
                                            <div key={j} className="flex gap-4">
                                              <span className="text-muted-foreground">{r.response_id?.slice(0, 8) || "N/A"}</span>
                                              <span>{r.verified_citations}/{r.total_citations} verified</span>
                                              <span className="text-muted-foreground">
                                                {r.created_at ? new Date(r.created_at).toLocaleString() : ""}
                                              </span>
                                            </div>
                                          ))}
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                ) : (
                                  <p className="text-muted-foreground">No drilldown data available</p>
                                )}
                              </td>
                            </tr>
                          )}
                        </>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <p className="text-muted-foreground text-center py-8">
                No doctrine data available for this period
              </p>
            )}
          </CardContent>
        </Card>

        <Card data-testid="period-info-card">
          <CardContent className="p-4">
            <p className="text-sm text-muted-foreground text-center">
              Data from {new Date(data?.period_start || "").toLocaleDateString()} to{" "}
              {new Date(data?.period_end || "").toLocaleDateString()} | Mode: {data?.mode || "ALL"}
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
