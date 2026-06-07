/**
 * Agent Dashboard — real-time status Webview panel.
 *
 * Shows the bridge connection state, health status, and a card for
 * every registered agent with live indicators (🟢🟡🔴), last heartbeat,
 * terminal status, and quick-action buttons.
 *
 * Data is pushed from the extension's poll cycle via `postMessage`.
 */

import * as vscode from "vscode";
import { type AgentInfo, type DashboardData, type ConnectionState, type HealthStatus } from "./types";

// ── Provider ────────────────────────────────────────────────────────

export class AgentDashboardProvider {
  public static readonly viewType = "agent-bridge.dashboard";

  private panel: vscode.WebviewPanel | null = null;
  private _data: DashboardData = {
    agents: [],
    connectionState: "disconnected",
    health: "unknown",
    terminalCount: 0,
  };

  constructor(
    private extensionUri: vscode.Uri,
    private onCommand: (command: string, args?: Record<string, string>) => void,
  ) {}

  // ── Public API ──────────────────────────────────────────────────

  /** Show or reveal the dashboard panel. */
  show(): void {
    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.Beside);
      return;
    }

    this.panel = vscode.window.createWebviewPanel(
      AgentDashboardProvider.viewType,
      "Agent Bridge — Dashboard",
      vscode.ViewColumn.Beside,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
      },
    );

    this.panel.webview.onDidReceiveMessage(
      this.handleMessage.bind(this),
    );

    this.panel.onDidDispose(() => {
      this.panel = null;
    });

    this.panel.webview.html = this.getHtmlContent();
    this.pushUpdate();
  }

  /** Push fresh data to the webview. */
  update(data: DashboardData): void {
    this._data = data;
    this.pushUpdate();
  }

  /** Dispose of the panel. */
  dispose(): void {
    this.panel?.dispose();
    this.panel = null;
  }

  // ── Private ────────────────────────────────────────────────────

  private pushUpdate(): void {
    if (!this.panel) return;
    this.postToWebview({ type: "update", data: this._data });
  }

  private postToWebview(message: Record<string, unknown>): void {
    this.panel?.webview.postMessage(message);
  }

  private async handleMessage(message: Record<string, unknown>): Promise<void> {
    const cmd = message.command as string;
    switch (cmd) {
      case "focus-terminal":
        this.onCommand("focus-terminal", message as Record<string, string>);
        break;
      case "disconnect-agent":
        this.onCommand("disconnect-agent", message as Record<string, string>);
        break;
      case "open-chat":
        this.onCommand("open-chat", message as Record<string, string>);
        break;
      case "ready":
        this.pushUpdate();
        break;
    }
  }

  // ── HTML template ─────────────────────────────────────────────

  private getHtmlContent(): string {
    return /* html */ `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta
    http-equiv="Content-Security-Policy"
    content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';"
  />
  <title>Agent Bridge Dashboard</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg: var(--vscode-editor-background, #1e1e1e);
      --fg: var(--vscode-editor-foreground, #d4d4d4);
      --sidebar-bg: var(--vscode-sideBar-background, #252526);
      --sidebar-fg: var(--vscode-sideBar-foreground, #cccccc);
      --input-bg: var(--vscode-input-background, #3c3c3c);
      --btn-bg: var(--vscode-button-background, #0e639c);
      --btn-fg: var(--vscode-button-foreground, #ffffff);
      --btn-hover: var(--vscode-button-hoverBackground, #1177bb);
      --btn-secondary-bg: var(--vscode-button-secondaryBackground, #3a3d41);
      --btn-secondary-fg: var(--vscode-button-secondaryForeground, #cccccc);
      --badge-bg: var(--vscode-badge-background, #4d4d4d);
      --badge-fg: var(--vscode-badge-foreground, #ffffff);
      --border-color: var(--vscode-panel-border, #3c3c3c);
      --list-hover: var(--vscode-list-hoverBackground, #2a2d2e);
      --font-family: var(--vscode-editor-font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif);
      --font-size: var(--vscode-editor-font-size, 13px);
      --focus-border: var(--vscode-focusBorder, #007fd4);
      --error-fg: #f48771;
      --warning-fg: #dcdcaa;
      --success-fg: #4ec9b0;
    }

    html, body {
      height: 100%;
      overflow: hidden;
      background: var(--bg);
      color: var(--fg);
      font-family: var(--font-family);
      font-size: var(--font-size);
    }

    #app {
      display: flex;
      flex-direction: column;
      height: 100vh;
      height: 100dvh;
      padding: 12px;
      gap: 12px;
      overflow-y: auto;
    }

    /* ── Bridge status header ─────────────────────────────── */

    .bridge-header {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px 14px;
      background: var(--sidebar-bg);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      flex-shrink: 0;
    }

    .bridge-status-icon {
      width: 12px;
      height: 12px;
      border-radius: 50%;
      flex-shrink: 0;
    }

    .bridge-status-icon.connected { background: var(--success-fg); }
    .bridge-status-icon.connecting,
    .bridge-status-icon.reconnecting { background: var(--warning-fg); }
    .bridge-status-icon.disconnected,
    .bridge-status-icon.error { background: var(--error-fg); }
    .bridge-status-icon.unhealthy { background: var(--warning-fg); }

    .bridge-info {
      flex: 1;
      min-width: 0;
    }

    .bridge-info__title {
      font-weight: 600;
      font-size: calc(var(--font-size) + 1px);
    }

    .bridge-info__detail {
      font-size: calc(var(--font-size) - 1px);
      opacity: 0.7;
      margin-top: 2px;
    }

    .bridge-actions {
      display: flex;
      gap: 6px;
    }

    /* ── Agent cards ──────────────────────────────────────── */

    .section-title {
      font-weight: 600;
      font-size: calc(var(--font-size) + 1px);
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .section-title .count {
      font-weight: 400;
      font-size: var(--font-size);
      opacity: 0.6;
    }

    .agent-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .agent-card {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px 14px;
      background: var(--sidebar-bg);
      border: 1px solid var(--border-color);
      border-radius: 6px;
    }

    .agent-status-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex-shrink: 0;
    }

    .agent-status-dot.online { background: var(--success-fg); }
    .agent-status-dot.idle { background: var(--warning-fg); }
    .agent-status-dot.offline { background: #6e6e6e; }

    .agent-info {
      flex: 1;
      min-width: 0;
    }

    .agent-info__name {
      font-weight: 600;
    }

    .agent-info__meta {
      font-size: calc(var(--font-size) - 1px);
      opacity: 0.7;
      margin-top: 1px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .agent-info__meta span {
      white-space: nowrap;
    }

    .terminal-badge {
      display: inline-block;
      padding: 1px 6px;
      border-radius: 3px;
      font-size: calc(var(--font-size) - 2px);
      font-weight: 600;
    }

    .terminal-badge.connected {
      background: var(--success-fg);
      color: var(--bg);
    }

    .agent-actions {
      display: flex;
      gap: 4px;
      flex-shrink: 0;
    }

    /* ── Buttons ──────────────────────────────────────────── */

    .btn {
      background: var(--btn-secondary-bg);
      color: var(--btn-secondary-fg);
      border: none;
      border-radius: 3px;
      padding: 4px 10px;
      font-family: var(--font-family);
      font-size: calc(var(--font-size) - 1px);
      cursor: pointer;
      white-space: nowrap;
    }

    .btn:hover {
      filter: brightness(1.2);
    }

    .btn--primary {
      background: var(--btn-bg);
      color: var(--btn-fg);
    }

    .btn--primary:hover {
      background: var(--btn-hover);
    }

    .btn--icon {
      background: transparent;
      padding: 2px 6px;
      font-size: var(--font-size);
    }

    .btn--icon:hover {
      background: var(--list-hover);
    }

    .btn--danger {
      color: var(--error-fg);
    }

    .btn--danger:hover {
      background: rgba(244, 135, 113, 0.15);
    }

    /* ── Empty state ──────────────────────────────────────── */

    .empty-state {
      text-align: center;
      padding: 32px 16px;
      opacity: 0.5;
      font-style: italic;
    }

    .empty-state__icon {
      font-size: 32px;
      margin-bottom: 8px;
    }

    /* ── Scrollbar ────────────────────────────────────────── */

    ::-webkit-scrollbar { width: 8px; }
    ::-webkit-scrollbar-thumb {
      background: var(--vscode-scrollbarSlider-background, #424242);
      border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
      background: var(--vscode-scrollbarSlider-hoverBackground, #555);
    }
  </style>
</head>
<body>
  <div id="app">
    <!-- Bridge status -->
    <div class="bridge-header" id="bridge-header">
      <div class="bridge-status-icon" id="bridge-status-icon"></div>
      <div class="bridge-info">
        <div class="bridge-info__title" id="bridge-title">Disconnected</div>
        <div class="bridge-info__detail" id="bridge-detail">Start the bridge to see agent status</div>
      </div>
      <div class="bridge-actions">
        <button class="btn btn--primary" id="btn-start">Start</button>
      </div>
    </div>

    <!-- Section: Agents -->
    <div>
      <div class="section-title">
        Agents <span class="count" id="agent-count"></span>
      </div>
      <div class="agent-list" id="agent-list"></div>
    </div>
  </div>

  <script>
    (function () {
      'use strict';

      var vscode = acquireVsCodeApi();

      // ── DOM refs ─────────────────────────────────────────

      var bridgeIcon = document.getElementById('bridge-status-icon');
      var bridgeTitle = document.getElementById('bridge-title');
      var bridgeDetail = document.getElementById('bridge-detail');
      var btnStart = document.getElementById('btn-start');
      var agentCount = document.getElementById('agent-count');
      var agentList = document.getElementById('agent-list');

      var state = {
        connectionState: 'disconnected',
        health: 'unknown',
      };

      // ── Helpers ──────────────────────────────────────────

      function relativeTime(iso) {
        if (!iso) return 'never';
        var now = Date.now();
        var then = new Date(iso).getTime();
        if (isNaN(then)) return 'unknown';
        var diffMs = now - then;
        if (diffMs < 0) return 'just now';
        var seconds = Math.floor(diffMs / 1000);
        if (seconds < 60) return seconds + 's ago';
        var minutes = Math.floor(seconds / 60);
        if (minutes < 60) return minutes + 'm ago';
        var hours = Math.floor(minutes / 60);
        if (hours < 24) return hours + 'h ago';
        var days = Math.floor(hours / 24);
        return days + 'd ago';
      }

      // ── Render bridge header ────────────────────────────

      function getBridgeLabel(cs, health) {
        if (health === 'unhealthy') return { icon: 'unhealthy', title: 'Bridge Unhealthy', detail: 'Process is alive but not responding — click Restart' };
        switch (cs) {
          case 'connected':    return { icon: 'connected',    title: 'Bridge Connected',     detail: '' };
          case 'connecting':   return { icon: 'connecting',   title: 'Connecting\u2026',      detail: 'Starting the bridge server\u2026' };
          case 'reconnecting': return { icon: 'reconnecting', title: 'Reconnecting\u2026',     detail: 'SSE stream dropped — reconnecting\u2026' };
          case 'disconnected': return { icon: 'disconnected', title: 'Bridge Disconnected',  detail: 'Click Start to launch the bridge server' };
          case 'error':        return { icon: 'error',        title: 'Bridge Error',          detail: 'A connection error occurred' };
          default:             return { icon: 'disconnected', title: 'Unknown',              detail: '' };
        }
      }

      function renderHeader(data) {
        var cs = data.connectionState;
        var health = data.health;
        var label = getBridgeLabel(cs, health);
        var pidText = data.pid ? 'PID: ' + data.pid : '';
        var terminalText = data.terminalCount > 0 ? data.terminalCount + ' terminal(s)' : '';
        var detailParts = [label.detail, pidText, terminalText].filter(Boolean);
        var detail = detailParts.join(' \\u00b7 ');

        bridgeIcon.className = 'bridge-status-icon ' + label.icon;
        bridgeTitle.textContent = label.title;
        bridgeDetail.textContent = detail;

        // Update button based on state
        if (cs === 'disconnected' || cs === 'error') {
          btnStart.textContent = 'Start';
          btnStart.className = 'btn btn--primary';
          btnStart.style.display = '';
        } else if (cs === 'connected' && health === 'unhealthy') {
          btnStart.textContent = 'Restart';
          btnStart.className = 'btn btn--primary';
          btnStart.style.display = '';
        } else if (cs === 'connected') {
          btnStart.style.display = 'none';
        } else {
          btnStart.style.display = 'none';
        }
      }

      // ── Render agents ───────────────────────────────────

      function escapeHtml(text) {
        return String(text)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;');
      }

      function renderAgents(agents, terminalCount) {
        agentList.innerHTML = '';

        if (agents.length === 0) {
          agentCount.textContent = '';
          agentList.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state__icon">🤖</div>' +
            'No agents connected yet. Open a terminal to connect one.' +
            '</div>';
          return;
        }

        agentCount.textContent = '(' + agents.length + ')';

        for (var i = 0; i < agents.length; i++) {
          var a = agents[i];
          var hasTerminal = terminalCount > 0;
          var timeAgo = relativeTime(a.lastHeartbeat);
          var statusLabel = a.status.charAt(0).toUpperCase() + a.status.slice(1);

          var card = document.createElement('div');
          card.className = 'agent-card';

          card.innerHTML =
            '<div class="agent-status-dot ' + a.status + '" title="' + statusLabel + '"></div>' +
            '<div class="agent-info">' +
              '<div class="agent-info__name">' + escapeHtml(a.name || a.id) + '</div>' +
              '<div class="agent-info__meta">' +
                '<span>' + escapeHtml(a.role) + '</span>' +
                '<span>' + statusLabel + '</span>' +
                '<span>' + timeAgo + '</span>' +
                '<span class="terminal-badge ' + (hasTerminal ? 'connected' : '') + '">' +
                  (hasTerminal ? 'Terminal' : 'No terminal') +
                '</span>' +
              '</div>' +
            '</div>' +
            '<div class="agent-actions">' +
              '<button class="btn btn--icon focus-btn" data-id="' + escapeHtml(a.id) + '" title="Focus terminal">\\u{1F4BB}</button>' +
              '<button class="btn btn--icon btn--danger disconnect-btn" data-id="' + escapeHtml(a.id) + '" title="Disconnect">\\u2716</button>' +
            '</div>';

          agentList.appendChild(card);
        }

        // ── Attach event listeners ─────────────────────────
        agentList.querySelectorAll('.focus-btn').forEach(function (btn) {
          btn.addEventListener('click', function () {
            vscode.postMessage({ command: 'focus-terminal', agentId: btn.dataset.id });
          });
        });

        agentList.querySelectorAll('.disconnect-btn').forEach(function (btn) {
          btn.addEventListener('click', function () {
            vscode.postMessage({ command: 'disconnect-agent', agentId: btn.dataset.id });
          });
        });
      }

      // ── Main update handler ─────────────────────────────

      function updateDashboard(data) {
        state.connectionState = data.connectionState;
        state.health = data.health;
        renderHeader(data);
        renderAgents(data.agents, data.terminalCount);
      }

      // ── Event listeners ─────────────────────────────────

      // Messages from the extension
      window.addEventListener('message', function (event) {
        var msg = event.data;
        if (msg.type === 'update') {
          updateDashboard(msg.data);
        }
      });

      // Button: Start / Restart
      btnStart.addEventListener('click', function () {
        if (state.connectionState === 'disconnected' || state.connectionState === 'error') {
          vscode.postMessage({ command: 'start-bridge' });
        } else if (state.health === 'unhealthy') {
          vscode.postMessage({ command: 'restart-bridge' });
        }
      });

      // ── Ready signal ────────────────────────────────────
      vscode.postMessage({ command: 'ready' });
    })();
  </script>
</body>
</html>`;
  }
}
