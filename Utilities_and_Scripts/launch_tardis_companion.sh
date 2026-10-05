#!/usr/bin/env bash
# ==============================================================================
# launch_tardis_companion.sh - Lanzador del Asistente Flotante sobre el SO
# ==============================================================================
# Inicia el widget translúcido Always-on-Top de TARDIS sobre todo el escritorio Linux
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

# Preferir WebKit con soporte Wayland/X11 y compositing
export WEBKIT_DISABLE_COMPOSITING_MODE=0

VENV_PYTHON="$DIR/.venv-linux/bin/python3"
if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="$(command -v python3)"
fi

echo "🌌 [Tardis] Iniciando Asistente Flotante sobre el Sistema Operativo..."
exec "$VENV_PYTHON" "$DIR/tardis_desktop_companion.py" "$@"
