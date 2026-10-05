#!/usr/bin/env bash
# ==============================================================================
# TARDIS MASTER HUB - SCRIPT LANZADOR MAESTRO
# ==============================================================================
# Inicia y verifica el servicio backend TARDIS y despliega la aplicación de
# escritorio nativa con la interfaz unificada de todos los subsistemas.
# ==============================================================================

set -e

APP_DIR="/home/timemachine/Escritorio/GODWORKS SYSTEM"
cd "$APP_DIR"

SERVER_URL="http://REDACTED_IP:8757"
HUB_URL="$SERVER_URL/hub"
MAX_WAIT_SECONDS=15

# 1. Comprobar si el backend responde
is_online() {
    curl -s --connect-timeout 2 "$SERVER_URL/health" > /dev/null 2>&1
}

if ! is_online; then
    echo "[TARDIS Hub] El backend no responde. Intentando iniciar tardis.service..."
    if systemctl is-active --quiet tardis.service 2>/dev/null; then
        echo "[TARDIS Hub] El servicio ya estaba activo pero no respondía en el puerto. Reiniciando..."
        sudo systemctl restart tardis.service 2>/dev/null || systemctl restart tardis.service 2>/dev/null || true
    else
        sudo systemctl start tardis.service 2>/dev/null || systemctl start tardis.service 2>/dev/null || true
    fi

    # Esperar a que el backend esté listo
    elapsed=0
    while ! is_online; do
        sleep 1
        elapsed=$((elapsed + 1))
        if [ "$elapsed" -ge "$MAX_WAIT_SECONDS" ]; then
            echo "[TARDIS Hub] Advertencia: El servidor tardó más de lo esperado. Iniciando interfaz de todos modos..."
            break
        fi
    done
fi

echo "[TARDIS Hub] Lanzando Cabina de Mando Soberana..."
# Usar el intérprete de Python del sistema o del venv si tiene gi
if python3 -c "import gi" >/dev/null 2>&1; then
    PYTHON_EXEC="python3"
elif [ -f "$APP_DIR/.venv-linux/bin/python3" ]; then
    PYTHON_EXEC="$APP_DIR/.venv-linux/bin/python3"
else
    PYTHON_EXEC="python3"
fi

exec "$PYTHON_EXEC" "$APP_DIR/tardis_master_app.py" "$HUB_URL"
