/**
 * Configuration module for Agent Bridge VSC extension.
 *
 * Reads settings from VSC configuration ("agent-bridge.*") and
 * falls back to a workspace bridge.json file if present.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";

import type { BridgeConfig } from "./types";

// ── Defaults ──────────────────────────────────────────────────────

const DEFAULTS: BridgeConfig = {
  port: 8765,
  dbPath: "bridge.db",
  autoStart: true,
  pollIntervalSeconds: 5,
  autoCreateTerminals: true,
};

// ── Helpers ───────────────────────────────────────────────────────

/**
 * Returns the full path to `bridge.json` in the workspace root,
 * or `null` when no workspace folder is open.
 */
export function getBridgeJsonPath(): string | null {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    return null;
  }
  return path.join(folders[0].uri.fsPath, "bridge.json");
}

/**
 * Reads and parses the workspace `bridge.json` file.
 *
 * @returns The parsed JSON value, or an empty object on failure.
 *          Never throws — warnings are logged via `console.warn`.
 */
export async function readBridgeJson(): Promise<Record<string, unknown>> {
  const jsonPath = getBridgeJsonPath();
  if (!jsonPath) {
    return {};
  }

  try {
    const raw = await fs.promises.readFile(jsonPath, "utf-8");
    const parsed = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      console.warn(
        `[agent-bridge] bridge.json is not a JSON object — ignoring`,
      );
      return {};
    }
    return parsed as Record<string, unknown>;
  } catch (err) {
    console.warn(
      `[agent-bridge] Could not read bridge.json: ${err instanceof Error ? err.message : String(err)}`,
    );
    return {};
  }
}

// ── Config loader ─────────────────────────────────────────────────

/**
 * Loads the effective BridgeConfig by merging three layers:
 *
 *  1. Hard-coded defaults
 *  2. Workspace `bridge.json` (if it exists)
 *  3. VSC configuration namespace `agent-bridge`
 *
 * VSC settings take highest precedence.
 */
export function loadConfig(): BridgeConfig {
  const config = vscode.workspace.getConfiguration("agent-bridge");

  // Start with defaults
  const result: BridgeConfig = { ...DEFAULTS };

  // ── bridge.json overlay ──────────────────────────────────────
  // We read synchronously here because loadConfig() is synchronous
  // and run at startup. The file read is local, so it's negligible.
  const jsonPath = getBridgeJsonPath();
  if (jsonPath) {
    try {
      const raw = fs.readFileSync(jsonPath, "utf-8");
      const json = JSON.parse(raw) as Record<string, unknown>;
      if (typeof json === "object" && json !== null && !Array.isArray(json)) {
        if (typeof json.port === "number") result.port = json.port;
        if (typeof json.dbPath === "string") result.dbPath = json.dbPath;
        if (typeof json.autoStart === "boolean") result.autoStart = json.autoStart;
        if (typeof json.pollIntervalSeconds === "number") result.pollIntervalSeconds = json.pollIntervalSeconds;
        if (typeof json.autoCreateTerminals === "boolean") result.autoCreateTerminals = json.autoCreateTerminals;
      }
    } catch (err) {
      console.warn(
        `[agent-bridge] Could not read bridge.json: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }

  // ── VSC settings overlay (highest priority) ──────────────────
  const port = config.inspect<number>("port");
  if (port && port.workspaceValue !== undefined) {
    result.port = port.workspaceValue;
  } else if (config.get<number>("port") !== undefined) {
    result.port = config.get<number>("port")!;
  }

  const dbPath = config.inspect<string>("dbPath");
  if (dbPath && dbPath.workspaceValue !== undefined) {
    result.dbPath = dbPath.workspaceValue;
  } else if (config.get<string>("dbPath") !== undefined) {
    result.dbPath = config.get<string>("dbPath")!;
  }

  const autoStart = config.inspect<boolean>("autoStart");
  if (autoStart && autoStart.workspaceValue !== undefined) {
    result.autoStart = autoStart.workspaceValue;
  } else if (config.get<boolean>("autoStart") !== undefined) {
    result.autoStart = config.get<boolean>("autoStart")!;
  }

  const pollIntervalSeconds = config.inspect<number>("pollIntervalSeconds");
  if (pollIntervalSeconds && pollIntervalSeconds.workspaceValue !== undefined) {
    result.pollIntervalSeconds = pollIntervalSeconds.workspaceValue;
  } else if (config.get<number>("pollIntervalSeconds") !== undefined) {
    result.pollIntervalSeconds = config.get<number>("pollIntervalSeconds")!;
  }

  const autoCreateTerminals = config.inspect<boolean>("autoCreateTerminals");
  if (autoCreateTerminals && autoCreateTerminals.workspaceValue !== undefined) {
    result.autoCreateTerminals = autoCreateTerminals.workspaceValue;
  } else if (config.get<boolean>("autoCreateTerminals") !== undefined) {
    result.autoCreateTerminals = config.get<boolean>("autoCreateTerminals")!;
  }

  return result;
}
