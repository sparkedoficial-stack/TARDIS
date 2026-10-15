#!/usr/bin/env bash
# ==============================================================================
# Script soberano: Sincronización rápida y segura de Android Payload (/dev/sda2)
# ==============================================================================
set -e

TARGET_DEV="${1:-/dev/sda}"

if [ ! -b "$TARGET_DEV" ]; then
    echo "[-] Error: $TARGET_DEV no es un dispositivo de bloques válido o no está conectado."
    exit 1
fi

ROOT_PART="${TARGET_DEV}2"
MNT_ROOT="/mnt/imac_smart_root"

echo "========================================================================"
echo "⚡ REPARACIÓN / SINCRONIZACIÓN RÁPIDA DE ANDROID 17 EN $ROOT_PART"
echo "========================================================================"

# Desactivar throttling WBT en el dispositivo de bloques
if [ -f "/sys/block/$(basename "$TARGET_DEV")/queue/wbt_lat_usec" ]; then
    echo 0 | sudo tee "/sys/block/$(basename "$TARGET_DEV")/queue/wbt_lat_usec" > /dev/null
    echo "[*] WBT throttling desactivado a nivel de Kernel (Ring 0)."
fi

# Reparar ext4 si quedó sucio por desconexión
echo "[1/4] Comprobando y reparando sistema de archivos ext4 en $ROOT_PART..."
sudo e2fsck -y "$ROOT_PART" || true

# Montar partición
echo "[2/4] Montando $ROOT_PART en $MNT_ROOT..."
sudo mkdir -p "$MNT_ROOT"
sudo mount "$ROOT_PART" "$MNT_ROOT"

sudo mkdir -p "$MNT_ROOT/android" "$MNT_ROOT/android/data"
sudo chmod 777 "$MNT_ROOT/android/data"

SRC_PAYLOAD="/home/timemachine/android_payload"

echo "[3/4] Transfiriendo system.sfs e imágenes del kernel con rsync..."
sudo rsync -avh --progress "$SRC_PAYLOAD/kernel" "$MNT_ROOT/android/kernel"
sudo rsync -avh --progress "$SRC_PAYLOAD/initrd.img" "$MNT_ROOT/android/initrd.img"
sudo rsync -avh --progress "$SRC_PAYLOAD/system.sfs" "$MNT_ROOT/android/system.sfs"
[ -f "$SRC_PAYLOAD/install.img" ] && sudo rsync -avh --progress "$SRC_PAYLOAD/install.img" "$MNT_ROOT/android/install.img" || true

echo "[4/4] Sincronizando búferes del disco (sync final garantizado)..."
sudo sync
sudo umount "$MNT_ROOT"
sudo rm -rf "$MNT_ROOT"

echo "========================================================================"
echo "✅ ANDROID 17 COMPLETAMENTE SINCRONIZADO Y CERRADO SIN RIESGOS."
echo "========================================================================"
