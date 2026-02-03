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
    // Debug logging - show target URL properly
    const userId = req.user?.claims?.sub;
    const targetUrl = typeof options.target === 'string' ? options.target : 
      (options.target ? `${(options.target as any).protocol || 'http:'}//${(options.target as any).host}` : 'unknown');
    console.log(`[proxy] ${req.method} ${req.originalUrl} -> ${targetUrl}${req.url} (user: ${userId || 'anonymous'})`);
    
    // Pass user ID to Python backend if authenticated
    if (userId) {
      proxyReq.setHeader("X-User-Id", userId);
    }
    
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

  // Helper to restore original URL before proxying (Express strips the mount path)
  const proxyWithOriginalUrl = (mountPath: string, timeout: number) => {
    return (req: Request, res: Response, next: NextFunction) => {
      req.setTimeout(timeout);
      res.setTimeout(timeout);
      // Restore the original URL that Express stripped
      req.url = mountPath + req.url;
      // Remove double slashes that can occur (e.g., /api/conversations + / → /api/conversations/)
      if (req.url.endsWith('/') && req.url.length > 1) {
        req.url = req.url.slice(0, -1);
      }
      proxy.web(req, res);
    };
  };

  // Protected routes - require authentication for conversation endpoints
  app.use("/api/conversations", isAuthenticated, proxyWithOriginalUrl("/api/conversations", 180000));

  // Admin endpoints need longer timeout for bulk operations
  app.use("/api/admin", proxyWithOriginalUrl("/api/admin", 600000));

  // Public API endpoints (status, search, etc.)
  app.use("/api", proxyWithOriginalUrl("/api", 120000));

  // PDF serving route - proxy to Python backend
  app.use("/pdf", proxyWithOriginalUrl("/pdf", 60000));
}
