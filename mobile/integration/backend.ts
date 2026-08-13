/**
 * Boots a disposable Brain Buddy backend for the integration suite:
 * `BRAIN_BUDDY_ENV=test` wires deterministic AI providers, allows the
 * text-fixture audio mime, and (with the opt-in flag) runs the voice sweep
 * so sealed operations progress to review without real STT keys.
 */

import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

export interface BackendHandle {
  baseUrl: string;
  invite(): string;
  stop(): void;
}

const BACKEND_DIR = path.resolve(__dirname, "..", "..", "backend");

export function resolveBackendPython(
  backendDir: string,
  override: string | undefined,
  executableExists: (candidate: string) => boolean = existsSync,
): string {
  if (override) return override;
  const virtualenvPython = path.join(backendDir, ".venv", "bin", "python");
  return executableExists(virtualenvPython) ? virtualenvPython : "python3";
}

const BACKEND_PYTHON = resolveBackendPython(
  BACKEND_DIR,
  process.env.BRAIN_BUDDY_BACKEND_PYTHON,
);

export async function startBackend(port: number): Promise<BackendHandle> {
  const dataDir = mkdtempSync(path.join(tmpdir(), "bb-mobile-integration-"));
  const env = {
    ...process.env,
    BRAIN_BUDDY_ENV: "test",
    BRAIN_BUDDY_DATA_DIR: dataDir,
    BRAIN_BUDDY_FEATURE_FLAGS: "voice_brain_dump=on",
    BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST: "1",
    BRAIN_BUDDY_VOICE_SWEEP_INTERVAL_SECONDS: "1",
  };

  const child: ChildProcess = spawn(
    BACKEND_PYTHON,
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(port)],
    { cwd: BACKEND_DIR, env, stdio: ["ignore", "pipe", "pipe"] },
  );

  let output = "";
  child.stdout?.on("data", (chunk: Buffer) => {
    output += chunk.toString();
  });
  child.stderr?.on("data", (chunk: Buffer) => {
    output += chunk.toString();
  });

  const baseUrl = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 60_000;
  for (;;) {
    if (child.exitCode !== null) {
      throw new Error(`Backend exited early (${child.exitCode}):\n${output.slice(-4000)}`);
    }
    try {
      const response = await fetch(`${baseUrl}/health`);
      if (response.ok) {
        break;
      }
    } catch {
      // Not up yet.
    }
    if (Date.now() > deadline) {
      child.kill("SIGKILL");
      throw new Error(`Backend did not become healthy in 60s:\n${output.slice(-4000)}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }

  return {
    baseUrl,
    invite() {
      const result = spawnSync(BACKEND_PYTHON, ["-m", "app.cli", "create-invite"], {
        cwd: BACKEND_DIR,
        env,
        encoding: "utf-8",
      });
      if (result.status !== 0) {
        throw new Error(`create-invite failed: ${result.stderr}`);
      }
      const code = result.stdout.trim().split("\n").pop();
      if (!code) {
        throw new Error(`create-invite printed nothing: ${result.stdout}`);
      }
      return code;
    },
    stop() {
      child.kill("SIGTERM");
      // The pending timer intentionally keeps the process alive long enough
      // to force-kill a stuck backend and remove the temp data dir.
      setTimeout(() => {
        if (child.exitCode === null) {
          child.kill("SIGKILL");
        }
        rmSync(dataDir, { recursive: true, force: true });
      }, 1500);
    },
  };
}
