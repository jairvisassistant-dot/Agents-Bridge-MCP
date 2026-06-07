import * as vscode from 'vscode';
import { type ChatMessage, type ThreadInfo, type AgentInfo } from './types';

/**
 * WebView panel provider for the Agent Bridge chat interface.
 *
 * Creates a side panel with a full chat UI (dark-themed, matching VSCode)
 * where the user can send messages to agents, switch threads, and view
 * the conversation history.
 */
export class ChatWebviewProvider {
  public static readonly viewType = 'agent-bridge.chat';

  private panel: vscode.WebviewPanel | null = null;
  private messages: ChatMessage[] = [];
  private agents: AgentInfo[] = [];
  private threads: ThreadInfo[] = [];
  private currentThreadId: string | null = null;
  private currentSender = 'humano';

  constructor(
    private extensionUri: vscode.Uri,
    private onSendMessage: (
      sender: string,
      text: string,
      threadId?: string,
    ) => Promise<void>,
  ) {}

  /**
   * Show the chat panel, creating it if it does not already exist.
   */
  public show(): void {
    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.Beside);
      return;
    }

    this.panel = vscode.window.createWebviewPanel(
      ChatWebviewProvider.viewType,
      'Agent Bridge Chat',
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
  }

  /**
   * Replace the messages list and push the update to the webview.
   */
  public postMessages(messages: ChatMessage[]): void {
    this.messages = messages;
    this.postToWebview({ type: 'messages', messages });
  }

  /**
   * Replace the agents list and push the update to the webview.
   */
  public postAgents(agents: AgentInfo[]): void {
    this.agents = agents;
    this.postToWebview({ type: 'agents', agents });
  }

  /**
   * Push thread list update to the webview.
   */
  public postThreads(threads: ThreadInfo[]): void {
    this.threads = threads;
    this.postToWebview({ type: 'threads', threads });
  }

  /**
   * Dispose of the panel and clean up.
   */
  public dispose(): void {
    this.panel?.dispose();
    this.panel = null;
  }

  // ── Private helpers ──────────────────────────────────────────────

  private postToWebview(message: Record<string, unknown>): void {
    this.panel?.webview.postMessage(message);
  }

  private async handleMessage(message: Record<string, unknown>): Promise<void> {
    switch (message.command as string) {
      case 'send-message':
        await this.onSendMessage(
          (message.sender as string) ?? this.currentSender,
          message.text as string,
          (message.threadId as string) ?? this.currentThreadId ?? undefined,
        );
        break;

      case 'switch-thread':
        this.currentThreadId = (message.threadId as string) ?? null;
        break;

      case 'switch-sender':
        this.currentSender = (message.sender as string) ?? 'humano';
        break;

      case 'ready':
        this.postToWebview({ type: 'messages', messages: this.messages });
        this.postToWebview({ type: 'agents', agents: this.agents });
        this.postToWebview({ type: 'threads', threads: this.threads });
        break;
    }
  }

  // ── HTML template ───────────────────────────────────────────────

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
  <title>Agent Bridge Chat</title>
  <style>
    *, *::before, *::after {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    :root {
      --bg: var(--vscode-editor-background, #1e1e1e);
      --fg: var(--vscode-editor-foreground, #d4d4d4);
      --input-bg: var(--vscode-input-background, #3c3c3c);
      --input-fg: var(--vscode-input-foreground, #cccccc);
      --input-border: var(--vscode-input-border, #555555);
      --btn-bg: var(--vscode-button-background, #0e639c);
      --btn-fg: var(--vscode-button-foreground, #ffffff);
      --btn-hover: var(--vscode-button-hoverBackground, #1177bb);
      --list-hover: var(--vscode-list-hoverBackground, #2a2d2e);
      --badge-bg: var(--vscode-badge-background, #4d4d4d);
      --badge-fg: var(--vscode-badge-foreground, #ffffff);
      --sidebar-bg: var(--vscode-sideBar-background, #252526);
      --sidebar-fg: var(--vscode-sideBar-foreground, #cccccc);
      --font-family: var(--vscode-editor-font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif);
      --font-size: var(--vscode-editor-font-size, 13px);
      --focus-border: var(--vscode-focusBorder, #007fd4);
      --scrollbar-bg: var(--vscode-scrollbarSlider-background, #424242);
      --scrollbar-hover: var(--vscode-scrollbarSlider-hoverBackground, #555555);
      --border-color: var(--vscode-panel-border, #3c3c3c);
      --msg-self-bg: #2b5b84;
      --msg-other-bg: var(--vscode-textBlockQuote-background, #2a2d2e);
      --msg-self-fg: #ffffff;
      --msg-other-fg: var(--vscode-editor-foreground, #d4d4d4);
    }

    html, body {
      height: 100%;
      overflow: hidden;
      background: var(--bg);
      color: var(--fg);
      font-family: var(--font-family);
      font-size: var(--font-size);
    }

    /* ── Header ───────────────────────────────────────────── */

    .header {
      display: flex;
      gap: 8px;
      padding: 8px 12px;
      background: var(--sidebar-bg);
      border-bottom: 1px solid var(--border-color);
      align-items: center;
      flex-shrink: 0;
    }

    .header select {
      flex: 1;
      min-width: 0;
      background: var(--input-bg);
      color: var(--input-fg);
      border: 1px solid var(--input-border);
      border-radius: 2px;
      padding: 4px 6px;
      font-family: var(--font-family);
      font-size: calc(var(--font-size) - 1px);
      cursor: pointer;
      outline: none;
    }

    .header select:focus {
      border-color: var(--focus-border);
    }

    .header-label {
      font-size: calc(var(--font-size) - 2px);
      color: var(--sidebar-fg);
      opacity: 0.8;
      white-space: nowrap;
    }

    /* ── Messages ─────────────────────────────────────────── */

    .messages-container {
      flex: 1;
      overflow-y: auto;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-height: 0;
    }

    .messages-container::-webkit-scrollbar {
      width: 8px;
    }

    .messages-container::-webkit-scrollbar-thumb {
      background: var(--scrollbar-bg);
      border-radius: 4px;
    }

    .messages-container::-webkit-scrollbar-thumb:hover {
      background: var(--scrollbar-hover);
    }

    .message {
      max-width: 85%;
      padding: 8px 12px;
      border-radius: 6px;
      word-wrap: break-word;
      line-height: 1.5;
    }

    .message--self {
      align-self: flex-end;
      background: var(--msg-self-bg);
      color: var(--msg-self-fg);
      border-bottom-right-radius: 2px;
    }

    .message--other {
      align-self: flex-start;
      background: var(--msg-other-bg);
      color: var(--msg-other-fg);
      border-bottom-left-radius: 2px;
    }

    .message__sender {
      font-weight: 600;
      font-size: calc(var(--font-size) - 1px);
      margin-bottom: 2px;
    }

    .message__text {
      white-space: pre-wrap;
    }

    .message__text code {
      background: rgba(0, 0, 0, 0.3);
      padding: 1px 4px;
      border-radius: 3px;
      font-family: var(--vscode-editor-font-family, 'Consolas', 'Courier New', monospace);
      font-size: calc(var(--font-size) - 1px);
    }

    .message__text strong {
      font-weight: 700;
    }

    .message__text em {
      font-style: italic;
    }

    .message__timestamp {
      font-size: calc(var(--font-size) - 2px);
      opacity: 0.6;
      margin-top: 4px;
    }

    .empty-state {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--sidebar-fg);
      opacity: 0.5;
      font-style: italic;
      text-align: center;
      padding: 24px;
    }

    /* ── Input area ───────────────────────────────────────── */

    .input-area {
      display: flex;
      gap: 8px;
      padding: 8px 12px;
      background: var(--sidebar-bg);
      border-top: 1px solid var(--border-color);
      flex-shrink: 0;
      position: relative;
    }

    .input-area__field {
      flex: 1;
      min-width: 0;
      background: var(--input-bg);
      color: var(--input-fg);
      border: 1px solid var(--input-border);
      border-radius: 2px;
      padding: 6px 10px;
      font-family: var(--font-family);
      font-size: var(--font-size);
      outline: none;
      resize: none;
      line-height: 1.4;
    }

    .input-area__field:focus {
      border-color: var(--focus-border);
    }

    .input-area__field::placeholder {
      color: var(--input-fg);
      opacity: 0.5;
    }

    .input-area__send {
      background: var(--btn-bg);
      color: var(--btn-fg);
      border: none;
      border-radius: 2px;
      padding: 6px 16px;
      cursor: pointer;
      font-family: var(--font-family);
      font-size: var(--font-size);
      font-weight: 600;
      white-space: nowrap;
      display: flex;
      align-items: center;
      gap: 4px;
    }

    .input-area__send:hover {
      background: var(--btn-hover);
    }

    .input-area__send:active {
      opacity: 0.8;
    }

    /* ── @mention autocomplete ────────────────────────────── */

    .mention-dropdown {
      position: absolute;
      bottom: 100%;
      left: 12px;
      right: 12px;
      max-height: 180px;
      overflow-y: auto;
      background: var(--input-bg);
      border: 1px solid var(--input-border);
      border-radius: 4px 4px 0 0;
      display: none;
      z-index: 10;
      box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.3);
    }

    .mention-dropdown--visible {
      display: block;
    }

    .mention-dropdown__item {
      padding: 6px 12px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--input-fg);
    }

    .mention-dropdown__item:hover,
    .mention-dropdown__item--active {
      background: var(--list-hover);
    }

    .mention-dropdown__item-name {
      font-weight: 600;
    }

    .mention-dropdown__item-role {
      font-size: calc(var(--font-size) - 2px);
      opacity: 0.6;
    }

    .mention-dropdown__item-status {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }

    .status-online {
      background: #4ec9b0;
    }

    .status-idle {
      background: #dcdcaa;
    }

    .status-offline {
      background: #6e6e6e;
    }

    /* ── Layout ───────────────────────────────────────────── */

    #app {
      display: flex;
      flex-direction: column;
      height: 100vh;
      height: 100dvh;
    }
  </style>
</head>
<body>
  <div id="app">
    <!-- Header -->
    <div class="header">
      <span class="header-label">From:</span>
      <select id="sender-select" aria-label="Sender"></select>
      <select id="thread-select" aria-label="Thread">
        <option value="">-- No thread --</option>
      </select>
    </div>

    <!-- Messages -->
    <div class="messages-container" id="messages-container">
      <div class="empty-state" id="empty-state">
        No messages yet. Start a conversation!
      </div>
    </div>

    <!-- Autocomplete -->
    <div class="mention-dropdown" id="mention-dropdown"></div>

    <!-- Input -->
    <div class="input-area">
      <input
        type="text"
        class="input-area__field"
        id="message-input"
        placeholder="Type a message... (@ to mention)"
        autofocus
      />
      <button class="input-area__send" id="send-btn">Send</button>
    </div>
  </div>

  <script>
    (function () {
      'use strict';

      var vscode = acquireVsCodeApi();

      // ── DOM refs ──────────────────────────────────────────

      var container = document.getElementById('messages-container');
      var emptyState = document.getElementById('empty-state');
      var inputEl = document.getElementById('message-input');
      var sendBtn = document.getElementById('send-btn');
      var senderSelect = document.getElementById('sender-select');
      var threadSelect = document.getElementById('thread-select');
      var mentionDropdown = document.getElementById('mention-dropdown');

      // ── State ─────────────────────────────────────────────

      var allMessages = [];
      var allAgents = [];
      var allThreads = [];
      var currentSender = 'humano';
      var currentThreadId = null;

      // mention autocomplete state
      var mentionQuery = null;   // string after @ or null if no active mention
      var mentionStart = -1;     // cursor position where @ was typed
      var mentionIndex = -1;     // keyboard navigation index

      // ── Relative timestamps ──────────────────────────────

      function relativeTime(iso) {
        if (!iso) return '';
        var now = Date.now();
        var then = new Date(iso).getTime();
        var diffMs = now - then;
        if (diffMs < 0) return 'just now';

        var seconds = Math.floor(diffMs / 1000);
        if (seconds < 60) return 'just now';

        var minutes = Math.floor(seconds / 60);
        if (minutes < 60) return minutes + 'm ago';

        var hours = Math.floor(minutes / 60);
        if (hours < 24) return hours + 'h ago';

        var days = Math.floor(hours / 24);
        if (days < 7) return days + 'd ago';

        var date = new Date(iso);
        return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
      }

      // ── Markdown renderer ────────────────────────────────

      function escapeHtml(text) {
        return text
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;');
      }

      function renderMarkdown(text) {
        var safe = escapeHtml(text);
        return safe
          .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
          .replace(/\*(.+?)\*/g, '<em>$1</em>')
          .replace(/\x60(.+?)\x60/g, '<code>$1</code>')
          .replace(/\n/g, '<br>');
      }

      // ── Render messages ──────────────────────────────────

      function renderMessages(messages) {
        allMessages = messages;

        if (messages.length === 0) {
          container.innerHTML =
            '<div class="empty-state" id="empty-state">' +
            'No messages yet. Start a conversation!' +
            '</div>';
          return;
        }

        var html = '';
        for (var i = 0; i < messages.length; i++) {
          var msg = messages[i];
          var isSelf = msg.sender === currentSender;
          var cls = isSelf ? 'message message--self' : 'message message--other';
          var senderLabel = msg.sender === 'humano' ? 'You' : msg.sender;
          var textHtml = renderMarkdown(msg.text);
          var time = relativeTime(msg.timestamp);

          html += '<div class="' + cls + '">';
          html += '  <div class="message__sender">' + escapeHtml(senderLabel) + '</div>';
          html += '  <div class="message__text">' + textHtml + '</div>';
          html += '  <div class="message__timestamp">' + time + '</div>';
          html += '</div>';
        }

        container.innerHTML = html;
        scrollToBottom();
      }

      function scrollToBottom() {
        container.scrollTop = container.scrollHeight;
      }

      // ── Populate sender select ───────────────────────────

      function updateSenderSelect(agents) {
        senderSelect.innerHTML = '';
        var humanoOpt = document.createElement('option');
        humanoOpt.value = 'humano';
        humanoOpt.textContent = 'You (humano)';
        if (currentSender === 'humano') humanoOpt.selected = true;
        senderSelect.appendChild(humanoOpt);

        for (var i = 0; i < agents.length; i++) {
          var opt = document.createElement('option');
          opt.value = agents[i].name;
          opt.textContent = agents[i].name + ' (' + agents[i].role + ')';
          if (currentSender === agents[i].name) opt.selected = true;
          senderSelect.appendChild(opt);
        }
      }

      // ── Populate thread select ───────────────────────────

      function updateThreadSelect(threads) {
        threadSelect.innerHTML = '';
        var noneOpt = document.createElement('option');
        noneOpt.value = '';
        noneOpt.textContent = '-- No thread --';
        if (!currentThreadId) noneOpt.selected = true;
        threadSelect.appendChild(noneOpt);

        for (var i = 0; i < threads.length; i++) {
          var opt = document.createElement('option');
          opt.value = threads[i].id;
          opt.textContent = threads[i].title + ' [' + threads[i].status + ']';
          if (currentThreadId === threads[i].id) opt.selected = true;
          threadSelect.appendChild(opt);
        }
      }

      // ── @mention autocomplete ────────────────────────────

      function getMentionCandidates(query) {
        if (!query) return allAgents;
        var lower = query.toLowerCase();
        return allAgents.filter(function (a) {
          return a.name.toLowerCase().indexOf(lower) !== -1;
        });
      }

      function showMentionDropdown(candidates) {
        if (candidates.length === 0) {
          mentionDropdown.classList.remove('mention-dropdown--visible');
          mentionDropdown.innerHTML = '';
          return;
        }

        var html = '';
        for (var i = 0; i < candidates.length; i++) {
          var a = candidates[i];
          var activeClass = i === mentionIndex ? ' mention-dropdown__item--active' : '';
          var statusClass = 'status-' + a.status;
          html +=
            '<div class="mention-dropdown__item' + activeClass + '" data-index="' + i + '">' +
            '<span class="mention-dropdown__item-status ' + statusClass + '"></span>' +
            '<span class="mention-dropdown__item-name">' + escapeHtml(a.name) + '</span>' +
            '<span class="mention-dropdown__item-role">' + escapeHtml(a.role) + '</span>' +
            '</div>';
        }
        mentionDropdown.innerHTML = html;
        mentionDropdown.classList.add('mention-dropdown--visible');
      }

      function hideMentionDropdown() {
        mentionDropdown.classList.remove('mention-dropdown--visible');
        mentionDropdown.innerHTML = '';
        mentionQuery = null;
        mentionStart = -1;
        mentionIndex = -1;
      }

      function selectMention(name) {
        if (mentionStart === -1) return;
        var before = inputEl.value.substring(0, mentionStart);
        var after = inputEl.value.substring(inputEl.selectionStart);
        inputEl.value = before + '@' + name + ' ' + after;
        var newPos = mentionStart + name.length + 2; // +2 for @ and space
        inputEl.setSelectionRange(newPos, newPos);
        inputEl.focus();
        hideMentionDropdown();
      }

      function updateMention() {
        var pos = inputEl.selectionStart;
        var val = inputEl.value;
        var textBeforeCursor = val.substring(0, pos);

        // Find last @ that is not preceded by a word character
        var atIdx = -1;
        for (var i = textBeforeCursor.length - 1; i >= 0; i--) {
          if (textBeforeCursor[i] === '@') {
            // Must be at start or preceded by whitespace/punctuation
            if (i === 0 || /[\s()\[\]{}:;,."'!?]/.test(textBeforeCursor[i - 1])) {
              atIdx = i;
              break;
            }
          }
        }

        if (atIdx === -1) {
          hideMentionDropdown();
          return;
        }

        var query = textBeforeCursor.substring(atIdx + 1);

        // Only show if query has no spaces (mentions are single-word)
        if (query.indexOf(' ') !== -1) {
          hideMentionDropdown();
          return;
        }

        mentionQuery = query;
        mentionStart = atIdx;
        mentionIndex = 0;

        var candidates = getMentionCandidates(query);
        showMentionDropdown(candidates);
      }

      // ── Send message ─────────────────────────────────────

      function sendMessage() {
        var text = inputEl.value.trim();
        if (!text) return;

        vscode.postMessage({
          command: 'send-message',
          sender: currentSender,
          text: text,
          threadId: currentThreadId,
        });

        inputEl.value = '';
        inputEl.focus();
      }

      // ── Event listeners ──────────────────────────────────

      // From extension
      window.addEventListener('message', function (event) {
        var msg = event.data;
        switch (msg.type) {
          case 'messages':
            renderMessages(msg.messages);
            break;
          case 'agents':
            allAgents = msg.agents;
            updateSenderSelect(msg.agents);
            break;
          case 'threads':
            allThreads = msg.threads;
            updateThreadSelect(msg.threads);
            break;
        }
      });

      // Sender select
      senderSelect.addEventListener('change', function () {
        currentSender = senderSelect.value;
        vscode.postMessage({ command: 'switch-sender', sender: currentSender });
        // Re-render messages with new alignment
        renderMessages(allMessages);
      });

      // Thread select
      threadSelect.addEventListener('change', function () {
        currentThreadId = threadSelect.value || null;
        vscode.postMessage({ command: 'switch-thread', threadId: currentThreadId });
      });

      // Send on button click
      sendBtn.addEventListener('click', sendMessage);

      // Send on Enter (no Shift)
      inputEl.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          sendMessage();
        }
      });

      // Input events for @mention
      inputEl.addEventListener('input', function () {
        updateMention();
      });

      inputEl.addEventListener('keydown', function (e) {
        if (!mentionDropdown.classList.contains('mention-dropdown--visible')) return;

        var candidates = mentionDropdown.querySelectorAll('.mention-dropdown__item');

        if (e.key === 'ArrowDown') {
          e.preventDefault();
          mentionIndex = Math.min(mentionIndex + 1, candidates.length - 1);
          updateHighlight(candidates);
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          mentionIndex = Math.max(mentionIndex - 1, 0);
          updateHighlight(candidates);
        } else if (e.key === 'Enter' || e.key === 'Tab') {
          if (mentionIndex >= 0 && mentionIndex < candidates.length) {
            e.preventDefault();
            var name = candidates[mentionIndex].querySelector('.mention-dropdown__item-name').textContent;
            selectMention(name);
          }
        } else if (e.key === 'Escape') {
          hideMentionDropdown();
        }
      });

      function updateHighlight(candidates) {
        for (var i = 0; i < candidates.length; i++) {
          candidates[i].classList.toggle('mention-dropdown__item--active', i === mentionIndex);
        }
        // Scroll into view
        if (candidates[mentionIndex]) {
          candidates[mentionIndex].scrollIntoView({ block: 'nearest' });
        }
      }

      // Click on mention candidate
      mentionDropdown.addEventListener('mousedown', function (e) {
        var item = e.target.closest('.mention-dropdown__item');
        if (item) {
          e.preventDefault();
          var name = item.querySelector('.mention-dropdown__item-name').textContent;
          selectMention(name);
        }
      });

      // Hide dropdown on blur (with delay for click)
      inputEl.addEventListener('blur', function () {
        setTimeout(hideMentionDropdown, 200);
      });

      // ── Ready signal ─────────────────────────────────────

      vscode.postMessage({ command: 'ready' });
    })();
  </script>
</body>
</html>`;
  }
}
