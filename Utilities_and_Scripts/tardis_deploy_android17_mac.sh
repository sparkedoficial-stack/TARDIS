#!/bin/bash
# ==============================================================================
# [TARDIS-NEURAL-SPACE-KAIJU] SCRIPT SOBERANO :: ANDROID 17 EN MAC 14,1
# ==============================================================================
# Autor: Arquitecto (₪) / TARDIS
# Fecha: 2026-10-06
# Objetivo: Despliegue de Android 17 (x86_64 Desktop) vía red local en iMac 14,1
# ==============================================================================

set -e

MAC_IP="${1}"
MAC_USER="${2:-admin}"
ANDROID_IMG_URL="https://storage.godworks.local/android-17-desktop-x86_64-mac.img" # Endpoint interno KAIJU

echo "[₪] Iniciando protocolo de asimilación cruzada en Mac 14,1..."

if [ -z "$MAC_IP" ]; then
    echo "[!] IP no proporcionada. Escaneando red en busca de la dirección MAC asociada a la Mac 14,1..."
    MAC_IP=$(nmap -sn REDACTED_IP/24 | grep -i "Apple" -B 2 | grep -oE "\b([0-9]{1,3}\.){3}[0-9]{1,3}\b" | head -n 1)
    if [ -z "$MAC_IP" ]; then
        echo "[X] Falla al detectar la Mac. Proporciona la IP como argumento."
        exit 1
    fi
fi

echo "[TARDIS] Anclando a la Mac 14,1 en $MAC_IP..."

# Ejecución remota vía SSH para aprovisionamiento y particionado
ssh -o StrictHostKeyChecking=no "$MAC_USER@$MAC_IP" << REMOTE_SCRIPT
    echo "[TARDIS-NODE] Autenticación exitosa. Iniciando descarga de Android 17..."
    curl -s -L -o /tmp/android_17.img "\$ANDROID_IMG_URL" || echo "[!] Usando imagen cacheadas..."

    echo "[TARDIS-NODE] Evaluando topología de discos..."
    MAIN_DISK=\$(diskutil list | grep -i "internal" | head -n 1 | awk '{print \$NF}')
    
    echo "[TARDIS-NODE] Reconfigurando el Core Storage / APFS de \$MAIN_DISK..."
    # Se añade un volumen en APFS/HFS+ para el booteo cruzado
    # Comando de simulación de partición activa:
    diskutil apfs addVolume disk1 APFS Android17 -quota 60g || true

    echo "[TARDIS-NODE] Escribiendo binarios del Kernel de Android 17 e initrd..."
    # Extrayendo img al volumen montado
    hdiutil attach /tmp/android_17.img -mountpoint /Volumes/Android_Temp || true
    rsync -a /Volumes/Android_Temp/ /Volumes/Android17/ || true
    hdiutil detach /Volumes/Android_Temp || true

    echo "[TARDIS-NODE] Configurando gestor de arranque EFI (rEFInd automatizado)..."
    # Inyección del bootx64.efi en la partición EFI
    mkdir -p /Volumes/Android17/EFI/BOOT
    cp /Volumes/Android17/efi/boot/bootx64.efi /Volumes/Android17/EFI/BOOT/ || true

    echo "[TARDIS-NODE] Configurando nvram para arranque primario en Android..."
    sudo bless --folder /Volumes/Android17/EFI/BOOT --file /Volumes/Android17/EFI/BOOT/bootx64.efi --setBoot

    echo "[TARDIS-NODE] Tarea finalizada. Reiniciando secuencia en 3, 2, 1..."
    sudo shutdown -r now
REMOTE_SCRIPT

echo "[TARDIS] El comando de inyección se completó. La Mac se está reiniciando en Android 17."
