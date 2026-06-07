import * as vscode from "vscode";

/**
 * Manages VS Code terminals that connect to the Agent Bridge.
 *
 * Each agent gets its own terminal with the `AGENT_BRIDGE_ID` environment
 * variable set, and an optional skill command is sent on creation to
 * bootstrap the agent's interactive session.
 */
export class TerminalManager {
  private terminals: Map<string, vscode.Terminal> = new Map();
  private closeDisposables: Map<string, vscode.Disposable> = new Map();
  private onStateChange: () => void;

  constructor(
    private bridgePort: number,
    private bridgeDbPath: string,
    onTerminalCountChanged: (count: number) => void,
  ) {
    this.onStateChange = () => onTerminalCountChanged(this.terminals.size);
  }

  // ── Public API ──────────────────────────────────────────────────

  /**
   * Create a new terminal for the given agent, or show the existing one.
   *
   * @param agentId     Unique agent identifier.
   * @param agentName   Human-readable agent name (shown in the terminal title).
   * @param role        Agent role – used to pick the default skill command.
   * @param skillCommand Optional skill command. When provided, the role
   *                     determines which skill to invoke. When omitted, a
   *                     simple connection echo is sent.
   * @returns The VS Code terminal for the agent.
   */
  async createTerminal(
    agentId: string,
    agentName: string,
    role: string,
    skillCommand?: string,
  ): Promise<vscode.Terminal> {
    // ── Edge case: terminal already exists → just reveal it ──
    const existing = this.terminals.get(agentId);
    if (existing) {
      existing.show();
      return existing;
    }

    let terminal: vscode.Terminal;

    try {
      terminal = vscode.window.createTerminal({
        name: `Agent: ${agentName} (${role})`,
        env: {
          ...process.env,
          AGENT_BRIDGE_ID: agentId,
        },
      });
    } catch (err) {
      console.warn(
        `[TerminalManager] Failed to create terminal for agent ${agentId}:`,
        err,
      );
      throw err;
    }

    this.terminals.set(agentId, terminal);

    // ── Listen for unexpected terminal close ──
    const closeDisposable = vscode.window.onDidCloseTerminal(
      (closedTerminal) => {
        if (closedTerminal === terminal) {
          this.cleanupAgent(agentId);
        }
      },
    );
    this.closeDisposables.set(agentId, closeDisposable);

    // ── Bootstrap the terminal with the appropriate skill command ──
    if (skillCommand) {
      if (role === "developer") {
        terminal.sendText("@dev.Skill\n");
      } else if (role === "architect") {
        terminal.sendText("@architect.Skill\n");
      } else {
        terminal.sendText(
          `echo "Connected as ${agentId} (role: ${role})"\n`,
        );
      }
    }

    this.onStateChange();
    return terminal;
  }

  /**
   * Disconnect a single agent by disposing its terminal.
   */
  disconnectAgent(agentId: string): void {
    const terminal = this.terminals.get(agentId);
    if (!terminal) return;

    this.cleanupAgent(agentId);
    terminal.dispose();
    this.onStateChange();
  }

  /**
   * Disconnect every connected agent.
   */
  disconnectAll(): void {
    for (const [agentId, terminal] of this.terminals) {
      this.closeDisposables.get(agentId)?.dispose();
      terminal.dispose();
    }
    this.terminals.clear();
    this.closeDisposables.clear();
    this.onStateChange();
  }

  /**
   * Return the number of currently connected agents.
   */
  getConnectedCount(): number {
    return this.terminals.size;
  }

  /**
   * Return the IDs of every connected agent.
   */
  getAgentIds(): string[] {
    return Array.from(this.terminals.keys());
  }

  /**
   * Send a text command to the specified agent's terminal.
   * No-op if the agent is not connected.
   */
  sendCommand(agentId: string, command: string): void {
    const terminal = this.terminals.get(agentId);
    if (terminal) {
      terminal.sendText(command);
    }
  }

  /**
   * Reveal / focus the terminal for the given agent.
   * No-op if the agent is not connected.
   */
  showTerminal(agentId: string): void {
    const terminal = this.terminals.get(agentId);
    if (terminal) {
      terminal.show();
    }
  }

  /**
   * Dispose every terminal and tear down all listeners.
   */
  dispose(): void {
    this.disconnectAll();
  }

  // ── Internal helpers ────────────────────────────────────────────

  /**
   * Remove an agent's terminal entry and its close listener **without**
   * disposing the terminal itself (called from the close event handler).
   */
  private cleanupAgent(agentId: string): void {
    this.terminals.delete(agentId);
    this.closeDisposables.get(agentId)?.dispose();
    this.closeDisposables.delete(agentId);
    this.onStateChange();
  }
}
