/**
 * Shared types for Agent Bridge VSC extension.
 */

// ── Data models ──────────────────────────────────────────────────

export interface AgentInfo {
  id: string;
  name: string;
  role: string;
  status: "online" | "idle" | "offline";
  lastHeartbeat: string | null;
  metadata?: Record<string, string>;
}

export interface TaskInfo {
  id: string;
  title: string;
  description: string;
  status: "pending" | "in_progress" | "review" | "approved";
  planId: string;
  assignee: string | null;
  createdAt: string;
}

export interface PlanInfo {
  id: string;
  title: string;
  description: string;
  status: string;
  createdAt: string;
}

export interface ChatMessage {
  id: string;
  sender: string;
  text: string;
  timestamp: string;
  threadId: string | null;
}

export interface ThreadInfo {
  id: string;
  title: string;
  status: "open" | "resolved";
  participants: string[];
  lastActivityAt: string | null;
}

export interface BridgeConfig {
  port: number;
  dbPath: string;
  autoStart: boolean;
  pollIntervalSeconds: number;
  autoCreateTerminals: boolean;
}

// ── Connection state ─────────────────────────────────────────────

export type ConnectionState =
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "error";

// ── MCP protocol types ──────────────────────────────────────────

export interface MCPTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export interface MCPCallResult {
  content: Array<{ type: string; text: string }>;
  isError?: boolean;
}

// ── Events ───────────────────────────────────────────────────────

export interface BridgeEvents {
  onConnectionStateChange: (state: ConnectionState) => void;
  onAgentsUpdate: (agents: AgentInfo[]) => void;
  onKanbanUpdate: (plans: PlanInfo[], tasks: TaskInfo[]) => void;
  onChatUpdate: (messages: ChatMessage[]) => void;
  onError: (error: string) => void;
}
