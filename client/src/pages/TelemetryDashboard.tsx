import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ArrowLeft, AlertTriangle, CheckCircle, XCircle, RefreshCw } from "lucide-react";
import { Link } from "wouter";

interface DoctrineMetrics {
  doctrine: string;
  verification_rate: number;
  total_queries: number;
  total_citations: number;
  verified_citations: number;
  unsupported_rate: number;
  avg_latency_ms: number;
  alert: boolean;
}

interface BindingFailure {
  reason: string;
  count: number;
  percentage: number;
  examples: string[];
}

interface DashboardData {
  overall_verification_rate: number;
  total_queries: number;
  total_citations: number;
  verified_citations: number;
  unsupported_statements_rate: number;
  median_latency_ms: number;
  by_doctrine: DoctrineMetrics[];
  top_binding_failures: BindingFailure[];
  alerts: string[];
  period_start: string;
  period_end: string;
}

export default function TelemetryDashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(7);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`/api/telemetry/dashboard?days=${days}`);
      if (!response.ok) throw new Error("Failed to fetch telemetry data");
      const result = await response.json();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [days]);

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
        <div className="flex items-center justify-between">
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
                  <h3 className="font-semibold text-yellow-800 dark:text-yellow-200">Alerts</h3>
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
                Overall Verification Rate
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
                Target: ≥90%
              </p>
            </CardContent>
          </Card>

          <Card data-testid="total-queries-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Total Queries
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">{data?.total_queries || 0}</div>
              <p className="text-xs text-muted-foreground mt-2">
                {days === 1 ? "Last 24 hours" : `Last ${days} days`}
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
                Verified / Total
              </p>
            </CardContent>
          </Card>

          <Card data-testid="latency-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Median Latency
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">
                {((data?.median_latency_ms || 0) / 1000).toFixed(1)}s
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                Response time
              </p>
            </CardContent>
          </Card>
        </div>

        <Card data-testid="doctrine-breakdown-card">
          <CardHeader>
            <CardTitle>Verification by Doctrine</CardTitle>
          </CardHeader>
          <CardContent>
            {data?.by_doctrine && data.by_doctrine.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left py-2 px-4">Doctrine</th>
                      <th className="text-right py-2 px-4">Verification Rate</th>
                      <th className="text-right py-2 px-4">Queries</th>
                      <th className="text-right py-2 px-4">Citations</th>
                      <th className="text-right py-2 px-4">Avg Latency</th>
                      <th className="text-center py-2 px-4">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_doctrine.map((doc, i) => (
                      <tr key={i} className={`border-b ${doc.alert ? "bg-red-50 dark:bg-red-900/20" : ""}`}>
                        <td className="py-2 px-4 font-medium">{doc.doctrine}</td>
                        <td className={`py-2 px-4 text-right font-bold ${getVerificationColor(doc.verification_rate)}`}>
                          {doc.verification_rate.toFixed(1)}%
                        </td>
                        <td className="py-2 px-4 text-right">{doc.total_queries}</td>
                        <td className="py-2 px-4 text-right">
                          {doc.verified_citations}/{doc.total_citations}
                        </td>
                        <td className="py-2 px-4 text-right">
                          {(doc.avg_latency_ms / 1000).toFixed(1)}s
                        </td>
                        <td className="py-2 px-4 text-center">
                          {doc.alert ? (
                            <AlertTriangle className="h-4 w-4 text-red-500 inline" />
                          ) : (
                            <CheckCircle className="h-4 w-4 text-green-500 inline" />
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-muted-foreground text-center py-8">
                No doctrine data available for this period
              </p>
            )}
          </CardContent>
        </Card>

        {data?.top_binding_failures && data.top_binding_failures.length > 0 && (
          <Card data-testid="binding-failures-card">
            <CardHeader>
              <CardTitle>Top Binding Failure Reasons</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {data.top_binding_failures.map((failure, i) => (
                  <div key={i} className="border-b pb-4 last:border-0">
                    <div className="flex justify-between items-start">
                      <div>
                        <p className="font-medium">{failure.reason}</p>
                        {failure.examples.length > 0 && (
                          <ul className="text-sm text-muted-foreground mt-1">
                            {failure.examples.map((ex, j) => (
                              <li key={j} className="truncate max-w-md">• {ex}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                      <div className="text-right">
                        <Badge variant="outline">{failure.count} occurrences</Badge>
                        <p className="text-sm text-muted-foreground mt-1">
                          {failure.percentage.toFixed(1)}%
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        <Card data-testid="period-info-card">
          <CardContent className="p-4">
            <p className="text-sm text-muted-foreground text-center">
              Data from {new Date(data?.period_start || "").toLocaleDateString()} to{" "}
              {new Date(data?.period_end || "").toLocaleDateString()}
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
