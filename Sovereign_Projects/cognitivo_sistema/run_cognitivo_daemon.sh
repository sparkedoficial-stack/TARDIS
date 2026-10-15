#!/usr/bin/env bash
# ==============================================================================
# run_cognitivo_daemon.sh - Lanzador Desacoplado del Sistema Cognitivo Soberano
# ==============================================================================
# Cumple estrictamente con la directiva de Aislamiento Total de Procesos en Segundo Plano:
# Redirección completa de streams (stdin=/dev/null, stdout/stderr a logs dedicados) y disown.

set -euo pipefail

BASE_DIR="/home/timemachine/cognitivo_sistema"
LOG_DIR="${BASE_DIR}/logs"
mkdir -p "${LOG_DIR}"

LOG_FILE="${LOG_DIR}/daemon_cognitivo.log"
PID_FILE="${LOG_DIR}/daemon_cognitivo.pid"

# Verificar si ya está en ejecución
if [ -f "${PID_FILE}" ]; then
    PID=$(cat "${PID_FILE}")
    if kill -0 "${PID}" 2>/dev/null; then
        echo "[INFO] Sistema Cognitivo ya está corriendo en segundo plano (PID: ${PID})."
        exit 0
    fi
fi

echo "[INICIANDO] Lanzando Sistema Cognitivo en modo 100% desacoplado..."
nohup /usr/bin/python3 "${BASE_DIR}/cli.py" daemon --interval 3600 </dev/null >>"${LOG_FILE}" 2>&1 &
NEW_PID=$!
disown "${NEW_PID}"
echo "${NEW_PID}" > "${PID_FILE}"

echo "[OK] Sistema Cognitivo ejecutándose en segundo plano (PID: ${NEW_PID})."
echo "[OK] Logs disponibles en: ${LOG_FILE}"
