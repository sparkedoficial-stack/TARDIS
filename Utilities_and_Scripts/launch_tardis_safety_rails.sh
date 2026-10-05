#!/usr/bin/env bash
# ==============================================================================
# TARDIS SAFETY RAILS - SCRIPT LANZADOR MAESTRO
# ==============================================================================
# Inicia y verifica el servicio backend TARDIS y despliega la aplicación de
# escritorio nativa con la consola de control de rieles de seguridad KAIJU.
# ==============================================================================

set -e

APP_DIR="/home/timemachine/Escritorio/GODWORKS SYSTEM"
cd "$APP_DIR"

SERVER_URL="http://REDACTED_IP:8757"
SAFETY_URL="$SERVER_URL/safety"
MAX_WAIT_SECONDS=10

# 1. Comprobar si el backend responde
is_online() {
    curl -s --connect-timeout 2 "$SERVER_URL/health" > /dev/null 2>&1
}

if ! is_online; then
    echo "[TARDIS Safety Rails] El backend no responde. Intentando iniciar servicio..."
    if systemctl is-active --quiet tardis.service 2>/dev/null; then
        sudo systemctl restart tardis.service 2>/dev/null || systemctl restart tardis.service 2>/dev/null || true
    else
        sudo systemctl start tardis.service 2>/dev/null || systemctl start tardis.service 2>/dev/null || true
    fi

    elapsed=0
    while ! is_online; do
        sleep 1
        elapsed=$((elapsed + 1))
        if [ "$elapsed" -ge "$MAX_WAIT_SECONDS" ]; then
            echo "[TARDIS Safety Rails] Advertencia: Servidor demorando. Abriendo consola de todos modos..."
            break
        fi
    done
fi

echo "[TARDIS Safety Rails] Desplegando Consola de Rieles de Seguridad KAIJU..."
if python3 -c "import gi" >/dev/null 2>&1; then
    PYTHON_EXEC="python3"
elif [ -f "$APP_DIR/.venv-linux/bin/python3" ]; then
    PYTHON_EXEC="$APP_DIR/.venv-linux/bin/python3"
else
    PYTHON_EXEC="python3"
fi

exec "$PYTHON_EXEC" "$APP_DIR/tardis_safety_app.py" "$SAFETY_URL"
