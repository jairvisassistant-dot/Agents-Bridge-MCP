import * as vscode from 'vscode';
import { type AgentInfo, type ConnectionState } from './types';

// ── Helpers ───────────────────────────────────────────────────────

/** Map an agent status to a ThemeIcon with the appropriate colour. */
function getAgentStatusIcon(status: AgentInfo['status']): vscode.ThemeIcon {
  const colourMap: Record<AgentInfo['status'], string> = {
    online: 'testing.iconPassed',
    idle: 'testing.iconSkipped',
    offline: 'testing.iconFailed',
  };
  return new vscode.ThemeIcon('circle-filled', new vscode.ThemeColor(colourMap[status]));
}

// ── Tree item ─────────────────────────────────────────────────────

export class AgentTreeItem extends vscode.TreeItem {
  constructor(
    public readonly agent: AgentInfo | null,
    public readonly type: 'agent' | 'header' | 'status',
  ) {
    let label: string;
    let collapsibleState: vscode.TreeItemCollapsibleState;

    if (type === 'header') {
      label = 'Agents';
      collapsibleState = vscode.TreeItemCollapsibleState.Collapsed;
    } else if (type === 'agent' && agent) {
      label =
        agent.name ||
        agent.role.charAt(0).toUpperCase() + agent.role.slice(1);
      collapsibleState = vscode.TreeItemCollapsibleState.None;
    } else {
      // Status items get their label set by the provider after construction.
      label = '';
      collapsibleState = vscode.TreeItemCollapsibleState.None;
    }

    super(label, collapsibleState);

    if (type === 'agent' && agent) {
      this.description = agent.id;
      this.contextValue = 'agent';
      this.iconPath = getAgentStatusIcon(agent.status);

      this.tooltip = new vscode.MarkdownString(
        `**Role:** ${agent.role}\n\n**Status:** ${agent.status}\n\n**Last Heartbeat:** ${agent.lastHeartbeat ?? 'N/A'}`,
      );
    }
  }
}

// ── Tree data provider ────────────────────────────────────────────

export class AgentTreeProvider implements vscode.TreeDataProvider<AgentTreeItem> {
  private _agents: AgentInfo[] = [];
  private _onDidChangeTreeData = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(private onStateChange: ConnectionState) {}

  /** Replace the agent list and connection state, then fire a tree refresh. */
  refresh(agents: AgentInfo[], state: ConnectionState): void {
    this._agents = agents;
    this.onStateChange = state;
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: AgentTreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: AgentTreeItem): AgentTreeItem[] {
    // ── Children of a parent node ──────────────────────────────
    if (element) {
      if (element.type === 'header') {
        return this._agents.map(a => new AgentTreeItem(a, 'agent'));
      }
      return [];
    }

    // ── Root level ─────────────────────────────────────────────
    const items: AgentTreeItem[] = [];

    // 1. Connection status
    const statusItem = new AgentTreeItem(null, 'status');
    if (this.onStateChange === 'connected') {
      statusItem.label =
        this._agents.length > 0 ? 'Connected' : 'No agents connected';
    } else if (this.onStateChange === 'connecting') {
      statusItem.label = 'Connecting...';
    } else if (this.onStateChange === 'error') {
      statusItem.label = 'Bridge connection error';
    } else {
      statusItem.label = "Bridge disconnected — run 'Agent Bridge: Start'";
    }
    items.push(statusItem);

    // 2. Agents header (only when connected and at least one agent)
    if (this.onStateChange === 'connected' && this._agents.length > 0) {
      items.push(new AgentTreeItem(null, 'header'));
    }

    return items;
  }
}
