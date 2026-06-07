/**
 * Agent Bridge VSC Extension — Entry point.
 *
 * Wires together all subsystems:
 *   - Sidecar (Python agent-bridge process)
 *   - MCP client (SSE/JSON-RPC connection)
 *   - Tree views (Agent list + Kanban)
 *   - Chat WebView
 *   - Terminal manager
 *   - Status bar
 *   - Commands
 */

import * as vscode from "vscode";
import * as path from "path";
import { existsSync } from "fs";
import { loadConfig, getBridgeJsonPath } from "./config";
import { SidecarManager } from "./sidecar";
import { MCPClient } from "./mcpClient";
import { AgentTreeProvider } from "./agentProvider";
import { KanbanTreeProvider } from "./kanbanProvider";
import { ChatWebviewProvider } from "./chatWebview";
import { AgentDashboardProvider } from "./agentDashboard";
import { TerminalManager } from "./terminalManager";
import { BridgeStatusBar } from "./statusBar";
import { CommandRegistry } from "./commands";
import type {
  ConnectionState,
  HealthStatus,
  AgentInfo,
  PlanInfo,
  TaskInfo,
  DashboardData,
} from "./types";

// ── Activation ────────────────────────────────────────────────────

let pollTimer: NodeJS.Timeout | null = null;
let statusBar: BridgeStatusBar;
let agentProvider: AgentTreeProvider;
let kanbanProvider: KanbanTreeProvider;
let chatProvider: ChatWebviewProvider;
let dashboardProvider: AgentDashboardProvider;
let sidecar: SidecarManager;
let mcpClient: MCPClient;
let terminalManager: TerminalManager;
let commandRegistry: CommandRegistry;

/** True while MCPClient is attempting to reconnect after an SSE stream drop. */
let isReconnecting = false;

/**
 * Resolve the path to a bundled `agent-bridge` binary inside the
 * extension install directory, or `undefined` when none is present.
 *
 * The binary is platform-specific (`.exe` on Windows).
 */
function resolveBundledPath(context: vscode.ExtensionContext): string | undefined {
  const extName = process.platform === "win32" ? "agent-bridge.exe" : "agent-bridge";
  const candidate = path.join(context.extensionPath, "bin", extName);
  try {
    if (existsSync(candidate)) {
      return candidate;
    }
  } catch {
    // FS error — not readable; fall through to PATH/uv
  }
  return undefined;
}

export function activate(context: vscode.ExtensionContext): void {
  console.log("[agent-bridge] Activating extension...");

  const config = loadConfig();
  const dbPath = resolveDbPath(config.dbPath);

  // ── Status bar ───────────────────────────────────────────────
  statusBar = new BridgeStatusBar(context);
  statusBar.update("disconnected", 0, 0);

  // ── Sidecar (Python process) ─────────────────────────────────
  const bundledPath = resolveBundledPath(context);
  sidecar = new SidecarManager(
    config.port,
    (state: ConnectionState) => {
      refreshAll(state);
    },
    (_health: HealthStatus) => {
      refreshStatusBar();
    },
    bundledPath,
  );

  // ── MCP Client ───────────────────────────────────────────────
  mcpClient = new MCPClient(
    config.port,
    // On new chat message: refresh chat
    (_msg) => {
      refreshChat();
    },
    undefined, // onSseEvent — not used
    // On SSE stream drop: flag reconnecting and refresh UI
    () => {
      isReconnecting = true;
      refreshAll(sidecar.getState() as ConnectionState);
    },
  );

  // ── Tree providers ───────────────────────────────────────────
  agentProvider = new AgentTreeProvider("disconnected");
  kanbanProvider = new KanbanTreeProvider();

  vscode.window.registerTreeDataProvider(
    "agent-bridge.agents",
    agentProvider,
  );
  vscode.window.registerTreeDataProvider(
    "agent-bridge.kanban",
    kanbanProvider,
  );

  // ── Chat webview ─────────────────────────────────────────────
  chatProvider = new ChatWebviewProvider(
    context.extensionUri,
    async (sender: string, text: string, threadId?: string) => {
      try {
        await mcpClient.sendMessage(sender, text, threadId);
        // Refresh chat after sending to show the new message
        await refreshChat();
      } catch (err) {
        vscode.window.showErrorMessage(
          `Failed to send message: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
    },
  );

  // Register the chat view as a webview panel (lazy — shown on command)
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "agent-bridge.chat.focus",
      () => {
        chatProvider.show();
      },
    ),
  );

  // ── Dashboard webview ─────────────────────────────────────────
  dashboardProvider = new AgentDashboardProvider(
    context.extensionUri,
    (command: string, args?: Record<string, string>) => {
      switch (command) {
        case "focus-terminal":
          if (args?.agentId) terminalManager?.showTerminal(args.agentId);
          break;
        case "disconnect-agent":
          if (args?.agentId) terminalManager?.disconnectAgent(args.agentId);
          refreshAll(sidecar.getState() as ConnectionState);
          break;
        case "open-chat":
          vscode.commands.executeCommand("agent-bridge.chat.focus");
          break;
        case "start-bridge":
          vscode.commands.executeCommand("agent-bridge.start");
          break;
        case "restart-bridge":
          vscode.commands.executeCommand("agent-bridge.restart");
          break;
      }
    },
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      "agent-bridge.showDashboard",
      () => {
        dashboardProvider.show();
      },
    ),
  );

  // ── Terminal manager ─────────────────────────────────────────
  terminalManager = new TerminalManager(
    config.port,
    config.dbPath,
    (_count: number) => {
      refreshStatusBar();
    },
  );

  // ── Status bar quick menu ────────────────────────────────────
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "agent-bridge.showMenu",
      async () => {
        const pick = await vscode.window.showQuickPick([
          { label: "$(dashboard) Dashboard", id: "agent-bridge.showDashboard" },
          { label: "$(comment-discussion) Open Chat", id: "agent-bridge.openChat" },
          { label: "$(plug) Connect Agent", id: "agent-bridge.connectAgent" },
          { label: "$(terminal) New Terminal", id: "agent-bridge.newTerminal" },
          { label: "$(check-all) Claim Task", id: "agent-bridge.claimTask" },
          { label: "$(repo-push) Submit Work", id: "agent-bridge.submitWork" },
          { label: "$(debug-disconnect) Disconnect", id: "agent-bridge.stop" },
        ], { placeHolder: "Agent Bridge — choose action" });
        if (pick) {
          vscode.commands.executeCommand(pick.id);
        }
      },
    ),
  );

  // ── Commands ─────────────────────────────────────────────────
  commandRegistry = new CommandRegistry(
    context,
    sidecar,
    mcpClient,
    terminalManager,
    () => {
      refreshAll(sidecar.getState() as ConnectionState);
    },
    dbPath,
  );
  commandRegistry.registerAll();

  // ── Config change listener ───────────────────────────────────
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("agent-bridge")) {
        console.log("[agent-bridge] Configuration changed");
      }
    }),
  );

  // ── Auto-start ───────────────────────────────────────────────
  if (config.autoStart) {
    vscode.commands.executeCommand("agent-bridge.start");
  }

  // ── Polling for state updates ────────────────────────────────
  startPolling(config.pollIntervalSeconds);

  console.log("[agent-bridge] Extension activated");
}

// ── Deactivation ─────────────────────────────────────────────────

export function deactivate(): void {
  console.log("[agent-bridge] Deactivating extension...");

  stopPolling();
  terminalManager?.disconnectAll();
  mcpClient?.disconnect().catch(() => {});
  sidecar?.stop().catch(() => {});
  chatProvider?.dispose();
  dashboardProvider?.dispose();
  statusBar?.dispose();

  console.log("[agent-bridge] Extension deactivated");
}

// ── Polling ──────────────────────────────────────────────────────

function startPolling(intervalSeconds: number): void {
  stopPolling();
  pollTimer = setInterval(() => {
    refreshAll(sidecar.getState() as ConnectionState);
  }, intervalSeconds * 1000);
}

function stopPolling(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

// ── Refresh ──────────────────────────────────────────────────────

// Keep track of the latest agent count for the status bar
let _lastAgentCount = 0;

// Track pending mentions for badge and desktop notification (Feature 4)
let _lastMentionCount = 0;
let _lastPendingCount = 0;

// Track roles that were already polled in this poll cycle to avoid duplicate
// terminal.get_pending calls.
let _terminalRolesPolled = new Set<string>();

async function refreshAll(state: ConnectionState): Promise<void> {
  try {
    if (state === "connected" && mcpClient.connected) {
      // Reconnection succeeded — clear the reconnecting flag.
      isReconnecting = false;

      const [agents, plans, tasks] = await Promise.all([
        safeGetAgents(),
        safeGetPlans(),
        safeGetTasks(),
      ]);

      _lastAgentCount = agents.length;
      agentProvider.refresh(agents, state);
      kanbanProvider.refresh(plans, tasks);
      chatProvider.postAgents(agents);

      // ── Update dashboard data ─────────────────────────────────
      const dashData: DashboardData = {
        agents,
        connectionState: state,
        health: sidecar.getHealthStatus(),
        terminalCount: terminalManager?.getConnectedCount() ?? 0,
        pid: sidecar.pid,
      };
      dashboardProvider?.update(dashData);

      // ── Update terminal roles & deliver cross-terminal messages ──
      _terminalRolesPolled.clear();
      for (const agent of agents) {
        terminalManager?.setAgentRole(agent.id, agent.role);
      }

      // Check for pending terminal messages per role (Feature 2)
      const roleSet = new Set(agents.map((a) => a.role));
      for (const role of roleSet) {
        if (_terminalRolesPolled.has(role)) continue;
        _terminalRolesPolled.add(role);

        try {
          const messages = await mcpClient.getPendingTerminalMessages(role);
          if (messages.length > 0) {
            const targets = terminalManager?.getAgentIdsByRole(role) ?? [];
            for (const msg of messages) {
              for (const targetId of targets) {
                terminalManager?.notifyTerminal(targetId, msg.sender, msg.text);
              }
              // Desktop notification for the human (once per message)
              if (targets.length > 0) {
                vscode.window.showInformationMessage(
                  `📩 ${msg.sender} → ${role}: ${msg.text.substring(0, 80)}`,
                );
              }
            }
            console.log(
              `[agent-bridge] Delivered ${messages.length} terminal message(s) for role '${role}'`,
            );
          }
        } catch (err) {
          console.warn(`[agent-bridge] Terminal message poll error for '${role}':`, err);
        }
      }

      // ── Pending mentions badge + desktop notification (Feature 4) ──
      try {
        const counts = await mcpClient.getPendingCounts();
        if (counts.pendingMentions > _lastMentionCount) {
          const newMentions = counts.pendingMentions - _lastMentionCount;
          vscode.window.showInformationMessage(
            `📨 ${newMentions} new mention${newMentions > 1 ? 's' : ''} pending`,
          );
        }
        _lastMentionCount = counts.pendingMentions;
        _lastPendingCount = counts.pendingMentions + counts.pendingTerminalMessages;
      } catch (err) {
        console.warn("[agent-bridge] Pending counts poll error:", err);
      }
    } else {
      // Clear reconnecting flag only on terminal states (disconnected or
      // error), not during connecting or when the sidecar is still up but
      // the SSE stream dropped (the reconnecting flow handles that case).
      if (state === "disconnected" || state === "error") {
        isReconnecting = false;
      }
      _lastAgentCount = 0;
      _lastMentionCount = 0;
      _lastPendingCount = 0;
      agentProvider.refresh([], state);
      kanbanProvider.refresh([], []);
      dashboardProvider?.update({
        agents: [],
        connectionState: state,
        health: sidecar.getHealthStatus(),
        terminalCount: 0,
        pid: sidecar.pid,
      });
    }
  } catch (err) {
    console.warn("[agent-bridge] Refresh error:", err);
  }

  refreshStatusBar();
}

function refreshStatusBar(): void {
  // If MCPClient is actively reconnecting, show that instead of the
  // sidecar state (the process may be up but the SSE stream is down).
  if (isReconnecting) {
    statusBar.update("reconnecting", _lastAgentCount, terminalManager?.getConnectedCount() ?? 0, undefined, _lastPendingCount);
    return;
  }

  const state = sidecar.getState() as ConnectionState;
  const health = sidecar.getHealthStatus();
  const terminalCount = terminalManager?.getConnectedCount() ?? 0;
  statusBar.update(state, _lastAgentCount, terminalCount, health, _lastPendingCount);
}

async function refreshChat(): Promise<void> {
  if (!mcpClient.connected) return;
  try {
    const messages = await mcpClient.getMessages();
    chatProvider.postMessages(messages);
  } catch (err) {
    console.warn("[agent-bridge] Chat refresh error:", err);
  }
}

// ── Safe fetching (never throw) ──────────────────────────────────

async function safeGetAgents(): Promise<AgentInfo[]> {
  try {
    return (await mcpClient.getAgents()) ?? [];
  } catch {
    return [];
  }
}

async function safeGetPlans(): Promise<PlanInfo[]> {
  try {
    return (await mcpClient.getPlans()) ?? [];
  } catch {
    return [];
  }
}

async function safeGetTasks(): Promise<TaskInfo[]> {
  try {
    return (await mcpClient.getTasks()) ?? [];
  } catch {
    return [];
  }
}

// ── Utilities ────────────────────────────────────────────────────

/**
 * Resolve the database path relative to the workspace root.
 * Falls back to just the config value if no workspace is open.
 */
function resolveDbPath(dbPath: string): string {
  const folders = vscode.workspace.workspaceFolders;
  if (folders && folders.length > 0) {
    return folders[0].uri.fsPath + "/" + dbPath;
  }
  return dbPath;
}
