#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# TARDIS POCKET SOBERANO - SUPERVISOR Y CENTINELA DE SISTEMA (24/7 AUTO-RUN)
# ==============================================================================
# Dispositivo: Motorola Moto X Play (Serial: ZY222ZXWPP)
# Función    : Mantiene el demonio nativo activo de forma ininterrumpida sin
#              necesidad de interacción del usuario ni de abrir URLs manuales.
# ==============================================================================

# Si se ejecuta en Linux estándar o Android chroot, ajustar paths
if [ -d "/data/data/com.termux/files/usr/bin" ]; then
    export PATH="/data/data/com.termux/files/usr/bin:$PATH"
fi

# Detectar directorio base del script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Bloqueo de suspensión permanente (Wake Lock)
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock
    echo "[TARDIS-DAEMON-SH] ✓ Termux Wake-Lock adquirido."
fi

# 2. Señal háptica de inicio de servicio
if command -v termux-vibrate >/dev/null 2>&1; then
    termux-vibrate -d 200
fi

# 3. Notificación vocal soberana
if command -v termux-tts-speak >/dev/null 2>&1; then
    termux-tts-speak "TARDIS POCKET en línea. Demonio soberano activo." &
fi

echo "[TARDIS-DAEMON-SH] Iniciando bucle supervisor 24/7..."

while true; do
    if command -v python3 >/dev/null 2>&1; then
        echo "[TARDIS-DAEMON-SH] Ejecutando tardis_pocket_daemon.py..."
        python3 "$SCRIPT_DIR/tardis_pocket_daemon.py"
    elif command -v python >/dev/null 2>&1; then
        echo "[TARDIS-DAEMON-SH] Ejecutando con python..."
        python "$SCRIPT_DIR/tardis_pocket_daemon.py"
    else
        echo "[TARDIS-DAEMON-SH] ⚠️ Python no encontrado. Instalando python en Termux..."
        if command -v pkg >/dev/null 2>&1; then
            pkg install -y python
            continue
        fi
        sleep 10
    fi
    echo "[TARDIS-DAEMON-SH] ⚠️ El demonio finalizó. Reiniciando en 3 segundos..."
    sleep 3
done
