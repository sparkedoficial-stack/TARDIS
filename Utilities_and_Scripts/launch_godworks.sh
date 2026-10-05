#!/usr/bin/env bash
# ==============================================================================
# launch_godworks.sh - Acceso Rápido y Lanzador de GODWORKS SYSTEM v26.4
# ==============================================================================
set -e

SCRIPT_DIR="/home/timemachine/Escritorio/GODWORKS SYSTEM"
cd "$SCRIPT_DIR"

if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env" 2>/dev/null || true
    set +a
fi

export PATH="$HOME/.local/bin:$SCRIPT_DIR/.venv-linux/bin:$PATH"
export GIA_MODEL="${GIA_MODEL:-TARDIS-NEURAL-SPACE-KAIJU}"
export GIA_FORCE_PIPE="1"
export GIA_DIRECT="1"
TOKEN="${GIA_AUTH_TOKEN:-${GIA_TOKEN:-}}"
DASHBOARD_URL="http://REDACTED_IP:8757/?key=$TOKEN"

# Comprobar si el servidor en puerto 8757 ya responde
if wget -q --spider --timeout=2 "http://REDACTED_IP:8757/api/status" 2>/dev/null || ss -tulpn | grep -q ":8757 "; then
    notify-send "GODWORKS SYSTEM v26.4" "Sistema en línea. Abriendo Dashboard Web..." -i godworks 2>/dev/null || true
    xdg-open "$DASHBOARD_URL" >/dev/null 2>&1 &
    exit 0
fi

# Si no está en ejecución, arrancar Suite en segundo plano y abrir navegador
notify-send "GODWORKS SYSTEM v26.4" "Iniciando Suite Soberana y abriendo Dashboard..." -i godworks 2>/dev/null || true

nohup "$SCRIPT_DIR/.venv-linux/bin/python3" "$SCRIPT_DIR/omni_temporal_control.py" --port 8757 --no-window > /home/timemachine/vw-control/omni.log 2>&1 &
nohup "$SCRIPT_DIR/.venv-linux/bin/python3" "$SCRIPT_DIR/supervisor.py" > /home/timemachine/vw-control/supervisor_stdout.log 2>&1 &

# Esperar brevemente a que levante el puerto
for i in {1..10}; do
    if ss -tulpn | grep -q ":8757 "; then
        break
    fi
    sleep 0.5
done

xdg-open "$DASHBOARD_URL" >/dev/null 2>&1 &
