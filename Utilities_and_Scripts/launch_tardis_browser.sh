#!/usr/bin/env bash
# ==============================================================================
# Lanzador Soberano de TARDIS Quantum Navigator (GUI + AI Search + Automation)
# ==============================================================================
set -e

SCRIPT_DIR="/home/timemachine/Escritorio/GODWORKS SYSTEM"
cd "$SCRIPT_DIR"

export DISPLAY="${DISPLAY:-:0}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export GDK_BACKEND="x11,wayland"
export WEBKIT_DISABLE_COMPOSITING_MODE=1

exec /usr/bin/python3 "$SCRIPT_DIR/tardis_browser_gui.py" "$@"
