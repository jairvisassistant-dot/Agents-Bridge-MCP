/**
 * OS-level PID health checker for the Agent Bridge Python sidecar.
 *
 * Combines two verification layers:
 *   1. `process.kill(pid, 0)` — cheap OS-level check that the PID exists
 *      and the current process has permission to signal it.
 *   2. HTTP GET /health — application-level check that the server is
 *      actually responding (catches hangs, dead-but-not-reaped processes).
 *
 * Health status transitions:
 *   - Consecutive failures >= maxFailures → "unhealthy"
 *   - A single successful check → "healthy"
 *   - Before first check → "unknown"
 */

import { type HealthStatus } from "./types";

// ── Constants ──────────────────────────────────────────────────────

const DEFAULT_INTERVAL_MS = 10_000; // 10s
const DEFAULT_MAX_FAILURES = 3;

// ── Health Checker ─────────────────────────────────────────────────

export class PidHealthChecker {
  private timer: NodeJS.Timeout | null = null;
  private _status: HealthStatus = "unknown";
  private consecutiveFailures = 0;
  private _pid: number;
  private _pidCheckOnly = false;

  constructor(
    pid: number,
    private port: number,
    private onStatusChange: (status: HealthStatus) => void,
    private intervalMs: number = DEFAULT_INTERVAL_MS,
    private maxFailures: number = DEFAULT_MAX_FAILURES,
  ) {
    this._pid = pid;
  }

  // ── Public API ───────────────────────────────────────────────────

  get status(): HealthStatus {
    return this._status;
  }

  get pid(): number {
    return this._pid;
  }

  /**
   * Update the tracked PID (e.g. after a restart).
   * Resets consecutive failures and status to "unknown".
   */
  updatePid(pid: number, pidCheckOnly?: boolean): void {
    this._pid = pid;
    this._pidCheckOnly = pidCheckOnly ?? false;
    this.consecutiveFailures = 0;
    this.setStatus("unknown");
  }

  start(): void {
    this.stop();
    this.runCheck(); // immediate first check
    this.timer = setInterval(() => {
      this.runCheck().catch((err) =>
        console.error("[PidHealthChecker] check error:", err),
      );
    }, this.intervalMs);
  }

  stop(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.setStatus("unknown");
    this.consecutiveFailures = 0;
  }

  dispose(): void {
    this.stop();
  }

  // ── Internal ─────────────────────────────────────────────────────

  private setStatus(status: HealthStatus): void {
    if (this._status === status) return;
    this._status = status;
    this.onStatusChange(status);
  }

  /**
   * Run a single health-check cycle:
   *   1. OS-level PID check via `process.kill(pid, 0)`
   *   2. HTTP GET /health (skipped if pidCheckOnly is true, e.g. on Windows)
   */
  private async runCheck(): Promise<void> {
    // ── Layer 1: OS-level PID validation ─────────────────────────
    const pidAlive = this.checkPidOsLevel();
    if (!pidAlive) {
      this.consecutiveFailures++;
      console.warn(
        `[PidHealthChecker] PID ${this._pid} not found at OS level ` +
          `(failure ${this.consecutiveFailures}/${this.maxFailures})`,
      );
      if (this.consecutiveFailures >= this.maxFailures) {
        this.setStatus("unhealthy");
      }
      return;
    }

    // ── Layer 2: HTTP endpoint check ─────────────────────────────
    if (this._pidCheckOnly) {
      // HTTP check disabled — OS check was enough
      this.consecutiveFailures = 0;
      this.setStatus("healthy");
      return;
    }

    try {
      const ok = await this.checkHttpEndpoint();
      if (ok) {
        this.consecutiveFailures = 0;
        this.setStatus("healthy");
      } else {
        this.consecutiveFailures++;
        console.warn(
          `[PidHealthChecker] HTTP health check failed ` +
            `(failure ${this.consecutiveFailures}/${this.maxFailures})`,
        );
        if (this.consecutiveFailures >= this.maxFailures) {
          this.setStatus("unhealthy");
        }
      }
    } catch (err) {
      this.consecutiveFailures++;
      console.warn(
        `[PidHealthChecker] HTTP health check error: ${err} ` +
          `(failure ${this.consecutiveFailures}/${this.maxFailures})`,
      );
      if (this.consecutiveFailures >= this.maxFailures) {
        this.setStatus("unhealthy");
      }
    }
  }

  /**
   * OS-level PID existence check.
   *
   * Uses `process.kill(pid, 0)` which is a POSIX signal-no-op: it
   * succeeds if the process exists and we have permission, throws
   * ESRCH if the process does not exist.
   *
   * On Windows this always returns `true` because the signal-0
   * behaviour is not guaranteed; the HTTP check covers that case.
   */
  private checkPidOsLevel(): boolean {
    try {
      process.kill(this._pid, 0);
      return true;
    } catch (err: unknown) {
      if ((err as NodeJS.ErrnoException).code === "ESRCH") {
        return false; // process does not exist
      }
      // EPERM means the process exists but we can't signal it — that's ok
      if ((err as NodeJS.ErrnoException).code === "EPERM") {
        return true;
      }
      // Unknown error — assume alive to avoid false positive restart
      console.warn("[PidHealthChecker] Unexpected process.kill error:", err);
      return true;
    }
  }

  /**
   * Application-level health check via the HTTP /health endpoint.
   *
   * Returns `true` if the server responds with HTTP 200 and
   * `{"status": "ok"}`, `false` otherwise.
   */
  private async checkHttpEndpoint(): Promise<boolean> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);

    try {
      const response = await fetch(`http://127.0.0.1:${this.port}/health`, {
        signal: controller.signal,
      });

      if (!response.ok) return false;

      const body: unknown = await response.json();
      if (typeof body !== "object" || body === null) return false;

      const data = body as Record<string, unknown>;
      return data.status === "ok";
    } catch {
      return false;
    } finally {
      clearTimeout(timeout);
    }
  }
}
