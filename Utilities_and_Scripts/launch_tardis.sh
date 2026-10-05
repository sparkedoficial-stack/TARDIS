#!/usr/bin/env bash
# ==============================================================================
# launch_tardis.sh - Lanzador Oficial de la Aplicación Unificada Tardis
# ==============================================================================
# Inicia la interfaz de escritorio completa e integrada de Tardis (WebKitGTK nativo)
# ==============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

export PYTHONPATH="$DIR:$PYTHONPATH"
export PYTHONUNBUFFERED=1

# Configuración de aceleración gráfica y entorno de escritorio
if [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]; then
    export DISPLAY=:0
fi

# Preferir WebKit con soporte Wayland/X11
export WEBKIT_DISABLE_COMPOSITING_MODE=0

VENV_PYTHON="$DIR/.venv-linux/bin/python3"
if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="$(command -v python3)"
fi

echo "🌌 [Tardis] Iniciando aplicación unificada..."
exec "$VENV_PYTHON" "$DIR/tardis_app.py" "$@"
