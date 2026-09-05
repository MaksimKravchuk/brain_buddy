/**
 * A real loopback A2A agent, on a real socket, for the integration suite.
 *
 * The suite's whole point is that the *shipped* client talks to a *real*
 * backend, so the agent at the far end has to be real too: a stubbed one would
 * prove nothing about discovery, the card fetch or the authenticated probe.
 * This spawns `backend/tests/a2a_fakes.py`, which is the same fake the backend
 * suites drive, and waits for it to announce the port it bound.
 */

import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

import { resolveBackendPython } from "./backend";

const BACKEND_DIR = path.resolve(__dirname, "..", "..", "backend");

const BACKEND_PYTHON = resolveBackendPython(
  BACKEND_DIR,
  process.env.BRAIN_BUDDY_BACKEND_PYTHON,
  existsSync,
);

export interface FakeAgentHandle {
  /** The agent's origin. The card lives below it, as A2A §14.3 requires. */
  origin: string;
  stop(): void;
}

export interface FakeAgentOptions {
  /** When set, the agent rejects any other bearer token with 401/`-32050`. */
  bearerToken?: string;
  /** Answer on the socket but serve no card: the `a2a_not_an_agent` category. */
  servesCard?: boolean;
}

export async function startFakeAgent(
  options: FakeAgentOptions = {},
): Promise<FakeAgentHandle> {
  const args = ["-m", "tests.a2a_fakes"];
  if (options.bearerToken) {
    args.push("--bearer-token", options.bearerToken);
  }
  if (options.servesCard === false) {
    args.push("--not-an-agent");
  }

  const child: ChildProcess = spawn(BACKEND_PYTHON, args, {
    cwd: BACKEND_DIR,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  let output = "";
  child.stderr?.on("data", (chunk: Buffer) => {
    output += chunk.toString();
  });

  const port = await new Promise<string>((resolve, reject) => {
    const deadline = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error(`Fake agent did not announce a port in 20s:\n${output.slice(-2000)}`));
    }, 20_000);
    child.stdout?.on("data", (chunk: Buffer) => {
      output += chunk.toString();
      const match = /PORT=(\d+)/.exec(output);
      if (match) {
        clearTimeout(deadline);
        resolve(match[1]);
      }
    });
    child.on("exit", (code) => {
      clearTimeout(deadline);
      reject(new Error(`Fake agent exited early (${code}):\n${output.slice(-2000)}`));
    });
  });

  return {
    origin: `http://127.0.0.1:${port}`,
    stop() {
      child.kill("SIGTERM");
      setTimeout(() => {
        if (child.exitCode === null) {
          child.kill("SIGKILL");
        }
      }, 1000);
    },
  };
}
