#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# bundle-backend.sh — Build a standalone agent-bridge binary via PyInstaller.
#
# Usage:  bash build/bundle-backend.sh
#
# The resulting binary is placed in extensions/vscode/bin/ so `vsce package`
# includes it in the .vsix.  Platform-specific suffixes are handled by the
# bundling and resolution logic (agent-bridge / agent-bridge.exe).
#
# Hidden imports are listed explicitly because PyInstaller cannot always
# detect them (e.g. mcp, textual, uvicorn plugins).
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE_DIR="$ROOT_DIR/extensions/vscode/bin"
SPEC_NAME="agent-bridge.spec"

# ── Detect platform binary name ────────────────────────────────────
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    BINARY_NAME="agent-bridge.exe"
else
    BINARY_NAME="agent-bridge"
fi

echo "=== bundle-backend.sh ==="
echo "  Root:      $ROOT_DIR"
echo "  Output:    $BUNDLE_DIR/$BINARY_NAME"
echo "  Platform:  $OSTYPE"

# ── Ensure the bundle dir exists ───────────────────────────────────
mkdir -p "$BUNDLE_DIR"

# ── Run PyInstaller ────────────────────────────────────────────────
# --onefile       → single portable binary
# --name          → binary name (platform-specific)
# --distpath      → where to put the result
# --workpath      → temporary working directory (cleaned up by PyInstaller)
# --add-data      → bundle skill JSON files so the binary finds them at runtime
# --hidden-import → force inclusion of modules that PyInstaller may miss
#
# NOTE: --add-data uses the platform path separator (: on Linux/macOS, ; on Windows)

HIDDEN_IMPORTS=(
    --hidden-import "mcp"
    --hidden-import "mcp.server"
    --hidden-import "mcp.server.lowlevel"
    --hidden-import "mcp.server.stdio"
    --hidden-import "aiosqlite"
    --hidden-import "textual"
    --hidden-import "textual.app"
    --hidden-import "textual.widgets"
    --hidden-import "textual.containers"
    --hidden-import "textual.reactive"
    --hidden-import "httpx"
    --hidden-import "uvicorn"
    --hidden-import "uvicorn.loops"
    --hidden-import "uvicorn.loops.auto"
    --hidden-import "uvicorn.protocols"
    --hidden-import "uvicorn.protocols.http"
    --hidden-import "uvicorn.protocols.http.auto"
    --hidden-import "anyio"
    --hidden-import "anyio.streams"
    --hidden-import "anyio.to_thread"
)

# Add skill JSON files so the bundled binary can load skill templates at runtime.
# This is required for the hot-reload / builtin skills feature.
SKILL_SRC="$ROOT_DIR/src/agent_bridge/skills"
DATA_SEP=":"

pyinstaller \
    --onefile \
    --name "$BINARY_NAME" \
    --distpath "$BUNDLE_DIR" \
    --workpath "$ROOT_DIR/build/.pyinstaller-work" \
    --add-data "$SKILL_SRC${DATA_SEP}agent_bridge/skills" \
    "${HIDDEN_IMPORTS[@]}" \
    "$ROOT_DIR/src/agent_bridge/__main__.py"

# ── Clean up build artifacts (keep only the binary) ────────────────
rm -rf "$ROOT_DIR/build/.pyinstaller-work"
rm -f "$ROOT_DIR/$SPEC_NAME"

echo "✅ Bundled $BINARY_NAME ($(du -h "$BUNDLE_DIR/$BINARY_NAME" | cut -f1))"
