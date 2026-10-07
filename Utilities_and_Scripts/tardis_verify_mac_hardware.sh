#!/bin/bash
# ==============================================================================
# [TARDIS-NEURAL-SPACE-KAIJU] SCRIPT SOBERANO :: VERIFICACIÓN HARDWARE MAC 14,1
# ==============================================================================
# Autor: Arquitecto (₪) / TARDIS
# Dependencia: ADB (Android Debug Bridge)
# ==============================================================================

MAC_IP="${1}"

if [ -z "$MAC_IP" ]; then
    echo "Uso: $0 <MAC_IP_ANDROID_WIFI>"
    exit 1
fi

echo "[TARDIS] Iniciando enlace ADB (TCP/IP) con Android 17 en Mac 14,1 ($MAC_IP:5555)..."
adb connect "$MAC_IP:5555"
sleep 2

echo "======================================================="
echo "   [DIAGNÓSTICO SOBERANO DE HARDWARE - ANDROID 17]     "
echo "======================================================="

echo "[+] 1. COMPOSITOR GRÁFICO (NVIDIA/Intel Iris Pro):"
adb -s "$MAC_IP:5555" shell dumpsys SurfaceFlinger | grep -E "GLES|OpenGL|Vendor|Renderer" | head -n 4

echo -e "\n[+] 2. TARJETA DE RED Y WI-FI (Broadcom BCM4360):"
adb -s "$MAC_IP:5555" shell ip a | grep -E "wlan0|eth0"
adb -s "$MAC_IP:5555" shell dumpsys wifi | grep "Wi-Fi is"

echo -e "\n[+] 3. BLUETOOTH ENCORE:"
adb -s "$MAC_IP:5555" shell dumpsys bluetooth_manager | grep "enabled: true" || echo "  [!] Bluetooth inactivo o sin driver."

echo -e "\n[+] 4. SUBSISTEMA DE AUDIO (Cirrus Logic CS4206B):"
adb -s "$MAC_IP:5555" shell dumpsys audio | grep -E "STREAM_MUSIC|Device" | head -n 5

echo -e "\n[+] 5. SENSORES Y PERIFÉRICOS (Magic Keyboard / Trackpad / USB):"
adb -s "$MAC_IP:5555" shell getevent -i | grep -E "name:|bus:" | grep -i "apple" || echo "  [ok] Dispositivos USB genéricos detectados."

echo "======================================================="
echo "[TARDIS] Verificación completada. Desvinculando ADB..."
adb disconnect "$MAC_IP:5555"
