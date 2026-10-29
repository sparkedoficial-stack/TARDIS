#!/usr/bin/env bash
# ==============================================================================
# 🛸 TARDIS :: CREADOR DE USB BOOTABLE DESATENDIDO DE OMARCHY 4.0.6 (iMac 14,1)
# ==============================================================================
# Descarga la ISO oficial de Omarchy (https://iso.omarchy.org/omarchy-4.0.6.iso),
# la graba en la unidad USB indicada y añade automáticamente una partición FAT32
# con etiqueta "cidata" que contiene:
#   - user_configuration.json (Disco /dev/sda, Limine EFI, Broadcom BCM4360, Iris Pro 5200)
#   - user_credentials.json   (Usuarios timemachine y operator con sudo)
#   - authorized_keys         (Llave SSH Ed25519 del host TARDIS, habilita sshd)
#
# Uso:
#   sudo /home/timemachine/prepare_omarchy_imac14_usb.sh /dev/sdX
# ==============================================================================
set -euo pipefail

USB_DEV="${1:-}"
PAYLOAD_DIR="/home/timemachine/omarchy_payload"
ISO_URL="https://iso.omarchy.org/omarchy-4.0.6.iso"
ISO_PATH="$PAYLOAD_DIR/omarchy-4.0.6.iso"
CIDATA_DIR="$PAYLOAD_DIR/cidata"

if [ -z "$USB_DEV" ]; then
    echo "Uso: sudo $0 /dev/sdX"
    echo ""
    echo "Dispositivos de bloques detectados actualmente:"
    lsblk -o NAME,SIZE,TYPE,RM,MODEL,MOUNTPOINT
    exit 1
fi

if [ "$USB_DEV" = "/dev/nvme0n1" ] || [[ "$USB_DEV" == /dev/nvme* ]]; then
    echo "❌ ERROR CRÍTICO: $USB_DEV es el disco principal NVMe del sistema host. Abortando."
    exit 1
fi

if [ ! -b "$USB_DEV" ]; then
    echo "❌ ERROR: El dispositivo $USB_DEV no existe o no es un dispositivo de bloques."
    exit 1
fi

mkdir -p "$PAYLOAD_DIR"

if [ ! -f "$ISO_PATH" ]; then
    echo "⬇️ Descargando ISO oficial de Omarchy 4.0.6 desde $ISO_URL..."
    curl -L --fail --progress-bar -o "$ISO_PATH.part" "$ISO_URL"
    mv "$ISO_PATH.part" "$ISO_PATH"
fi

echo "🔥 Grabando $ISO_PATH en $USB_DEV..."
umount "${USB_DEV}"* 2>/dev/null || true
dd if="$ISO_PATH" of="$USB_DEV" bs=4M status=progress conv=fsync
sync
partprobe "$USB_DEV" 2>/dev/null || true
sleep 2

echo "🧩 Creando partición NoCloud 'cidata' en el espacio libre de $USB_DEV para instalación 100% desatendida..."
# Añadir una partición pequeña de 64MB al final de la tabla para 'cidata'
sgdisk -e "$USB_DEV" 2>/dev/null || true
LAST_PART_NUM=$(lsblk -ln -o NAME "$USB_DEV" | tail -n +2 | wc -l)
NEW_PART_NUM=$((LAST_PART_NUM + 1))
sgdisk -n "${NEW_PART_NUM}:0:+64M" -t "${NEW_PART_NUM}:0700" -c "${NEW_PART_NUM}:cidata" "$USB_DEV" 2>/dev/null || \
    parted -s "$USB_DEV" mkpart primary fat32 95% 100% 2>/dev/null || true
partprobe "$USB_DEV" 2>/dev/null || true
sleep 2

CIDATA_PART="${USB_DEV}${NEW_PART_NUM}"
if [ -b "$CIDATA_PART" ]; then
    mkfs.vfat -F 32 -n "cidata" "$CIDATA_PART"
    MNT_TMP="$(mktemp -d)"
    mount "$CIDATA_PART" "$MNT_TMP"
    cp -v "$CIDATA_DIR/user_configuration.json" "$MNT_TMP/"
    cp -v "$CIDATA_DIR/user_credentials.json" "$MNT_TMP/"
    cp -v "$CIDATA_DIR/authorized_keys" "$MNT_TMP/"
    cp -v "$CIDATA_DIR/meta-data" "$MNT_TMP/" 2>/dev/null || true
    sync
    umount "$MNT_TMP"
    rmdir "$MNT_TMP"
    echo "✅ Partición 'cidata' inyectada en $CIDATA_PART."
else
    echo "⚠️ No se pudo anexar partición extra en la tabla híbrida ISO; puedes usar $PAYLOAD_DIR/cidata.iso en un segundo USB si deseas modo desatendido."
fi

echo "========================================================================"
echo "🎉 USB de Omarchy 4.0.6 para iMac 14,1 listo en $USB_DEV"
echo "1. Conecta el USB al iMac 14,1 y enciéndelo manteniendo presionada Option (Alt)."
echo "2. Selecciona 'EFI Boot'."
echo "3. Omarchy detectará la partición 'cidata', instalará Arch+Hyprland+Broadcom WL"
echo "   en /dev/sda, habilitará SSH con tu llave y reiniciará automáticamente."
echo "========================================================================"
