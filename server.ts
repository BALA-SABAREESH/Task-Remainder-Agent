import "dotenv/config";
import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import express, { type Request, type Response } from "express";

const PORT = Number(process.env.PORT || 3000);
const PYTHON_PORT = Number(process.env.PYTHON_AGENT_PORT || 8001);
const PYTHON_URL = `http://127.0.0.1:${PYTHON_PORT}`;
const ROOT_DIR = process.cwd();

let pythonProc: ChildProcess | null = null;
let shuttingDown = false;

function resolvePythonExecutable(): string {
  const venvPython = path.join(ROOT_DIR, ".venv", "bin", "python");
  if (fs.existsSync(venvPython)) {
    return venvPython;
  }
  return "python3";
}

function startPythonAgent(): void {
  if (shuttingDown) return;
  const pythonBin = resolvePythonExecutable();
  pythonProc = spawn(
    pythonBin,
    [
      "-m",
      "uvicorn",
      "python_agent.server:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(PYTHON_PORT),
      "--log-level",
      "warning",
    ],
    {
      cwd: ROOT_DIR,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );

  pythonProc.stdout?.on("data", (chunk: Buffer) => {
    const text = chunk.toString().trim();
    if (text) console.log(`[python-agent] ${text}`);
  });

  pythonProc.stderr?.on("data", (chunk: Buffer) => {
    const text = chunk.toString().trim();
    if (text) console.error(`[python-agent] ${text}`);
  });

  pythonProc.on("exit", (code, signal) => {
    pythonProc = null;
    if (!shuttingDown) {
      console.error(
        `[python-agent] exited unexpectedly (code=${code}, signal=${signal}), restarting in 1s...`,
      );
      setTimeout(startPythonAgent, 1000);
    }
  });
}

async function waitForPythonAgent(timeoutMs = 15000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${PYTHON_URL}/health`);
      if (res.ok) return;
    } catch {
      // keep polling briefly until uvicorn binds
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("Python LangGraph agent failed to become healthy in time");
}

async function proxyToPython(req: Request, res: Response): Promise<void> {
  try {
    const targetUrl = `${PYTHON_URL}${req.originalUrl}`;
    const hasBody = !["GET", "HEAD"].includes(req.method.toUpperCase());
    const upstream = await fetch(targetUrl, {
      method: req.method,
      headers: {
        "Content-Type": "application/json",
      },
      body: hasBody ? JSON.stringify(req.body ?? {}) : undefined,
    });

    const contentType = upstream.headers.get("content-type") || "application/json";
    const text = await upstream.text();
    res.status(upstream.status).type(contentType).send(text);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Python backend unavailable";
    res.status(502).json({ error: message });
  }
}

async function main(): Promise<void> {
  startPythonAgent();
  await waitForPythonAgent();

  const app = express();
  app.use(express.json({ limit: "4mb" }));

  app.all("/api/*", proxyToPython);

  if (process.env.NODE_ENV !== "production") {
    const { createServer: createViteServer } = await import("vite");
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distDir = path.join(ROOT_DIR, "dist");
    app.use(express.static(distDir));
    app.get("*", (_req, res) => {
      res.sendFile(path.join(distDir, "index.html"));
    });
  }

  const server = app.listen(PORT, "0.0.0.0", () => {
    console.log(`NeuralTask server listening on http://0.0.0.0:${PORT}`);
  });

  const shutdown = () => {
    shuttingDown = true;
    if (pythonProc) {
      pythonProc.kill("SIGTERM");
    }
    server.close(() => process.exit(0));
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

main().catch((err) => {
  console.error("Failed to start server:", err);
  process.exit(1);
});
