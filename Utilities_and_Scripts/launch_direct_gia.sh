#!/usr/bin/env bash
# ==============================================================================
# launch_direct_gia.sh - Lanzador de Conexión Directa Local GIA (Sin Servidor Web)
# GODWORKS SYSTEM v26.4 · Zero-Network-Port Pipe Runner
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.local/bin:$SCRIPT_DIR/.venv-linux/bin:$PATH"
export GIA_MODEL="${GIA_MODEL:-huihui_ai/llama3.1-8b-instruct-abliterated}"
export GIA_FORCE_PIPE="1"
export GIA_DIRECT="1"
export CUDA_VISIBLE_DEVICES="0"

PYTHON_BIN="$SCRIPT_DIR/.venv-linux/bin/python3"
if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(which python3)"
fi

TARGET_SCRIPT="$SCRIPT_DIR/gia_direct_channel.py"

# Si ya estamos en una terminal interactiva, ejecutar directamente
if [ -t 0 ]; then
    exec "$PYTHON_BIN" "$TARGET_SCRIPT" "$@"
fi

# Si se llama desde el escritorio (interfaz gráfica), abrir una ventana de terminal
if command -v ptyxis >/dev/null 2>&1; then
    exec ptyxis -T "GIA Conexión Directa (GPU)" --working-directory="$SCRIPT_DIR" -- "$PYTHON_BIN" "$TARGET_SCRIPT"
elif command -v x-terminal-emulator >/dev/null 2>&1; then
    exec x-terminal-emulator -T "GIA Conexión Directa (GPU)" -e "$PYTHON_BIN" "$TARGET_SCRIPT"
elif command -v gnome-terminal >/dev/null 2>&1; then
    exec gnome-terminal --title="GIA Conexión Directa (GPU)" -- "$PYTHON_BIN" "$TARGET_SCRIPT"
else
    exec "$PYTHON_BIN" "$TARGET_SCRIPT" "$@"
fi
