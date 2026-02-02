import type { Express, Request, Response, NextFunction } from "express";
import { createServer, type Server } from "http";
import httpProxy from "http-proxy";
import { setupAuth, registerAuthRoutes, isAuthenticated } from "./replit_integrations/auth";

const PYTHON_PORT = 8000;

export async function registerRoutes(httpServer: Server, app: Express): Promise<void> {
  // Set up Replit Auth FIRST (before other routes)
  await setupAuth(app);
  registerAuthRoutes(app);

  const proxy = httpProxy.createProxyServer({
    target: `http://localhost:${PYTHON_PORT}`,
    changeOrigin: true,
    proxyTimeout: 120000,
    timeout: 120000,
  });
  
  proxy.on("proxyReq", (proxyReq, req: any, res, options) => {
    if (req.body && Object.keys(req.body).length > 0) {
      const bodyData = JSON.stringify(req.body);
      proxyReq.setHeader("Content-Type", "application/json");
      proxyReq.setHeader("Content-Length", Buffer.byteLength(bodyData));
      proxyReq.write(bodyData);
    }
  });
  
  proxy.on("error", (err, req, res) => {
    console.error("[proxy] error:", err.message);
    if (res && !res.writableEnded) {
      (res as any).writeHead?.(503, { "Content-Type": "application/json" });
      (res as any).end?.(JSON.stringify({ 
        error: "Python backend unavailable", 
        message: "The backend is starting up. Please wait a moment and try again.",
        retryAfter: 5
      }));
    }
  });

  // Admin endpoints need longer timeout for bulk operations
  app.use("/api/admin", (req: Request, res: Response, next: NextFunction) => {
    req.setTimeout(600000);  // 10 minutes
    res.setTimeout(600000);
    proxy.web(req, res, { target: `http://localhost:${PYTHON_PORT}/api/admin` });
  });

  // Chat endpoints need longer timeout for web search + ingestion
  app.post("/api/conversations/:id/messages", (req: Request, res: Response, next: NextFunction) => {
    req.setTimeout(180000);  // 3 minutes for chat with web search
    res.setTimeout(180000);
    // Preserve original URL when proxying
    proxy.web(req, res, { target: `http://localhost:${PYTHON_PORT}` });
  });

  app.use("/api", (req: Request, res: Response, next: NextFunction) => {
    req.setTimeout(120000);
    res.setTimeout(120000);
    proxy.web(req, res, { target: `http://localhost:${PYTHON_PORT}/api` });
  });

  // PDF serving route - proxy to Python backend
  app.use("/pdf", (req: Request, res: Response, next: NextFunction) => {
    proxy.web(req, res, { target: `http://localhost:${PYTHON_PORT}/pdf` });
  });
}
