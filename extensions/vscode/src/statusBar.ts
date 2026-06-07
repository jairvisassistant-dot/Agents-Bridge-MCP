import * as vscode from 'vscode';
import { type ConnectionState } from './types';

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
   * Update the status bar to reflect the current connection state.
   *
   * @param state        One of disconnected, connecting, connected, error.
   * @param agentCount   Number of agents currently connected (only relevant when connected).
   * @param terminalCount Number of active terminal sessions.
   */
  update(
    state: ConnectionState,
    agentCount: number,
    terminalCount: number,
  ): void {
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
        const agents = agentCount === 1 ? '1 agent' : `${agentCount} agents`;
        const terminals =
          terminalCount === 1 ? '1 terminal' : `${terminalCount} terminals`;
        this.statusBarItem.text = `$(hubot) Agent Bridge: ${agents} \u00b7 ${terminals}`;
        this.statusBarItem.tooltip = `${agentCount} agent(s), ${terminalCount} terminal(s) connected`;
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
