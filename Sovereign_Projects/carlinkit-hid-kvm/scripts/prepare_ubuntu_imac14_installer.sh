#!/usr/bin/env bash
# ==============================================================================
# Script soberano: Preparador de USB Autoinstall Ubuntu 24.04 LTS para iMac 14,1
# ==============================================================================
set -e

TARGET_DEV="${1:-/dev/sda}"

if [ ! -b "$TARGET_DEV" ]; then
    echo "[-] Error: $TARGET_DEV no es un dispositivo de bloques válido."
    echo "    Inserta la memoria USB de 32GB y verifica con 'lsblk'."
    exit 1
fi

echo "========================================================================"
echo "⚡ PREPARANDO INSTALADOR AUTOMÁTICO UBUNTU 24.04 LTS PARA iMAC 14,1 ($TARGET_DEV)"
echo "========================================================================"

# Desactivar throttling de kernel en el dispositivo USB
if [ -f "/sys/block/$(basename "$TARGET_DEV")/queue/wbt_lat_usec" ]; then
    echo 0 | sudo tee "/sys/block/$(basename "$TARGET_DEV")/queue/wbt_lat_usec" > /dev/null
fi

# Desmontar puntos previos
echo "[1/6] Desmontando particiones previas..."
sudo umount "${TARGET_DEV}"* 2>/dev/null || true
sudo wipefs -a "$TARGET_DEV"

# Crear tabla GPT
echo "[2/6] Creando tabla de particiones GPT Apple EFI..."
sudo parted -s "$TARGET_DEV" mklabel gpt
sudo parted -s "$TARGET_DEV" mkpart "IMAC_EFI" fat32 1MiB 2049MiB
sudo parted -s "$TARGET_DEV" set 1 esp on
sudo parted -s "$TARGET_DEV" set 1 boot on
sudo parted -s "$TARGET_DEV" mkpart "UBUNTU_DATA" ext4 2049MiB 100%

sudo partprobe "$TARGET_DEV"
sleep 2

EFI_PART="${TARGET_DEV}1"
DATA_PART="${TARGET_DEV}2"

echo "[3/6] Formateando particiones..."
sudo mkfs.vfat -F 32 -n "IMAC_EFI" "$EFI_PART"
sudo mkfs.ext4 -F -L "UBUNTU_INST" -b 4096 "$DATA_PART"

# Montar EFI
MNT_EFI="/mnt/imac_ubuntu_efi"
sudo mkdir -p "$MNT_EFI"
sudo mount "$EFI_PART" "$MNT_EFI"

echo "[4/6] Desplegando cargador nativo Apple EFI y GRUB para iMac 14,1..."
sudo mkdir -p "$MNT_EFI/EFI/BOOT"
sudo mkdir -p "$MNT_EFI/System/Library/CoreServices"
sudo mkdir -p "$MNT_EFI/boot/grub"
sudo mkdir -p "$MNT_EFI/nocloud"

# Copiar cargadores EFI
if [ -f "/boot/efi/EFI/BOOT/BOOTX64.EFI" ]; then
    sudo cp -v "/boot/efi/EFI/BOOT/BOOTX64.EFI" "$MNT_EFI/EFI/BOOT/BOOTX64.EFI"
    sudo cp -v "$MNT_EFI/EFI/BOOT/BOOTX64.EFI" "$MNT_EFI/System/Library/CoreServices/boot.efi"
elif [ -f "/boot/efi/EFI/ubuntu/grubx64.efi" ]; then
    sudo cp -v "/boot/efi/EFI/ubuntu/grubx64.efi" "$MNT_EFI/EFI/BOOT/BOOTX64.EFI"
    sudo cp -v "$MNT_EFI/EFI/BOOT/BOOTX64.EFI" "$MNT_EFI/System/Library/CoreServices/boot.efi"
fi

# Bendición Apple CoreServices para iMac 14,1
cat << 'EOF_PLIST' | sudo tee "$MNT_EFI/System/Library/CoreServices/SystemVersion.plist" > /dev/null
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>ProductBuildVersion</key>
    <string>24.04</string>
    <key>ProductName</key>
    <string>Ubuntu 24.04 LTS iMac 14,1</string>
    <key>ProductVersion</key>
    <string>24.04</string>
</dict>
</plist>
EOF_PLIST

# Autoinstall cloud-init user-data para instalación 100% desatendida en iMac
cat << 'EOF_USERDATA' | sudo tee "$MNT_EFI/nocloud/user-data" > /dev/null
#cloud-config
autoinstall:
  version: 1
  locale: es_ES.UTF-8
  keyboard:
    layout: es
  identity:
    hostname: imac14-ubuntu
    username: timemachine
    password: "REDACTED"
  ssh:
    install-server: true
    allow-pw: true
  packages:
    - openssh-server
    - mesa-utils
    - intel-media-va-driver
    - bcmwl-kernel-source
    - curl
    - git
    - net-tools
  storage:
    layout:
      name: lvm
  late-commands:
    - echo 'PermitRootLogin yes' >> /target/etc/ssh/sshd_config
    - systemctl enable ssh
EOF_USERDATA

touch /tmp/meta-data
sudo cp /tmp/meta-data "$MNT_EFI/nocloud/meta-data"

# Configuración GRUB EFI
cat << 'EOF_GRUB' | sudo tee "$MNT_EFI/boot/grub/grub.cfg" > /dev/null
set timeout=5
set default=0

insmod efi_gop
insmod efi_uga
insmod video_bochs
insmod video_cirrus
insmod all_video
insmod font

menuentry "⚡ Instalar Ubuntu 24.04 LTS en iMac 14,1 (100% Autónomo)" --class ubuntu {
    search --no-floppy --set=root -l UBUNTU_INST
    linux /casper/vmlinuz quiet splash autoinstall ds=nocloud\;s=/cdrom/nocloud/ ---
    initrd /casper/initrd
}

menuentry "🖥️ Probar Ubuntu 24.04 LTS Live Desktop (iMac 14,1)" --class ubuntu {
    search --no-floppy --set=root -l UBUNTU_INST
    linux /casper/vmlinuz boot=casper quiet splash ---
    initrd /casper/initrd
}
EOF_GRUB

sudo sync
sudo umount "$MNT_EFI"
sudo rm -rf "$MNT_EFI"

echo "========================================================================"
echo "🎉 BASE DE ARRANQUE APPLE EFI PARA UBUNTU DESPLEGADA EN $TARGET_DEV"
echo "   Siguiente paso: Inyectar imagen de sistema en $DATA_PART"
echo "========================================================================"
