// Starts the FastAPI backend for `npm run dev:all`, on any OS.
// Uses backend/venv (or backend/.venv) if present -- venv/Scripts/python.exe on
// Windows, venv/bin/python elsewhere -- otherwise falls back to python3/python on PATH.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

const backend = resolve(import.meta.dirname, "..", "..", "backend");
const isWin = process.platform === "win32";
const candidates = ["venv", ".venv"].map((d) =>
  join(backend, d, isWin ? "Scripts" : "bin", isWin ? "python.exe" : "python"),
);
const python = candidates.find(existsSync) ?? (isWin ? "python" : "python3");

const child = spawn(
  python,
  ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", process.env.API_PORT ?? "8001", "--reload"],
  { cwd: backend, stdio: "inherit" },
);
child.on("exit", (code) => process.exit(code ?? 0));
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => child.kill(sig));
