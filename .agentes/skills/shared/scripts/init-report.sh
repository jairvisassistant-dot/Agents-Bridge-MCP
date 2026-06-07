#!/bin/bash
# init-report.sh — Inicializa directorios y resuelve PROJECT_ROOT
# Uso: source init-report.sh
# Salida: PROJECT_ROOT, AUDITS_DIR

set -euo pipefail

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
AUDITS_DIR="$PROJECT_ROOT/Otros/Info_Auditorias"
SCRIPTS_DIR="$PROJECT_ROOT/.agentes/skills/shared/scripts"

mkdir -p "$AUDITS_DIR"

export PROJECT_ROOT AUDITS_DIR SCRIPTS_DIR
