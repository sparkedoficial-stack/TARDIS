#!/usr/bin/env bash
# ==============================================================================
# Script de Instalación y Empaquetado de AirPlay Monitor Soberano
# ==============================================================================
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
DESKTOP_DIR="${HOME}/Escritorio"
APPS_DIR="${HOME}/.local/share/applications"
ICONS_BASE="${HOME}/.local/share/icons/hicolor"

echo "🍏 [AIRPLAY MONITOR] Instalando y empaquetando el sistema..."

# 1. Crear directorios necesarios
mkdir -p "${BIN_DIR}" "${APPS_DIR}" "${DESKTOP_DIR}" "${ICONS_BASE}"

# 2. Permisos ejecutables
chmod +x "${BASE_DIR}/bin/airplay-monitor"
chmod +x "${BASE_DIR}/airplay_monitor/main.py"

# 3. Enlaces simbólicos en ~/.local/bin
ln -sf "${BASE_DIR}/bin/airplay-monitor" "${BIN_DIR}/airplay-monitor"
ln -sf "${BASE_DIR}/bin/airplay-monitor" "${BIN_DIR}/airplay-studio"

# 4. Instalar iconos en el tema del sistema
echo "🎨 Registrando iconos en tema hicolor..."
mkdir -p "${ICONS_BASE}/scalable/apps"
cp -f "${BASE_DIR}/airplay_monitor/assets/icon.svg" "${ICONS_BASE}/scalable/apps/airplay-monitor.svg"

for sz in 512 256 128 64 48 32; do
    if [ -f "${BASE_DIR}/airplay_monitor/assets/icon_${sz}.png" ]; then
        mkdir -p "${ICONS_BASE}/${sz}x${sz}/apps"
        cp -f "${BASE_DIR}/airplay_monitor/assets/icon_${sz}.png" "${ICONS_BASE}/${sz}x${sz}/apps/airplay-monitor.png"
    fi
done

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f "${ICONS_BASE}" 2>/dev/null || true
fi

# 5. Instalar accesos directos de escritorio (.desktop)
echo "🖥️ Configurando lanzadores de aplicación..."
cp -f "${BASE_DIR}/airplay-monitor.desktop" "${APPS_DIR}/airplay-monitor.desktop"
cp -f "${BASE_DIR}/airplay-monitor.desktop" "${DESKTOP_DIR}/AirPlay Monitor.desktop"

chmod +x "${APPS_DIR}/airplay-monitor.desktop"
chmod +x "${DESKTOP_DIR}/AirPlay Monitor.desktop"

if command -v gio >/dev/null 2>&1; then
    gio set "${DESKTOP_DIR}/AirPlay Monitor.desktop" metadata::trusted true 2>/dev/null || true
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${APPS_DIR}" 2>/dev/null || true
fi

# 6. Inicializar configuración por defecto si no existe
python3 -c "
import sys
sys.path.insert(0, '${BASE_DIR}')
from airplay_monitor.backend import ConfigManager, AirPlayServiceManager
cfg = ConfigManager()
cfg.write_uxplayrc()
svc = AirPlayServiceManager()
svc.ensure_service_installed()
"

echo "✅ [AIRPLAY MONITOR] ¡Instalación completada con éxito!"
echo "   • Acceso en Escritorio : 'AirPlay Monitor' listo."
echo "   • Lanzador en Menú     : Registrado en la cuadrícula de aplicaciones GNOME."
echo "   • Comando terminal     : 'airplay-monitor' o 'airplay-studio'"
