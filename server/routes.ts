import type { Express, Request, Response, NextFunction } from "express";
import { createServer, type Server } from "http";
import httpProxy from "http-proxy";

const PYTHON_PORT = 8000;

export async function registerRoutes(httpServer: Server, app: Express): Promise<void> {
  const proxy = httpProxy.createProxyServer({
    target: `http://localhost:${PYTHON_PORT}`,
    changeOrigin: true,
  });
  
  proxy.on("error", (err, req, res) => {
    console.error("[proxy] error:", err.message);
    if (res && !res.writableEnded) {
      (res as any).writeHead?.(503, { "Content-Type": "application/json" });
      (res as any).end?.(JSON.stringify({ error: "Python backend unavailable" }));
    }
  });

  app.use("/api", (req: Request, res: Response, next: NextFunction) => {
    proxy.web(req, res, { target: `http://localhost:${PYTHON_PORT}/api` });
  });
}
