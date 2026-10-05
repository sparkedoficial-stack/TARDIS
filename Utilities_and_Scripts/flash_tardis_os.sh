#!/usr/bin/env bash
# ==============================================================================
# TARDIS SOVEREIGN OS - MOTOROLA MOTO X PLAY FLASHING & DEPLOYMENT SUITE
# ==============================================================================
# Este script orquesta la detección, preparación del bootloader y flasheo
# de la Custom ROM TARDIS Sovereign OS en el dispositivo Motorola.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$SCRIPT_DIR/dist"
ROM_ZIP="$DIST_DIR/TARDIS_SOVEREIGN_OS_MOTO_X_PLAY.zip"

ADB_BIN="/tmp/platform-tools/adb"
FASTBOOT_BIN="/tmp/platform-tools/fastboot"

# Colores
C_CYAN="\033[1;36m"
C_GREEN="\033[1;32m"
C_YELLOW="\033[1;33m"
C_RED="\033[1;31m"
C_RESET="\033[0m"

echo -e "${C_CYAN}===============================================================${C_RESET}"
echo -e "${C_CYAN}   TARDIS SOVEREIGN OS · SUITE DE FLASHEO Y DESPLIEGUE         ${C_RESET}"
echo -e "${C_CYAN}===============================================================${C_RESET}"

# Asegurar binarios de platform-tools
if [ ! -f "$ADB_BIN" ] || [ ! -f "$FASTBOOT_BIN" ]; then
    echo -e "${C_YELLOW}Descargando platform-tools oficiales...${C_RESET}"
    curl -sL -o /tmp/platform-tools.zip "https://dl.google.com/android/repository/platform-tools-latest-linux.zip"
    unzip -q -o /tmp/platform-tools.zip -d /tmp/
fi

# 1. Comprobar ROM compilada
if [ ! -f "$ROM_ZIP" ]; then
    echo -e "${C_YELLOW}La ROM aún no ha sido empaquetada. Construyéndola ahora...${C_RESET}"
    python3 "$SCRIPT_DIR/build_tardis_rom.py"
fi

echo -e "\n${C_CYAN}[1/4] Detectando dispositivo conectado...${C_RESET}"

MODE="NONE"
DEVICE_SERIAL=""

# Comprobar Fastboot
FB_OUT=$("$FASTBOOT_BIN" devices 2>/dev/null || true)
if [ -n "$FB_OUT" ]; then
    MODE="FASTBOOT"
    DEVICE_SERIAL=$(echo "$FB_OUT" | awk '{print $1}')
    echo -e "${C_GREEN}✓ Dispositivo detectado en MODO FASTBOOT: ${DEVICE_SERIAL}${C_RESET}"
fi

# Comprobar ADB
if [ "$MODE" == "NONE" ]; then
    ADB_OUT=$("$ADB_BIN" devices | grep -v "List" | grep -v "^$" || true)
    if [ -n "$ADB_OUT" ]; then
        MODE="ADB"
        DEVICE_SERIAL=$(echo "$ADB_OUT" | awk '{print $1}')
        echo -e "${C_GREEN}✓ Dispositivo detectado en MODO ADB: ${DEVICE_SERIAL}${C_RESET}"
    fi
fi

# Comprobar MTP
if [ "$MODE" == "NONE" ]; then
    if ls -d /run/user/1000/gvfs/mtp:host=motorola_* >/dev/null 2>&1; then
        MODE="MTP"
        echo -e "${C_GREEN}✓ Dispositivo detectado en MODO MTP (Almacenamiento USB).${C_RESET}"
    fi
fi

if [ "$MODE" == "NONE" ]; then
    echo -e "${C_RED}❌ No se detectó ningún dispositivo Motorola conectado.${C_RESET}"
    echo -e "Asegúrate de tener el teléfono conectado por USB con la pantalla encendida."
    echo -e "Para entrar en Modo Fastboot:"
    echo -e "  1. Apaga el teléfono completamente."
    echo -e "  2. Mantén presionados al mismo tiempo: [Volumen Abajo] + [Botón Encendido] durante 4 segundos."
    echo -e "  3. Suelta ambos botones; la pantalla mostrará el menú del Bootloader."
    exit 1
fi

# 2. Diagnóstico del Estado del Bootloader
echo -e "\n${C_CYAN}[2/4] Verificando estado del Bootloader...${C_RESET}"

if [ "$MODE" == "FASTBOOT" ]; then
    UNLOCKED=$("$FASTBOOT_BIN" getvar unlocked 2>&1 | grep -i "unlocked:" | awk '{print $2}' || true)
    echo -e "Estado del Bootloader: ${C_YELLOW}${UNLOCKED}${C_RESET}"
    
    if [ "$UNLOCKED" != "yes" ]; then
        echo -e "\n${C_YELLOW}ℹ El Bootloader de este Motorola está actualmente BLOQUEADO.${C_RESET}"
        echo -e "Para flashear una Custom ROM completa, Motorola requiere desbloquearlo:"
        echo -e "1. Obtén tu identificador único ejecutando:"
        echo -e "   ${C_CYAN}$FASTBOOT_BIN oem get_unlock_data${C_RESET}"
        echo -e "2. Ingresa los códigos resultantes en la web oficial de desbloqueo de Motorola:"
        echo -e "   ${C_CYAN}https://motorola-global-portal.custhelp.com/app/standalone/bootloader/unlock-your-device-b${C_RESET}"
        echo -e "3. Una vez recibido tu código de desbloqueo por correo, ejecuta:"
        echo -e "   ${C_CYAN}$FASTBOOT_BIN oem unlock <TU_CODIGO>${C_RESET}"
    else
        echo -e "${C_GREEN}✓ Bootloader DESBLOQUEADO. Listo para flasheo.${C_RESET}"
    fi
elif [ "$MODE" == "ADB" ]; then
    echo -e "El teléfono está en modo ADB normal."
    echo -e "Para reiniciar en modo Bootloader y proceder al flasheo, ejecuta:"
    echo -e "   ${C_CYAN}$ADB_BIN reboot bootloader${C_RESET}"
elif [ "$MODE" == "MTP" ]; then
    echo -e "El teléfono está en modo MTP (Transferencia de archivos)."
    echo -e "Para proceder con la Custom ROM:"
    echo -e "  1. Activa la 'Depuración USB' en Ajustes > Opciones de programador."
    echo -e "  2. O reinicia manualmente en Fastboot apagando y manteniendo [Volumen Abajo + Encendido]."
fi

# 3. Métodos de Instalación Disponibles
echo -e "\n${C_CYAN}[3/4] Paquete de la Custom ROM listo:${C_RESET}"
echo -e "  Archivo: ${C_GREEN}$ROM_ZIP${C_RESET} ($(du -h "$ROM_ZIP" | awk '{print $1}'))"

echo -e "\n${C_CYAN}[4/4] Opciones de Flasheo Disponibles:${C_RESET}"
echo -e "  ${C_GREEN}A) Sideload por Recovery (TWRP)${C_RESET}:"
echo -e "     En TWRP: Avanzado > ADB Sideload, luego ejecutar:"
echo -e "     ${C_CYAN}$ADB_BIN sideload $ROM_ZIP${C_RESET}"
echo -e ""
echo -e "  ${C_GREEN}B) Copiar al almacenamiento y flashear desde TWRP${C_RESET}:"
echo -e "     Copiar el archivo a la tarjeta SD o almacenamiento interno y seleccionarlo en 'Install'."
echo -e "==============================================================="
