#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# TARDIS SOVEREIGN MOBILE TERMINAL - AUTO-START ON BOOT (ZERO-URL NATIVE ENGINE)
# ==============================================================================
# Dispositivo : Motorola Moto X Play (lux / ZY222ZXWPP)
# Función     : Inicia el demonio soberano local y levanta la interfaz nativa
#               offline en REDACTED_IP:8080 sin depender de ningún URL externo.
# ==============================================================================

if [ -d "/data/data/com.termux/files/usr/bin" ]; then
    export PATH="/data/data/com.termux/files/usr/bin:$PATH"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[TARDIS-POCKET] Activando bloqueo de suspensión (Wake Lock)..."
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock
fi

# 1. Comprobar si el demonio local ya está corriendo
if ! pgrep -f "tardis_pocket_daemon.py" >/dev/null 2>&1; then
    echo "[TARDIS-POCKET] Iniciando Demonio Autónomo en segundo plano..."
    if [ -f "$SCRIPT_DIR/tardis_pocket_daemon.sh" ]; then
        bash "$SCRIPT_DIR/tardis_pocket_daemon.sh" >/dev/null 2>&1 &
    else
        python3 "$SCRIPT_DIR/tardis_pocket_daemon.py" >/dev/null 2>&1 &
    fi
    sleep 1.5
fi

# 2. Pulso háptico y confirmación vocal
if command -v termux-vibrate >/dev/null 2>&1; then
    termux-vibrate -d 250
fi

if command -v termux-tts-speak >/dev/null 2>&1; then
    termux-tts-speak "TARDIS POCKET iniciado en modo soberano nativo." &
fi

# 3. Lanzar la interfaz en pantalla local (REDACTED_IP:8080)
LOCAL_UI="http://REDACTED_IP:8080"
echo "[TARDIS-POCKET] Desplegando interfaz en pantalla: $LOCAL_UI"

# Intentar primero con el Launcher Soberano Nativo si está disponible
if pm list packages 2>/dev/null | grep -q "com.tardis.sovereign"; then
    am start -n com.tardis.sovereign/.TardisLauncherActivity >/dev/null 2>&1
elif pm list packages 2>/dev/null | grep -q "com.shinydiscoballsdev.kifossk"; then
    am start -n com.shinydiscoballsdev.kifossk/.MainActivity >/dev/null 2>&1 || \
    am start -a android.intent.action.VIEW -d "$LOCAL_UI" >/dev/null 2>&1
else
    # Navegador predeterminado en modo pantalla completa local
    am start -a android.intent.action.VIEW -d "$LOCAL_UI" >/dev/null 2>&1 || \
    termux-open-url "$LOCAL_UI" >/dev/null 2>&1 || \
    xdg-open "$LOCAL_UI" >/dev/null 2>&1
fi

echo "[TARDIS-POCKET] ✓ Sistema completamente operativo sin dependencias externas."
