import { useState, useEffect, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { ArrowLeft, Play, Pause, RefreshCw, AlertCircle, CheckCircle, Clock, FileText, Database } from "lucide-react";
import { Link } from "wouter";
import { useToast } from "@/hooks/use-toast";

interface IngestionStatus {
  total_documents: number;
  ingested: number;
  pending: number;
  failed: number;
  total_pages: number;
  percent_complete: number;
}

interface IngestionResult {
  success: boolean;
  message: string;
  processed: number;
  succeeded: number;
  failed: number;
  results: Array<{
    success: boolean;
    status: string;
    doc_id: string;
    num_pages?: number;
    num_chunks?: number;
    error?: string;
  }>;
}

interface ActivityLog {
  time: string;
  type: "success" | "error" | "info";
  message: string;
}

export default function Admin() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [batchSize, setBatchSize] = useState(10);
  const [isRunning, setIsRunning] = useState(false);
  const [activityLog, setActivityLog] = useState<ActivityLog[]>([]);

  const addLog = (type: ActivityLog["type"], message: string) => {
    const entry: ActivityLog = {
      time: new Date().toLocaleTimeString(),
      type,
      message
    };
    setActivityLog(prev => [entry, ...prev].slice(0, 100));
  };

  const { data: status, isLoading, refetch: refetchStatus } = useQuery<IngestionStatus>({
    queryKey: ["/api/admin/ingest_status"],
    refetchInterval: isRunning ? 5000 : 30000
  });

  const ingestMutation = useMutation({
    mutationFn: async (limit: number) => {
      const res = await fetch(`/api/admin/ingest_batch?limit=${limit}`, { method: "POST" });
      if (!res.ok) throw new Error("Ingestion failed");
      return res.json() as Promise<IngestionResult>;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["/api/admin/ingest_status"] });
      addLog("success", `Batch complete: ${data.succeeded} succeeded, ${data.failed} failed`);
      
      data.results.forEach(r => {
        if (r.success) {
          addLog("info", `Ingested ${r.doc_id.slice(0, 8)}... (${r.num_pages} pages)`);
        } else {
          addLog("error", `Failed ${r.doc_id.slice(0, 8)}...: ${r.error}`);
        }
      });
    },
    onError: (error) => {
      addLog("error", `Error: ${error.message}`);
      toast({
        title: "Ingestion Error",
        description: error.message,
        variant: "destructive"
      });
    }
  });

  const [isLoadingManifest, setIsLoadingManifest] = useState(false);
  
  const handleLoadManifest = async (count: number) => {
    setIsLoadingManifest(true);
    addLog("info", `Building manifest from CourtListener (${count} opinions)...`);
    
    try {
      const res = await fetch(`/api/admin/build_and_load_manifest?count=${count}`, { method: "POST" });
      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(errorText || "Failed to load manifest");
      }
      const data = await res.json();
      queryClient.invalidateQueries({ queryKey: ["/api/admin/ingest_status"] });
      addLog("success", `Loaded ${data.imported} documents from CourtListener`);
      toast({
        title: "Manifest Loaded",
        description: `Successfully loaded ${data.imported} documents`
      });
    } catch (error: any) {
      addLog("error", `Failed to load manifest: ${error.message}`);
      toast({
        title: "Error Loading Manifest",
        description: error.message,
        variant: "destructive"
      });
    } finally {
      setIsLoadingManifest(false);
    }
  };

  const isRunningRef = useRef(false);
  const timeoutRef = useRef<number | null>(null);

  const handleStartBatch = async () => {
    addLog("info", `Starting batch ingestion (${batchSize} documents)...`);
    ingestMutation.mutate(batchSize);
  };

  const stopContinuous = useCallback(() => {
    isRunningRef.current = false;
    setIsRunning(false);
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    addLog("info", "Stopping continuous ingestion...");
  }, []);

  const runContinuous = useCallback(async () => {
    if (!isRunningRef.current) return;
    
    try {
      const res = await fetch(`/api/admin/ingest_batch?limit=${batchSize}`, { method: "POST" });
      if (!res.ok) throw new Error("Ingestion failed");
      const data = await res.json() as IngestionResult;
      
      queryClient.invalidateQueries({ queryKey: ["/api/admin/ingest_status"] });
      addLog("success", `Batch: ${data.succeeded} succeeded, ${data.failed} failed`);
      
      if (data.processed > 0 && isRunningRef.current) {
        timeoutRef.current = window.setTimeout(runContinuous, 2000);
      } else {
        stopContinuous();
        addLog("info", "Continuous ingestion complete - no more pending documents");
        toast({
          title: "Ingestion Complete",
          description: "All pending documents have been processed"
        });
      }
    } catch (error) {
      stopContinuous();
      addLog("error", `Error: ${(error as Error).message}`);
    }
  }, [batchSize, queryClient, stopContinuous, toast]);

  const handleContinuousIngest = () => {
    if (isRunning) {
      stopContinuous();
      return;
    }
    
    isRunningRef.current = true;
    setIsRunning(true);
    addLog("info", "Starting continuous ingestion...");
    runContinuous();
  };

  useEffect(() => {
    if (isRunning) {
      runContinuous();
    }
  }, []);

  const percentComplete = status?.percent_complete ?? 0;

  return (
    <div className="min-h-screen bg-background p-6" data-testid="admin-page">
      <div className="max-w-6xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/">
              <Button variant="ghost" size="icon" data-testid="back-button">
                <ArrowLeft className="h-5 w-5" />
              </Button>
            </Link>
            <div>
              <h1 className="text-2xl font-bold">Admin Dashboard</h1>
              <p className="text-muted-foreground">Manage opinion ingestion and monitor progress</p>
            </div>
          </div>
          <Button variant="outline" onClick={() => refetchStatus()} data-testid="refresh-status">
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
        </div>

        <div className="grid gap-4 md:grid-cols-4">
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Total Documents</CardDescription>
              <CardTitle className="text-3xl" data-testid="stat-total">
                {isLoading ? "..." : status?.total_documents ?? 0}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center text-muted-foreground">
                <Database className="h-4 w-4 mr-1" />
                In database
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Ingested</CardDescription>
              <CardTitle className="text-3xl text-green-600" data-testid="stat-ingested">
                {isLoading ? "..." : status?.ingested ?? 0}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center text-muted-foreground">
                <CheckCircle className="h-4 w-4 mr-1" />
                {status?.total_pages ?? 0} pages extracted
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Pending</CardDescription>
              <CardTitle className="text-3xl text-yellow-600" data-testid="stat-pending">
                {isLoading ? "..." : status?.pending ?? 0}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center text-muted-foreground">
                <Clock className="h-4 w-4 mr-1" />
                Awaiting ingestion
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Failed</CardDescription>
              <CardTitle className="text-3xl text-red-600" data-testid="stat-failed">
                {isLoading ? "..." : status?.failed ?? 0}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center text-muted-foreground">
                <AlertCircle className="h-4 w-4 mr-1" />
                Need retry
              </div>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Progress</CardTitle>
            <CardDescription>Overall ingestion progress</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>Ingested</span>
                <span>{percentComplete.toFixed(1)}%</span>
              </div>
              <Progress value={percentComplete} className="h-3" data-testid="progress-bar" />
            </div>
          </CardContent>
        </Card>

        <Card className={status?.total_documents === 0 ? "border-orange-200 bg-orange-50 dark:border-orange-800 dark:bg-orange-950" : ""}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {status?.total_documents === 0 ? (
                <AlertCircle className="h-5 w-5 text-orange-600" />
              ) : (
                <Database className="h-5 w-5" />
              )}
              Load Opinions from CourtListener
            </CardTitle>
            <CardDescription>
              {status?.total_documents === 0 
                ? "No documents loaded yet. Choose how many opinions to import from CourtListener."
                : "Add more CAFC opinions to your database. New opinions will be deduplicated automatically."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={() => handleLoadManifest(100)}
                disabled={isLoadingManifest}
                variant="outline"
                data-testid="load-100-button"
              >
                Load 100 opinions
              </Button>
              <Button
                onClick={() => handleLoadManifest(500)}
                disabled={isLoadingManifest}
                variant="outline"
                data-testid="load-500-button"
              >
                Load 500 opinions
              </Button>
              <Button
                onClick={() => handleLoadManifest(1000)}
                disabled={isLoadingManifest}
                data-testid="load-1000-button"
              >
                Load 1,000 opinions
              </Button>
            </div>
            {isLoadingManifest && (
              <Badge variant="secondary" className="animate-pulse">
                <RefreshCw className="h-3 w-3 mr-1 animate-spin" />
                Loading opinions from CourtListener...
              </Badge>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Ingestion Controls</CardTitle>
            <CardDescription>Start, stop, and configure ingestion batches</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <label className="text-sm font-medium">Batch Size:</label>
                <Input
                  type="number"
                  value={batchSize}
                  onChange={(e) => setBatchSize(parseInt(e.target.value) || 10)}
                  className="w-20"
                  min={1}
                  max={100}
                  data-testid="batch-size-input"
                />
              </div>
              <Button
                onClick={handleStartBatch}
                disabled={ingestMutation.isPending || isRunning}
                data-testid="start-batch-button"
              >
                <Play className="h-4 w-4 mr-2" />
                Run Single Batch
              </Button>
              <Button
                onClick={handleContinuousIngest}
                variant={isRunning ? "destructive" : "default"}
                data-testid="continuous-button"
              >
                {isRunning ? (
                  <>
                    <Pause className="h-4 w-4 mr-2" />
                    Stop Continuous
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4 mr-2" />
                    Start Continuous
                  </>
                )}
              </Button>
            </div>
            
            {isRunning && (
              <Badge variant="secondary" className="animate-pulse">
                <RefreshCw className="h-3 w-3 mr-1 animate-spin" />
                Continuous ingestion running...
              </Badge>
            )}
            
            {ingestMutation.isPending && (
              <Badge variant="secondary">
                <RefreshCw className="h-3 w-3 mr-1 animate-spin" />
                Processing batch...
              </Badge>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Activity Log</CardTitle>
            <CardDescription>Recent ingestion activity</CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-64" data-testid="activity-log">
              {activityLog.length === 0 ? (
                <div className="text-center text-muted-foreground py-8">
                  <FileText className="h-8 w-8 mx-auto mb-2 opacity-50" />
                  <p>No activity yet. Start ingestion to see logs.</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {activityLog.map((log, i) => (
                    <div key={i} className="flex items-start gap-2 text-sm p-2 rounded bg-muted/50">
                      <span className="text-muted-foreground text-xs w-20 flex-shrink-0">
                        {log.time}
                      </span>
                      {log.type === "success" && <CheckCircle className="h-4 w-4 text-green-500 flex-shrink-0" />}
                      {log.type === "error" && <AlertCircle className="h-4 w-4 text-red-500 flex-shrink-0" />}
                      {log.type === "info" && <Clock className="h-4 w-4 text-blue-500 flex-shrink-0" />}
                      <span className={log.type === "error" ? "text-red-600" : ""}>
                        {log.message}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
