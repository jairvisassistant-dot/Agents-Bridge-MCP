import { spawn, type ChildProcess } from 'child_process';
import * as vscode from 'vscode';
import { type ConnectionState } from './types';

const BACKOFF_BASE = 1000; // 1s
const BACKOFF_MAX = 30000; // 30s
const CONNECT_DELAY = 1000; // 1s
const STOP_TIMEOUT = 3000; // 3s
const SPAWN_TIMEOUT = 500; // safety fallback

export class SidecarManager {
  private process: ChildProcess | null = null;
  private port: number;
  private state: ConnectionState = 'disconnected';
  private onStateChange: (state: ConnectionState) => void;
  private reconnectAttempts = 0;
  private active = true;

  constructor(
    port: number,
    onStateChange: (state: ConnectionState) => void,
    private _bundledPath?: string,
  ) {
    this.port = port;
    this.onStateChange = onStateChange;
  }

  // ── Public API ────────────────────────────────────────────────────

  getState(): ConnectionState {
    return this.state;
  }

  async start(dbPath: string): Promise<void> {
    this.active = true;

    if (this.process) {
      await this.stop();
      this.active = true; // stop() resets active, restore it
    }

    this.setState('connecting');

    try {
      const proc = await this.resolveAndSpawn(dbPath);
      this.process = proc;

      // Pipe stderr for logging; stdout unused in headless mode
      proc.stderr?.on('data', (data: Buffer) => {
        const text = data.toString().trim();
        if (text) {
          console.log(`[agent-bridge] ${text}`);
        }
      });

      // Handle unexpected exit — trigger auto-restart
      proc.on('exit', (code, signal) => {
        console.warn(
          `[agent-bridge] process exited code=${code} signal=${signal}`,
        );

        // Ignore stale events from a previous process
        if (this.process !== proc) return;
        this.process = null;

        if (this.active && code !== null && signal !== 'SIGTERM') {
          this.autoRestart(dbPath).catch(err =>
            console.error('[agent-bridge] auto-restart error:', err),
          );
        }
      });

      // Brief delay to let the process settle before declaring connected
      await this.delay(CONNECT_DELAY);

      if (this.process) {
        this.setState('connected');
        this.reconnectAttempts = 0;
      }
    } catch (err) {
      const nodeErr = err as NodeJS.ErrnoException;
      if (nodeErr.code === 'ENOENT') {
        const hint = this._bundledPath
          ? 'Bundled binary not found — reinstall the extension or install via `uv tool install agent-bridge`.'
          : 'Install via `uv tool install agent-bridge` or `pip install agent-bridge`.';
        vscode.window.showErrorMessage(
          `Agent Bridge: command not found. ${hint}`,
        );
      } else {
        vscode.window.showErrorMessage(
          `Agent Bridge: failed to start — ${nodeErr.message || String(err)}`,
        );
      }
      this.setState('error');
    }
  }

  async stop(): Promise<void> {
    this.active = false;

    if (!this.process) {
      this.setState('disconnected');
      this.reconnectAttempts = 0;
      return;
    }

    const proc = this.process;
    this.process = null;

    proc.kill('SIGTERM');

    // Wait up to STOP_TIMEOUT ms for graceful shutdown, then force-kill
    await new Promise<void>(resolve => {
      const timer = setTimeout(() => {
        try {
          proc.kill('SIGKILL');
        } catch {
          // process already dead
        }
        resolve();
      }, STOP_TIMEOUT);

      proc.on('exit', () => {
        clearTimeout(timer);
        resolve();
      });
    });

    this.setState('disconnected');
    this.reconnectAttempts = 0;
  }

  async restart(dbPath: string): Promise<void> {
    await this.stop();
    await this.start(dbPath);
  }

  // ── Private helpers ───────────────────────────────────────────────

  /**
   * Attempt to reconnect with exponential backoff.
   * Only proceeds if the extension is still active.
   */
  private async autoRestart(dbPath: string): Promise<void> {
    if (!this.active) return;

    const delay = Math.min(
      BACKOFF_BASE * 2 ** this.reconnectAttempts,
      BACKOFF_MAX,
    );
    this.reconnectAttempts++;

    console.warn(
      `[agent-bridge] restarting in ${delay}ms (attempt ${this.reconnectAttempts})`,
    );

    await this.delay(delay);
    if (!this.active) return;

    try {
      await this.start(dbPath);
    } catch (err) {
      console.error('[agent-bridge] auto-restart failed:', err);
    }
  }

  private setState(state: ConnectionState): void {
    this.state = state;
    this.onStateChange(state);
  }

  /**
   * Resolve the agent-bridge command.  Tries in order:
   *   1. Bundled binary (inside the VSC extension directory)
   *   2. `agent-bridge` on PATH
   *   3. `uv tool run agent-bridge`
   */
  private async resolveAndSpawn(dbPath: string): Promise<ChildProcess> {
    const baseArgs = [
      'start',
      '--headless',
      '--port',
      String(this.port),
      '--db-path',
      dbPath,
    ];

    // Attempt 1: bundled binary (inside extension install dir)
    if (this._bundledPath) {
      try {
        return await this.trySpawn(this._bundledPath, baseArgs);
      } catch (err) {
        const nodeErr = err as NodeJS.ErrnoException;
        if (nodeErr.code !== 'ENOENT') throw err;
      }
    }

    // Attempt 2: agent-bridge directly (expected on PATH)
    try {
      return await this.trySpawn('agent-bridge', baseArgs);
    } catch (err) {
      const nodeErr = err as NodeJS.ErrnoException;
      if (nodeErr.code !== 'ENOENT') throw err;
    }

    // Attempt 3: via uv tool
    return await this.trySpawn('uv', [
      'tool',
      'run',
      'agent-bridge',
      ...baseArgs,
    ]);
  }

  /**
   * Spawn a child process and return a promise that resolves once
   * the process has started (or rejects on spawn error).
   */
  private trySpawn(command: string, args: string[]): Promise<ChildProcess> {
    return new Promise((resolve, reject) => {
      const proc = spawn(command, args, {
        stdio: ['ignore', 'ignore', 'pipe'],
      });

      let settled = false;

      proc.on('error', (err: NodeJS.ErrnoException) => {
        if (!settled) {
          settled = true;
          reject(err);
        }
      });

      proc.on('spawn', () => {
        if (!settled) {
          settled = true;
          resolve(proc);
        }
      });

      // Safety timeout for environments that don't emit 'spawn'
      setTimeout(() => {
        if (!settled) {
          settled = true;
          resolve(proc);
        }
      }, SPAWN_TIMEOUT);
    });
  }

  private delay(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}
