/**
 * Command registry for Agent Bridge VSC extension.
 *
 * Registers all `agent-bridge.*` commands — start/stop/restart the
 * sidecar, manage agent terminals, claim tasks, submit work, and
 * open the chat webview.
 */

import * as vscode from "vscode";
import { readBridgeJson } from "./config";

// ── CommandRegistry ───────────────────────────────────────────────

export class CommandRegistry {
  constructor(
    private context: vscode.ExtensionContext,
    private sidecar: {
      start: (dbPath: string) => Promise<void>;
      stop: () => Promise<void>;
      restart: (dbPath: string) => Promise<void>;
      getState: () => string;
    },
    private mcpClient: {
      connect: () => Promise<void>;
      disconnect: () => Promise<void>;
      getAgents: () => Promise<any[]>;
      getPlans: () => Promise<any[]>;
      getTasks: (planId?: string, status?: string) => Promise<any[]>;
      sendMessage: (sender: string, text: string, threadId?: string) => Promise<void>;
      claimTask: (taskId: string, agentId: string) => Promise<void>;
      submitWork: (taskId: string, agentId: string, summary: string, diff: string) => Promise<void>;
    },
    private terminalManager: {
      createTerminal: (agentId: string, name: string, role: string, cmd?: string) => Promise<any>;
      disconnectAll: () => void;
      getConnectedCount: () => number;
    },
    private onStateChange: () => void,
    private dbPath: string,
  ) {}

  // ── Registration ──────────────────────────────────────────────

  /**
   * Register every `agent-bridge.*` command into
   * `this.context.subscriptions`.
   */
  registerAll(): void {
    this.context.subscriptions.push(
      // ── Lifecycle ────────────────────────────────────────────
      vscode.commands.registerCommand("agent-bridge.start", async () => {
        try {
          vscode.window.setStatusBarMessage(
            "Agent Bridge: Connecting...",
          );

          await this.sidecar.start(this.dbPath);
          await this.sleep(1500);
          await this.mcpClient.connect();

          // Disable auto-start so manual start is explicit
          await vscode.workspace
            .getConfiguration("agent-bridge")
            .update(
              "autoStart",
              false,
              vscode.ConfigurationTarget.Global,
            );

          this.onStateChange();
          vscode.window.showInformationMessage(
            "Agent Bridge: Connected",
          );
        } catch (err) {
          this.showError("Failed to start Agent Bridge", err);
        }
      }),

      vscode.commands.registerCommand("agent-bridge.stop", async () => {
        try {
          await this.mcpClient.disconnect();
          await this.sidecar.stop();
          this.onStateChange();
          vscode.window.showInformationMessage(
            "Agent Bridge: Disconnected",
          );
        } catch (err) {
          this.showError("Failed to stop Agent Bridge", err);
        }
      }),

      vscode.commands.registerCommand(
        "agent-bridge.restart",
        async () => {
          try {
            await this.mcpClient.disconnect();
            await this.sidecar.stop();

            vscode.window.setStatusBarMessage(
              "Agent Bridge: Connecting...",
            );
            await this.sidecar.start(this.dbPath);
            await this.sleep(1500);
            await this.mcpClient.connect();

            await vscode.workspace
              .getConfiguration("agent-bridge")
              .update(
                "autoStart",
                false,
                vscode.ConfigurationTarget.Global,
              );

            this.onStateChange();
            vscode.window.showInformationMessage(
              "Agent Bridge: Restarted",
            );
          } catch (err) {
            this.showError("Failed to restart Agent Bridge", err);
          }
        },
      ),

      // ── Chat ─────────────────────────────────────────────────
      vscode.commands.registerCommand(
        "agent-bridge.openChat",
        async () => {
          try {
            await vscode.commands.executeCommand(
              "agent-bridge.chat.focus",
            );
          } catch (err) {
            this.showError("Failed to open chat", err);
          }
        },
      ),

      // ── Agent terminals ──────────────────────────────────────
      vscode.commands.registerCommand(
        "agent-bridge.connectAgent",
        this.promptConnectAgent.bind(this),
      ),

      vscode.commands.registerCommand(
        "agent-bridge.newTerminal",
        this.promptConnectAgent.bind(this),
      ),

      vscode.commands.registerCommand(
        "agent-bridge.disconnectAgent",
        async () => {
          try {
            const count = this.terminalManager.getConnectedCount();
            if (count === 0) {
              vscode.window.showInformationMessage(
                "No agents currently connected",
              );
              return;
            }

            const confirmed = await vscode.window.showWarningMessage(
              `Disconnect all ${count} connected agent(s)?`,
              { modal: true },
              "Disconnect All",
            );
            if (confirmed !== "Disconnect All") return;

            this.terminalManager.disconnectAll();
            this.onStateChange();
            vscode.window.showInformationMessage(
              "All agents disconnected",
            );
          } catch (err) {
            this.showError("Failed to disconnect agents", err);
          }
        },
      ),

      // ── Task workflow ────────────────────────────────────────
      vscode.commands.registerCommand(
        "agent-bridge.claimTask",
        async () => {
          try {
            const tasks = await this.mcpClient.getTasks("pending");
            if (!tasks || tasks.length === 0) {
              vscode.window.showInformationMessage(
                "No pending tasks available to claim",
              );
              return;
            }

            const taskPick = await vscode.window.showQuickPick(
              tasks.map((t: any) => ({
                label: t.title ?? "Untitled",
                description: t.id,
                detail: t.description ?? "",
                taskId: t.id,
              })),
              {
                placeHolder: "Select a task to claim",
              },
            );
            if (!taskPick) return;

            const agents = await this.mcpClient.getAgents();
            let agentPick: { label: string; agentId: string } | undefined;

            if (agents && agents.length > 0) {
              agentPick = await vscode.window.showQuickPick(
                agents.map((a: any) => ({
                  label: a.name ?? a.id,
                  description: a.role ?? "",
                  agentId: a.id,
                })),
                {
                  placeHolder: "Select the agent to assign this task to",
                },
              );
            } else {
              const agentId = await vscode.window.showInputBox({
                prompt: "Enter agent ID to assign the task to",
                placeHolder: "agent-id",
              });
              if (!agentId) return;
              await this.mcpClient.claimTask(
                taskPick.taskId,
                agentId,
              );
              vscode.window.showInformationMessage(
                `Task "${taskPick.label}" claimed by agent ${agentId}`,
              );
              this.onStateChange();
              return;
            }

            if (!agentPick) return;

            await this.mcpClient.claimTask(
              taskPick.taskId,
              agentPick.agentId,
            );
            vscode.window.showInformationMessage(
              `Task "${taskPick.label}" claimed by ${agentPick.label}`,
            );
            this.onStateChange();
          } catch (err) {
            this.showError("Failed to claim task", err);
          }
        },
      ),

      vscode.commands.registerCommand(
        "agent-bridge.submitWork",
        async () => {
          try {
            const tasks = await this.mcpClient.getTasks(
              "in_progress",
            );
            if (!tasks || tasks.length === 0) {
              vscode.window.showInformationMessage(
                "No in-progress tasks to submit work for",
              );
              return;
            }

            const taskPick = await vscode.window.showQuickPick(
              tasks.map((t: any) => ({
                label: t.title ?? "Untitled",
                description: t.id,
                detail: t.description ?? "",
                taskId: t.id,
                assignee: t.assignee ?? null,
              })),
              {
                placeHolder: "Select a task to submit work for",
              },
            );
            if (!taskPick) return;

            const summary = await vscode.window.showInputBox({
              prompt:
                "Describe the work completed (summary)",
              placeHolder:
                "e.g., Implemented the authentication middleware with JWT verification...",
              value: "",
            });
            if (summary === undefined) return;

            const diff = await vscode.window.showInputBox({
              prompt: "Paste the diff or patch for this work",
              placeHolder: "e.g., diff --git a/src/auth.ts b/src/auth.ts\n@@ ... @@",
              value: "",
            });
            if (diff === undefined) return;

            // Resolve agent ID from the task's assignee, or ask
            let agentId = taskPick.assignee;
            if (!agentId) {
              const input = await vscode.window.showInputBox({
                prompt:
                  "Enter the agent ID that completed this work",
                placeHolder: "agent-id",
              });
              if (!input) return;
              agentId = input;
            }

            await this.mcpClient.submitWork(
              taskPick.taskId,
              agentId,
              summary,
              diff,
            );
            vscode.window.showInformationMessage(
              `Work submitted for task "${taskPick.label}"`,
            );
            this.onStateChange();
          } catch (err) {
            this.showError("Failed to submit work", err);
          }
        },
      ),
    );
  }

  // ── Shared handlers ───────────────────────────────────────────

  /**
   * Walk the user through connecting a new agent terminal.
   *
   * 1. Pick a role from bridge.json (or the hard-coded defaults).
   * 2. Enter a name for the agent.
   * 3. Call `terminalManager.createTerminal(...)`.
   */
  private async promptConnectAgent(): Promise<void> {
    try {
      const bridgeJson = await readBridgeJson();
      const roles: string[] =
        (bridgeJson.roles as string[]) ?? [
          "arquitecto",
          "desarrollador",
          "humano",
        ];

      const selectedRole = await vscode.window.showQuickPick(roles, {
        placeHolder: "Select agent role",
        title: "Connect Agent — Role",
      });
      if (!selectedRole) return;

      const agentName = await vscode.window.showInputBox({
        prompt: "Enter a name for this agent",
        placeHolder: "e.g., architect-01",
        title: "Connect Agent — Name",
      });
      if (!agentName) return;

      await this.terminalManager.createTerminal(
        agentName,
        agentName,
        selectedRole,
      );

      this.onStateChange();
      vscode.window.showInformationMessage(
        `Agent "${agentName}" connected with role "${selectedRole}"`,
      );
    } catch (err) {
      this.showError("Failed to connect agent", err);
    }
  }

  // ── Utilities ──────────────────────────────────────────────────

  /** Promise-based delay. */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /** Show a standardised error message to the user. */
  private showError(contextMessage: string, err: unknown): void {
    const detail =
      err instanceof Error ? err.message : String(err);
    vscode.window.showErrorMessage(`${contextMessage}: ${detail}`);
  }
}
