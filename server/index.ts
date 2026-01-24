import express, { type Request, Response, NextFunction } from "express";
import { registerRoutes } from "./routes";
import { serveStatic } from "./static";
import { createServer } from "http";
import { spawn, ChildProcess } from "child_process";

const app = express();
const httpServer = createServer(app);

let pythonProcess: ChildProcess | null = null;
let pythonReady = false;

async function waitForPython(maxRetries = 30, delayMs = 1000): Promise<boolean> {
  for (let i = 0; i < maxRetries; i++) {
    try {
      const response = await fetch("http://localhost:8000/api/status");
      if (response.ok) {
        console.log("[python] Backend is ready!");
        pythonReady = true;
        return true;
      }
    } catch (e) {
      // Python not ready yet
    }
    await new Promise(r => setTimeout(r, delayMs));
  }
  console.error("[python] Backend failed to start after", maxRetries, "retries");
  return false;
}

function startPythonBackend() {
  if (pythonProcess) {
    pythonProcess.kill();
  }
  
  pythonReady = false;
  console.log("Starting Python FastAPI backend on port 8000...");
  
  // Try python3 first (more common in production), then fall back to python
  const pythonCmd = process.platform === "win32" ? "python" : "python3";
  
  pythonProcess = spawn(pythonCmd, ["-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"], {
    cwd: process.cwd(),
    stdio: ["pipe", "pipe", "pipe"],
    env: { ...process.env },
  });
  
  pythonProcess.stdout?.on("data", (data) => {
    console.log("[python]", data.toString().trim());
  });
  
  pythonProcess.stderr?.on("data", (data) => {
    console.log("[python]", data.toString().trim());
  });
  
  pythonProcess.on("error", (err) => {
    console.error("[python] Failed to start:", err.message);
  });
  
  pythonProcess.on("close", (code) => {
    console.log("[python] exited with code", code);
    pythonReady = false;
    if (code !== 0 && code !== null) {
      setTimeout(startPythonBackend, 2000);
    }
  });
  
  // Start checking for Python readiness
  waitForPython();
}

startPythonBackend();

declare module "http" {
  interface IncomingMessage {
    rawBody: unknown;
  }
}

app.use(
  express.json({
    verify: (req, _res, buf) => {
      req.rawBody = buf;
    },
  }),
);

app.use(express.urlencoded({ extended: false }));

export function log(message: string, source = "express") {
  const formattedTime = new Date().toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });

  console.log(`${formattedTime} [${source}] ${message}`);
}

app.use((req, res, next) => {
  const start = Date.now();
  const path = req.path;
  let capturedJsonResponse: Record<string, any> | undefined = undefined;

  const originalResJson = res.json;
  res.json = function (bodyJson, ...args) {
    capturedJsonResponse = bodyJson;
    return originalResJson.apply(res, [bodyJson, ...args]);
  };

  res.on("finish", () => {
    const duration = Date.now() - start;
    if (path.startsWith("/api")) {
      let logLine = `${req.method} ${path} ${res.statusCode} in ${duration}ms`;
      if (capturedJsonResponse) {
        logLine += ` :: ${JSON.stringify(capturedJsonResponse)}`;
      }

      log(logLine);
    }
  });

  next();
});

(async () => {
  await registerRoutes(httpServer, app);

  app.use((err: any, _req: Request, res: Response, next: NextFunction) => {
    const status = err.status || err.statusCode || 500;
    const message = err.message || "Internal Server Error";

    console.error("Internal Server Error:", err);

    if (res.headersSent) {
      return next(err);
    }

    return res.status(status).json({ message });
  });

  // importantly only setup vite in development and after
  // setting up all the other routes so the catch-all route
  // doesn't interfere with the other routes
  if (process.env.NODE_ENV === "production") {
    serveStatic(app);
  } else {
    const { setupVite } = await import("./vite");
    await setupVite(httpServer, app);
  }

  // ALWAYS serve the app on the port specified in the environment variable PORT
  // Other ports are firewalled. Default to 5000 if not specified.
  // this serves both the API and the client.
  // It is the only port that is not firewalled.
  const port = parseInt(process.env.PORT || "5000", 10);
  httpServer.listen(
    {
      port,
      host: "0.0.0.0",
      reusePort: true,
    },
    () => {
      log(`serving on port ${port}`);
    },
  );
})();
