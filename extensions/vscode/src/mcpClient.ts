/**
 * MCP (Model Context Protocol) client over SSE for the Agent Bridge VSC extension.
 *
 * Communicates with the Agent Bridge Python server via:
 *   - GET  /sse  — Server-Sent Events stream for server→client events
 *   - POST /messages/?sessionId=xxx — JSON-RPC requests (client→server)
 *
 * @see https://spec.modelcontextprotocol.io/
 */

import {
  type AgentInfo,
  type PlanInfo,
  type TaskInfo,
  type ChatMessage,
  type ThreadInfo,
  type ConnectionState,
  type MCPTool,
  type MCPCallResult,
} from "./types";

// ── Constants ───────────────────────────────────────────────────────

/** MCP protocol version advertised during handshake. */
const MCP_PROTOCOL_VERSION = "2024-11-05";

/** Client identity sent to the server on initialize. */
const CLIENT_INFO = {
  name: "agent-bridge-vsc",
  version: "1.0.0",
};

/** Default event type when the SSE stream omits the `event:` field. */
const DEFAULT_SSE_EVENT = "message";

/** Initial retry delay in milliseconds. */
const INITIAL_RETRY_DELAY_MS = 500;

/** Maximum retry delay cap in milliseconds. */
const MAX_RETRY_DELAY_MS = 10_000;

// ── Public API ──────────────────────────────────────────────────────

export class MCPClient {
  // ── State ──────────────────────────────────────────────────────────

  private port: number;
  private sessionId: string | null = null;
  private requestId = 1;
  private baseUrl: string;
  private abortController: AbortController | null = null;
  private sessionEndpoint: string | null = null;
  private onMessage: ((msg: ChatMessage) => void) | null;
  private onSseEvent: ((event: string, data: any) => void) | null;
  private _onDisconnect: (() => void) | null;
  private _reconnectEnabled = true;
  private _reconnecting = false;

  // ── Construction ───────────────────────────────────────────────────

  constructor(
    port: number,
    onMessage?: (msg: ChatMessage) => void,
    onSseEvent?: (event: string, data: any) => void,
    onDisconnect?: () => void,
  ) {
    this.port = port;
    this.baseUrl = `http://127.0.0.1:${port}`;
    this.onMessage = onMessage ?? null;
    this.onSseEvent = onSseEvent ?? null;
    this._onDisconnect = onDisconnect ?? null;
  }

  // ── Connection lifecycle ───────────────────────────────────────────

  /**
   * True when the client has an active session with the server.
   * Does **not** guarantee the underlying SSE stream is still open.
   */
  get connected(): boolean {
    return this.sessionId !== null;
  }

  /**
   * Open an SSE connection to the server and perform the MCP handshake.
   *
   * 1. GET /sse and wait for the `endpoint` event that carries the session URL.
   * 2. POST an MCP `initialize` request with the agreed protocol version.
   * 3. POST an `notifications/initialized` ping.
   * 4. Fork the SSE read-loop to the background so server-pushed events
   *    (chat messages, state updates, …) are handled live.
   *
   * @throws when the server is unreachable, returns an HTTP error,
   *         or the `endpoint` event never arrives.
   */
  async connect(): Promise<void> {
    this.cleanup();
    this.abortController = new AbortController();

    let lastError: Error | null = null;
    let delay = INITIAL_RETRY_DELAY_MS;

    for (let attempt = 0; ; attempt++) {
      // Throw on the first call if we already have a legitimate error,
      // or after exhausting retries below.
      if (attempt > 0) {
        await this.sleep(delay);
        delay = Math.min(delay * 2, MAX_RETRY_DELAY_MS);
      }

      try {
        const response = await fetch(`${this.baseUrl}/sse`, {
          signal: this.abortController.signal,
        });

        if (!response.ok) {
          throw new Error(
            `SSE connection failed: HTTP ${response.status} ${response.statusText}`,
          );
        }

        if (!response.body) {
          throw new Error("SSE response has no readable body stream");
        }

        // Success — proceed with the SSE stream.
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        // ── Phase 1 — wait for the `endpoint` event ──────────────
        while (!this.sessionEndpoint) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          buffer = this.processSseBuffer(buffer);
        }

        if (!this.sessionEndpoint) {
          throw new Error("No endpoint received from SSE stream");
        }

        // ── Phase 2 — MCP initialize handshake ───────────────────
        await this.jsonRpcRequest("initialize", {
          protocolVersion: MCP_PROTOCOL_VERSION,
          capabilities: {},
          clientInfo: CLIENT_INFO,
        });

        // ── Phase 3 — initialized notification ───────────────────
        await this.jsonRpcRequest("notifications/initialized", {});

        // ── Phase 4 — background SSE read-loop ───────────────────
        this.readSseLoop(reader, decoder, buffer).catch((err: Error) => {
          if (err.name !== "AbortError") {
            console.error("[MCPClient] SSE stream error:", err);
          }
        });

        return; // connected successfully
      } catch (err) {
        lastError = err instanceof Error ? err : new Error(String(err));

        // Don't retry if the user intentionally disconnected.
        if (lastError.name === "AbortError") {
          throw lastError;
        }

        // Keep looping to retry.
      }
    }
  }

  /**
   * Tear down the connection.
   * - Aborts the in-flight fetch (closes SSE stream and any pending POST).
   * - Resets session bookkeeping so `connected` returns `false`.
   */
  async disconnect(): Promise<void> {
    this._reconnectEnabled = false;
    this.cleanup();
  }

  // ── Tool operations ────────────────────────────────────────────────

  /**
   * Call an MCP tool by name.  This is the low-level primitive that every
   * convenience method (`getAgents`, `createTask`, …) delegates to.
   *
   * On network / protocol errors the result is returned **with**
   * `isError: true` rather than throwing, so callers can always expect a
   * well-typed `MCPCallResult`.
   */
  async callTool(
    name: string,
    args: Record<string, unknown> = {},
  ): Promise<MCPCallResult> {
    try {
      const result = await this.jsonRpcRequest("tools/call", {
        name,
        arguments: args,
      });
      return result as MCPCallResult;
    } catch (err) {
      return {
        content: [{ type: "text", text: String(err) }],
        isError: true,
      };
    }
  }

  /**
   * Enumerate every tool the server exposes.
   */
  async listTools(): Promise<MCPTool[]> {
    const result = await this.jsonRpcRequest("tools/list", {});
    return (result as { tools: MCPTool[] }).tools;
  }

  // ── Agent operations ───────────────────────────────────────────────

  /**
   * Fetch the list of registered agents.
   */
  async getAgents(): Promise<AgentInfo[]> {
    const result = await this.callTool("agent.list");
    return this.parseContent<AgentInfo[]>(result) ?? [];
  }

  // ── Plan operations ────────────────────────────────────────────────

  /**
   * Fetch all plans.
   */
  async getPlans(): Promise<PlanInfo[]> {
    const result = await this.callTool("plan.list");
    return this.parseContent<PlanInfo[]>(result) ?? [];
  }

  // ── Task operations ────────────────────────────────────────────────

  /**
   * Fetch tasks, optionally filtered by plan and/or status.
   */
  async getTasks(planId?: string, status?: string): Promise<TaskInfo[]> {
    const args: Record<string, unknown> = {};
    if (planId !== undefined) args.plan_id = planId;
    if (status !== undefined) args.status = status;

    const result = await this.callTool("task.list", args);
    return this.parseContent<TaskInfo[]>(result) ?? [];
  }

  /**
   * Claim a task for an agent.
   */
  async claimTask(taskId: string, agentId: string): Promise<void> {
    await this.callTool("task.claim", {
      task_id: taskId,
      agent_id: agentId,
    });
  }

  /**
   * Submit completed work for a task.
   */
  async submitWork(
    taskId: string,
    agentId: string,
    summary: string,
    diff: string,
  ): Promise<void> {
    await this.callTool("task.submit_work", {
      task_id: taskId,
      agent_id: agentId,
      summary,
      diff,
    });
  }

  /**
   * Create a new task under a plan and return its ID.
   */
  async createTask(
    planId: string,
    title: string,
    description: string,
  ): Promise<string> {
    const result = await this.callTool("task.create", {
      plan_id: planId,
      title,
      description,
    });

    const content = result.content.find((c) => c.type === "text");
    if (content) {
      try {
        const parsed = JSON.parse(content.text);
        return parsed.id ?? parsed.task_id ?? content.text;
      } catch {
        return content.text;
      }
    }

    throw new Error("createTask: no text content in response");
  }

  // ── Chat operations ────────────────────────────────────────────────

  /**
   * Read recent messages, optionally filtered by thread.
   *
   * @param threadId  When provided, only messages from this thread are returned.
   * @param limit     Maximum number of messages (default 50).
   */
  async getMessages(threadId?: string, limit = 50): Promise<ChatMessage[]> {
    const args: Record<string, unknown> = { limit };
    if (threadId !== undefined) args.thread_id = threadId;

    const result = await this.callTool("chat.read", args);
    return this.parseContent<ChatMessage[]>(result) ?? [];
  }

  /**
   * Send a chat message as the given sender, optionally scoped to a thread.
   */
  async sendMessage(
    sender: string,
    text: string,
    threadId?: string,
  ): Promise<void> {
    const args: Record<string, unknown> = { sender, text };
    if (threadId !== undefined) args.thread_id = threadId;

    await this.callTool("chat.send", args);
  }

  // ── JSON-RPC transport ─────────────────────────────────────────────

  /**
   * Send a JSON-RPC 2.0 request to the session endpoint and return the
   * `result` field of the response.
   *
   * Notifications (methods beginning with `notifications/`) are sent
   * **without** an `id` field; the server returns no response for them.
   *
   * @throws on HTTP errors, JSON-RPC error responses, or if the session
   *         has not been established yet.
   */
  private async jsonRpcRequest(method: string, params?: unknown): Promise<any> {
    if (!this.sessionEndpoint) {
      throw new Error("MCPClient is not connected");
    }

    const id = this.requestId++;
    const isNotification = method.startsWith("notifications/");

    const body: Record<string, unknown> = {
      jsonrpc: "2.0",
      method,
    };

    if (params !== undefined) {
      body.params = params;
    }

    if (!isNotification) {
      body.id = id;
    }

    // sessionEndpoint may be relative ("/messages/?sessionId=xxx") or
    // absolute ("http://…"); normalise either way.
    const url = this.sessionEndpoint.startsWith("http")
      ? this.sessionEndpoint
      : `${this.baseUrl}${this.sessionEndpoint}`;

    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: this.abortController?.signal,
    });

    if (!response.ok) {
      throw new Error(
        `JSON-RPC HTTP ${response.status}: ${response.statusText}`,
      );
    }

    // Notifications produce no response body.
    if (isNotification) {
      return undefined;
    }

    const json: any = await response.json();

    if (json.error) {
      throw new Error(
        `JSON-RPC error ${json.error.code}: ${json.error.message}`,
      );
    }

    return json.result;
  }

  // ── SSE helpers ────────────────────────────────────────────────────

  /**
   * Process a chunk of SSE buffer, splitting on `\n\n` event boundaries.
   *
   * Returns the (potentially incomplete) remainder so the caller can
   * prepend it to the next chunk.
   */
  private processSseBuffer(buffer: string): string {
    const parts = buffer.split("\n\n");
    // The last element may be an incomplete event — keep it for later.
    const remaining = parts.pop() ?? "";

    for (const part of parts) {
      if (!part.trim()) continue;
      this.handleSseEvent(part);
    }

    return remaining;
  }

  /**
   * Parse a single SSE event (everything between two `\n\n` separators)
   * and dispatch it.
   *
   * Special events:
   *   - `endpoint`      — stores the session POST URL and extracts sessionId.
   *   - `chat.message`  — parses the JSON payload into a `ChatMessage` and
   *                        fires the `onMessage` callback.
   *
   * Every event (including the ones above) is also forwarded to the
   * generic `onSseEvent` callback.
   */
  private handleSseEvent(part: string): void {
    let event = DEFAULT_SSE_EVENT;
    let data = "";

    for (const line of part.split("\n")) {
      if (line.startsWith("event: ")) {
        event = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        // Accumulate continuation lines (spec §5 — multiple data: lines
        // are concatenated with a single newline).
        if (data) data += "\n";
        data += line.slice(6);
      }
    }

    // ── endpoint event ────────────────────────────────────────────────
    if (event === "endpoint" && data) {
      this.sessionEndpoint = data;
      try {
        const sessionUrl = new URL(data, this.baseUrl);
        this.sessionId = sessionUrl.searchParams.get("sessionId");
      } catch {
        // data may be a path-only string — that's fine, we store as-is.
      }
    }

    // ── chat.message event ────────────────────────────────────────────
    if (event === "chat.message" && data) {
      try {
        const msg: ChatMessage = JSON.parse(data);
        this.onMessage?.(msg);
      } catch {
        // Malformed JSON — ignore silently.
      }
    }

    // ── generic callback ──────────────────────────────────────────────
    this.onSseEvent?.(event, data);
  }

  /**
   * Background read-loop that consumes the SSE stream for the lifetime
   * of the connection.
   *
   * When the stream ends (server closed the connection, or `abort()` was
   * called) it resets session bookkeeping.
   */
  private async readSseLoop(
    reader: ReadableStreamDefaultReader<Uint8Array>,
    decoder: InstanceType<typeof TextDecoder>,
    initialBuffer: string,
  ): Promise<void> {
    let buffer = initialBuffer;

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        buffer = this.processSseBuffer(buffer);
      }
    } finally {
      // Stream ended or was aborted — the session is no longer valid.
      this.sessionId = null;
      this.sessionEndpoint = null;

      // Notify the extension that the stream dropped.
      this._onDisconnect?.();

      // Attempt auto-reconnect unless the user explicitly disconnected.
      if (this._reconnectEnabled) {
        this._autoReconnect().catch((err: Error) => {
          if (err.name !== "AbortError") {
            console.error("[MCPClient] Auto-reconnect error:", err);
          }
        });
      }
    }
  }

  /**
   * Attempt to reconnect after the SSE stream drops unexpectedly.
   *
   * Waits a brief stabilisation delay, then delegates to `connect()`
   * which already has its own exponential-backoff retry loop.
   * Aborts early when `disconnect()` is called externally.
   */
  private async _autoReconnect(): Promise<void> {
    if (this._reconnecting || this.sessionId !== null) return;
    this._reconnecting = true;

    // Brief delay so we don't hammer the server on a quick restart.
    await this.sleep(1000);

    if (!this._reconnectEnabled) {
      this._reconnecting = false;
      return;
    }

    try {
      // `connect()` has its own retry loop with exponential backoff.
      // It will keep retrying until success or AbortError.
      await this.connect();
    } catch {
      // AbortError from disconnect() — nothing to do.
    } finally {
      this._reconnecting = false;
    }
  }

  // ── Internal utilities ─────────────────────────────────────────────

  /**
   * Parse the first `text` content item from an `MCPCallResult` as JSON.
   *
   * Returns `undefined` when no text content exists or parsing fails.
   */
  private parseContent<T>(result: MCPCallResult): T | undefined {
    const content = result.content.find((c) => c.type === "text");
    if (!content) return undefined;

    try {
      return JSON.parse(content.text) as T;
    } catch {
      return undefined;
    }
  }

  /**
   * Reset all connection-related state.
   * Safe to call multiple times or when already disconnected.
   */
  private cleanup(): void {
    this.abortController?.abort();
    this.abortController = null;
    this.sessionId = null;
    this.sessionEndpoint = null;
    this._reconnecting = false;
  }

  /**
   * Promise-based sleep for use with exponential backoff.
   */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
