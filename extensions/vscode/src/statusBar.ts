import * as vscode from 'vscode';
import { type ConnectionState, type HealthStatus } from './types';

/**
 * Status bar indicator for Agent Bridge connection state.
 *
 * Shows connection status at a glance with colour-coded backgrounds
 * and themed icons. Clicking the item triggers the relevant action
 * depending on the current state.
 */
export class BridgeStatusBar {
  private statusBarItem: vscode.StatusBarItem;

  constructor(context: vscode.ExtensionContext) {
    this.statusBarItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      100,
    );
    this.statusBarItem.command = 'agent-bridge.start';
    context.subscriptions.push(this.statusBarItem);
  }

/**
 * Update the status bar to reflect the current connection and health state.
 *
 * @param state         Connection state (disconnected, connecting, connected, etc.).
 * @param agentCount    Number of agents currently connected.
 * @param terminalCount Number of active terminal sessions.
 * @param health        Optional health status — shown when connected but unhealthy.
 * @param pendingCount  Optional count of undelivered mentions/terminal messages.
 */
update(
  state: ConnectionState,
  agentCount: number,
  terminalCount: number,
  health?: HealthStatus,
  pendingCount?: number,
): void {
    // ── Connected but unhealthy takes visual priority ──────────────
    if (state === 'connected' && health === 'unhealthy') {
      this.statusBarItem.text = '$(warning) Agent Bridge: Unhealthy';
      this.statusBarItem.tooltip =
        'Bridge process is alive but not responding \u2014 click to restart';
      this.statusBarItem.backgroundColor = new vscode.ThemeColor(
        'statusBarItem.warningBackground',
      );
      this.statusBarItem.command = 'agent-bridge.restart';
      this.statusBarItem.show();
      return;
    }

    switch (state) {
      case 'disconnected':
        this.statusBarItem.text = '$(debug-disconnect) Agent Bridge: Disconnected';
        this.statusBarItem.tooltip = 'Click to start the Agent Bridge server';
        this.statusBarItem.backgroundColor = new vscode.ThemeColor(
          'statusBarItem.errorBackground',
        );
        this.statusBarItem.command = 'agent-bridge.start';
        break;

      case 'connecting':
        this.statusBarItem.text = '$(loading~spin) Agent Bridge: Connecting\u2026';
        this.statusBarItem.tooltip = 'Connecting to the Agent Bridge server\u2026';
        this.statusBarItem.backgroundColor = new vscode.ThemeColor(
          'statusBarItem.warningBackground',
        );
        this.statusBarItem.command = undefined;
        break;

      case 'reconnecting':
        this.statusBarItem.text = '$(sync~spin) Agent Bridge: Reconnecting\u2026';
        this.statusBarItem.tooltip =
          'SSE connection lost \u2014 reconnecting to the server\u2026';
        this.statusBarItem.backgroundColor = new vscode.ThemeColor(
          'statusBarItem.warningBackground',
        );
        this.statusBarItem.command = undefined;
        break;

      case 'connected': {
        const healthSuffix = health === 'unknown' ? ' \u2014 checking\u2026' : '';
        const agents = agentCount === 1 ? '1 agent' : `${agentCount} agents`;
        const terminals =
          terminalCount === 1 ? '1 terminal' : `${terminalCount} terminals`;
        const pending =
          pendingCount && pendingCount > 0
            ? ` \u00b7 $(mail) ${pendingCount} pending`
            : '';
        this.statusBarItem.text = `$(hubot) Agent Bridge: ${agents} \u00b7 ${terminals}${pending}${healthSuffix}`;
        this.statusBarItem.tooltip = `${agentCount} agent(s), ${terminalCount} terminal(s) connected` +
          (pendingCount && pendingCount > 0 ? `, ${pendingCount} pending` : '');
        this.statusBarItem.backgroundColor = undefined;
        this.statusBarItem.command = 'agent-bridge.showMenu';
        break;
      }

      case 'error':
        this.statusBarItem.text = '$(error) Agent Bridge: Error';
        this.statusBarItem.tooltip = 'A connection error occurred \u2014 click to restart';
        this.statusBarItem.backgroundColor = new vscode.ThemeColor(
          'statusBarItem.errorBackground',
        );
        this.statusBarItem.command = 'agent-bridge.restart';
        break;
    }

    this.statusBarItem.show();
  }

  /** Dispose the underlying status bar item. */
  dispose(): void {
    this.statusBarItem.dispose();
  }
}
