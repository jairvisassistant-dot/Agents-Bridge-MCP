#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════
# Agent Bridge — ARRANQUE TODO-EN-UNO
# ═══════════════════════════════════════════════════════════════
# Uso:
#   ./start.sh              →  setup + servidor + TUI
#   ./start.sh --headless   →  setup + servidor solo (sin TUI)
#   ./start.sh --agent      →  conecta este terminal como agente OpenCode
# ═══════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

MODE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --headless) MODE="headless"; shift ;;
    --agent)    MODE="agent"; shift ;;
    *)          echo "❌ Opción desconocida: $1"; exit 1 ;;
  esac
done

# ── 1. Verificar prerequisitos ─────────────────────────────────
echo "🔍 Verificando requisitos..."

if ! command -v python3 &>/dev/null; then
  echo "❌ Python3 no está instalado. Instalalo primero."
  exit 1
fi

PY_VERSION=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
if [[ $(echo "$PY_VERSION < 3.12" | bc -l) -eq 1 ]]; then
  echo "❌ Se necesita Python 3.12+. Tenés: $(python3 --version)"
  exit 1
fi

if ! command -v uv &>/dev/null; then
  echo "❌ uv no está instalado. Instalalo con: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

echo "  ✅ Python $(python3 --version | cut -d' ' -f2)"
echo "  ✅ uv $(uv --version | cut -d' ' -f2)"

# ── 2. Sincronizar dependencias ────────────────────────────────
echo "📦 Sincronizando dependencias..."
uv sync 2>&1 | tail -1 || { echo "❌ uv sync falló"; exit 1; }
echo "  ✅ Dependencias listas"

# ── 3. Instalar agent-bridge globalmente si no está ────────────
if ! command -v agent-bridge &>/dev/null; then
  echo "📦 Instalando agent-bridge..."
  uv tool install --editable . 2>&1 | tail -1
  echo "  ✅ agent-bridge instalado"
else
  echo "  ✅ agent-bridge ya instalado"
fi

# ── 4. Inicializar bridge.json si no existe ────────────────────
if [ ! -f bridge.json ]; then
  echo "⚙️  Inicializando configuración..."
  agent-bridge init 2>&1 | head -5
  echo "  ✅ Configuración creada"
else
  echo "  ✅ bridge.json ya existe"
fi

# ── Modo agente: conectar este terminal como OpenCode ─────────
if [ "$MODE" = "agent" ]; then
  echo ""
  echo "═══════════════════════════════════════════════════════"
  echo "  Conectando como OpenCode (Desarrollador)..."
  echo "  Asegurate de tener agent-bridge start corriendo"
  echo "  en OTRA terminal."
  echo "═══════════════════════════════════════════════════════"
  echo ""
  exec AGENT_BRIDGE_ID=opencode-1 agent-bridge --transport sse --host 127.0.0.1 --port 8765
fi

# ── 5. Arrancar servidor ───────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  🚀 Agent Bridge arrancando..."
if [ "$MODE" = "headless" ]; then
  echo "  Modo: solo servidor (headless)"
else
  echo "  Modo: servidor + TUI"
fi
echo "  Puerto: 8765"
echo "  DB: bridge.db"
echo ""
echo "  ▶ Terminal 2 → OpenCode:  @dev.Skill"
echo "  ▶ Terminal 3 → Claude:    @architect.Skill"
echo "═══════════════════════════════════════════════════════"
echo ""

if [ "$MODE" = "headless" ]; then
  exec .venv/bin/python -m agent_bridge start --headless --port 8765
else
  exec .venv/bin/python -m agent_bridge start --port 8765
fi
