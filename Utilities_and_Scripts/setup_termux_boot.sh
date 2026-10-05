#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# INSTALADOR DE ARRANQUE AUTÓNOMO SOBERANO EN TERMUX (MOTO X PLAY)
# ==============================================================================
# Ejecuta este script dentro de la app Termux en el teléfono:
#   bash /sdcard/tardis/setup_termux_boot.sh
# ==============================================================================

set -e
echo "=== CONFIGURANDO TERMINAL SOBERANA TARDIS EN TERMUX (MODO ZERO-URL) ==="

# 1. Asegurar dependencias de Python y Termux API si es posible
if command -v pkg >/dev/null 2>&1; then
    echo "[1/4] Verificando entorno Python en Termux..."
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Instalando Python..."
        pkg install -y python
    fi
fi

# 2. Crear directorio de arranque de Termux-Boot
echo "[2/4] Configurando inicio automático con Termux-Boot..."
mkdir -p ~/.termux/boot

# 3. Buscar directorio de la suite TARDIS POCKET
TARDIS_DIR=""
for p in "/sdcard/tardis" \
         "/storage/emulated/0/tardis" \
         "/sdcard/Download/TARDIS_TERMINAL" \
         "$HOME/storage/downloads/TARDIS_TERMINAL"; do
    if [ -f "$p/tardis_pocket_daemon.py" ]; then
        TARDIS_DIR="$p"
        break
    fi
done

# Copiar archivos a almacenamiento local de Termux si se encontraron externamente
TARGET_APP_DIR="$HOME/tardis_pocket"
mkdir -p "$TARGET_APP_DIR"

if [ -n "$TARDIS_DIR" ]; then
    echo "[3/4] Sincronizando archivos desde $TARDIS_DIR hacia $TARGET_APP_DIR..."
    cp -rf "$TARDIS_DIR"/* "$TARGET_APP_DIR"/ 2>/dev/null || true
fi

# 4. Crear script de auto-arranque en ~/.termux/boot/start-tardis.sh
echo "[4/4] Creando servicio de arranque en ~/.termux/boot/start-tardis.sh..."
cat << 'EOF' > ~/.termux/boot/start-tardis.sh
#!/data/data/com.termux/files/usr/bin/bash
export PATH="/data/data/com.termux/files/usr/bin:$PATH"

# Activar bloqueo de suspensión
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock
fi

# Localizar suite
POCKET_DIR="$HOME/tardis_pocket"
if [ ! -f "$POCKET_DIR/start_tardis_terminal.sh" ]; then
    POCKET_DIR="/sdcard/tardis"
fi

if [ -f "$POCKET_DIR/start_tardis_terminal.sh" ]; then
    bash "$POCKET_DIR/start_tardis_terminal.sh"
else
    # Fallback directo
    if command -v python3 >/dev/null 2>&1 && [ -f "$POCKET_DIR/tardis_pocket_daemon.py" ]; then
        python3 "$POCKET_DIR/tardis_pocket_daemon.py" &
        sleep 2
        am start -a android.intent.action.VIEW -d "http://REDACTED_IP:8080" >/dev/null 2>&1
    fi
fi
EOF

chmod +x ~/.termux/boot/start-tardis.sh
chmod +x "$TARGET_APP_DIR"/*.sh 2>/dev/null || true

echo ""
echo "=============================================================================="
echo "✓ INSTALACIÓN COMPLETADA EXITOSAMENTE"
echo "=============================================================================="
echo "A partir de ahora, cada vez que enciendas el Moto X Play:"
echo "  1. Termux-Boot iniciará el demonio local en REDACTED_IP:8080 automáticamente."
echo "  2. Se conectará por Hotspot (REDACTED_IP) o LAN en segundo plano."
echo "  3. La telemetría física (Batería, GPS) se transmitirá sin abrir nada."
echo "  4. La cabina soberana funcionará 100% offline o conectada sin URLs manuales."
echo "=============================================================================="
