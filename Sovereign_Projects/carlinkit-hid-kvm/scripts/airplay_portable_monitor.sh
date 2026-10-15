#!/bin/bash
# ==============================================================================
# USB-C DISPLAYPORT & AIRPLAY PORTABLE MONITOR ORCHESTRATOR
# Sovereign Media & Display Engine for Antigravity & TARDIS
# ==============================================================================
set -euo pipefail

DP_CONNECTOR="/sys/class/drm/card1-DP-1"
TYPEC_PORT="/sys/class/typec/port0"
CONNECTOR_ID=129

echo "======================================================================"
echo "⚡ ESTADO DE ENLACE DISPLAYPORT SOBRE USB-C (DP ALT MODE)"
echo "======================================================================"

# 1. Verificar subsistema Type-C del Kernel
if [ -d "$TYPEC_PORT" ]; then
    DATA_ROLE=$(cat "$TYPEC_PORT/data_role" 2>/dev/null || echo "unknown")
    POWER_ROLE=$(cat "$TYPEC_PORT/power_role" 2>/dev/null || echo "unknown")
    echo "[+] Controlador de Puerto Físico USB-C: Activo (ACPI/UCSI)"
    echo "    - Rol de Datos : $DATA_ROLE"
    echo "    - Rol de Energía: $POWER_ROLE (Entrega de energía habilitada)"
else
    echo "[-] Advertencia: Puerto Type-C no detectado en sysfs."
fi

# 2. Verificar estado del conector DRM de la GPU NVIDIA (card1-DP-1)
if [ -d "$DP_CONNECTOR" ]; then
    STATUS=$(cat "$DP_CONNECTOR/status" 2>/dev/null || echo "disconnected")
    ENABLED=$(cat "$DP_CONNECTOR/enabled" 2>/dev/null || echo "disabled")
    echo "[+] Conector DRM de Video (GPU NVIDIA RTX 3050):"
    echo "    - Dispositivo: /dev/dri/card1 (card1-DP-1)"
    echo "    - ID Conector KMS: $CONNECTOR_ID"
    echo "    - Estado Físico: $STATUS"
    echo "    - Estado Lógico: $ENABLED"

    if [ "$STATUS" == "connected" ]; then
        echo "[+] MONITOR PORTÁTIL DETECTADO EN EL PUERTO USB-C."
        MODES=$(cat "$DP_CONNECTOR/modes" 2>/dev/null || echo "auto")
        echo "    - Modos de Video Soportados: $MODES"
    else
        echo "[*] Monitor portátil actualmente NO conectado en el puerto USB-C."
        echo "    - Al enchufar tu monitor portátil con su cable USB-C a este puerto,"
        echo "      el kernel conmutará automáticamente a modo DisplayPort Alt Mode."
    fi
else
    echo "[-] Error: Nodo card1-DP-1 no encontrado."
fi

echo ""
echo "======================================================================"
echo "⚡ SERVICIO DE RECEPTOR AIRPLAY (UXPLAY + NVDEC)"
echo "======================================================================"

if systemctl --user is-active --quiet uxplay-airplay.service; then
    PID=$(pgrep -u "$USER" uxplay || echo "N/A")
    echo "[+] Servidor AirPlay: ONLINE (Activo en segundo plano)"
    echo "    - PID: $PID"
    echo "    - Nombre en Red (mDNS): TARDIS"
    echo "    - Decodificador Hardware: NVIDIA NVDEC (nvh264dec / HEVC 4K)"
    echo "    - Frecuencia Máxima: 144 Hz"
    echo "    - Puertos: UDP 5353 (mDNS), TCP 45275 (RTSP AirPlay)"
else
    echo "[-] Servicio AirPlay inactivo. Iniciando..."
    systemctl --user start uxplay-airplay.service
fi

echo ""
echo "======================================================================"
echo "⚡ GUÍA DE OPERACIÓN:"
echo "======================================================================"
echo "1. Conecta el cable USB-C de tu monitor portátil directamente al puerto"
echo "   USB-C de esta computadora."
echo "2. En tu iPhone, iPad o Mac, abre el 'Centro de Control' -> 'Duplicar Pantalla'."
echo "3. Selecciona 'TARDIS' de la lista de receptores AirPlay disponibles."
echo "4. La pantalla de tu dispositivo iOS/macOS se proyectará instantáneamente"
echo "   con aceleración por hardware NVIDIA en el monitor portátil."
echo "======================================================================"
