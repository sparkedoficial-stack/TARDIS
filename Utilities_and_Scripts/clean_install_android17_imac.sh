#!/usr/bin/env bash
# ==============================================================================
# ⚡ INSTALACIÓN 100% LIMPIA DE ANDROID 17 EN EL DISCO INTERNO (iMac 14,1)
# Borrado total de particiones previas, formato nuevo e inyección de Android 17
# ==============================================================================
set -e

IMAC_IP="${1:-REDACTED_IP}"
SSH_KEY="/home/timemachine/.ssh/id_ed25519"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=3"
LOG="/var/log/imac_clean_install.log"
exec > >(tee -a "$LOG") 2>&1

echo "========================================================================"
echo "⚡ INICIANDO PROTOCOLO DE LIMPIEZA TOTAL Y DESPLIEGUE ANDROID 17"
echo "Objetivo: $IMAC_IP"
echo "========================================================================"

echo "[1/6] Esperando conexión SSH con el iMac en $IMAC_IP..."
while ! ping -c 1 -W 1 "$IMAC_IP" >/dev/null 2>&1; do
    printf "."
    sleep 2
done
echo ""
echo "✅ iMac detectado en $IMAC_IP. Estableciendo enlace seguro..."

ssh $SSH_OPTS -i "$SSH_KEY" root@"$IMAC_IP" bash << 'REMOTE_CLEAN'
set -e

echo "[2/6] Analizando discos del sistema..."
BOOT_DEV="/dev/$(lsblk -no PKNAME "$(findmnt -n -o SOURCE /)" 2>/dev/null || echo sdb)"
echo "Dispositivo de arranque activo: $BOOT_DEV"

# Identificar disco interno (el que no sea el boot)
INTERNAL_DISK=""
for dev in /dev/sd[a-z] /dev/nvme[0-9]n[0-9]; do
    if [ -b "$dev" ] && [ "$dev" != "$BOOT_DEV" ]; then
        INTERNAL_DISK="$dev"
        break
    fi
done

if [ -z "$INTERNAL_DISK" ]; then
    echo "❌ Error: No se encontró disco interno diferente al USB ($BOOT_DEV)"
    exit 1
fi
echo "Disco interno objetivo: $INTERNAL_DISK ($(lsblk -dn -o SIZE "$INTERNAL_DISK"))"

echo "[3/6] Desmontando particiones activas y borrando firmas previas..."
umount ${INTERNAL_DISK}* 2>/dev/null || true
wipefs -a "$INTERNAL_DISK" || true

# Borrado completo de tabla de particiones previa con sgdisk/parted
echo "Creando tabla GPT limpia desde cero..."
parted -s "$INTERNAL_DISK" mklabel gpt
parted -s "$INTERNAL_DISK" mkpart "IMAC_EFI" fat32 1MiB 1025MiB
parted -s "$INTERNAL_DISK" set 1 esp on
parted -s "$INTERNAL_DISK" mkpart "ANDROID" ext4 1025MiB 100%
udevadm settle

PART_PREFIX=""
if [[ "$INTERNAL_DISK" =~ [0-9]$ ]]; then PART_PREFIX="p"; fi
EFI_PART="${INTERNAL_DISK}${PART_PREFIX}1"
ROOT_PART="${INTERNAL_DISK}${PART_PREFIX}2"

echo "Formateando partición EFI ($EFI_PART) y partición Android ($ROOT_PART)..."
mkfs.vfat -F32 -n "IMAC_EFI" "$EFI_PART"
mkfs.ext4 -F -L "ANDROID" "$ROOT_PART"
udevadm settle

echo "[4/6] Montando disco limpio y copiando Android 17..."
MNT="/mnt/clean_target"
mkdir -p "$MNT"
mount "$ROOT_PART" "$MNT"
mkdir -p "$MNT/boot/efi"
mount "$EFI_PART" "$MNT/boot/efi"

mkdir -p "$MNT/android" "$MNT/android/data"
chmod 777 "$MNT/android/data"

# Copiar archivos verificados de Android 17 desde el USB
cp -v /android/kernel "$MNT/android/kernel"
cp -v /android/initrd.img "$MNT/android/initrd.img"
cp -v /android/system.sfs "$MNT/android/system.sfs"
cp -v /android/install.img "$MNT/android/install.img" 2>/dev/null || true
cp -v /android/data/local.prop "$MNT/android/data/local.prop" 2>/dev/null || true

echo "[5/6] Instalando cargador de arranque dedicado GRUB EFI para Android 17..."
mkdir -p "$MNT/boot/efi/EFI/BOOT" "$MNT/boot/efi/EFI/debian" "$MNT/boot/efi/System/Library/CoreServices"

# Copiar binario EFI 64-bit
if [ -f /boot/efi/EFI/debian/grubx64.efi ]; then
    cp -v /boot/efi/EFI/debian/grubx64.efi "$MNT/boot/efi/EFI/BOOT/BOOTX64.EFI"
    cp -v /boot/efi/EFI/debian/grubx64.efi "$MNT/boot/efi/EFI/debian/grubx64.efi"
elif [ -f /boot/efi/EFI/BOOT/BOOTX64.EFI ]; then
    cp -v /boot/efi/EFI/BOOT/BOOTX64.EFI "$MNT/boot/efi/EFI/BOOT/BOOTX64.EFI"
    cp -v /boot/efi/EFI/BOOT/BOOTX64.EFI "$MNT/boot/efi/EFI/debian/grubx64.efi"
fi

# Configuración de GRUB limpia y directa
cat << 'EOF_GRUB' > "$MNT/boot/efi/EFI/BOOT/grub.cfg"
set default=0
set timeout=2
terminal_output console

menuentry "Android 17 (Bliss OS Desktop)" --class android-x86 --class android --class os {
    insmod part_gpt
    insmod ext2
    search --no-floppy --label --set=root ANDROID
    linux /android/kernel root=/dev/ram0 SRC=/android androidboot.hardware=android_x86_64 androidboot.selinux=permissive quiet PC_MODE=1 FFMPEG_CODEC=1 FFMPEG_PREFER_C2=1 service.adb.tcp.port=5555 androidboot.adb.port=5555
    initrd /android/initrd.img
}

menuentry "Android 17 (Modo Graficos Seguros - nomodeset)" --class android-x86 --class android --class os {
    insmod part_gpt
    insmod ext2
    search --no-floppy --label --set=root ANDROID
    linux /android/kernel root=/dev/ram0 SRC=/android androidboot.hardware=android_x86_64 androidboot.selinux=permissive quiet nomodeset HWACCEL=0 service.adb.tcp.port=5555 androidboot.adb.port=5555
    initrd /android/initrd.img
}
EOF_GRUB

cp -v "$MNT/boot/efi/EFI/BOOT/grub.cfg" "$MNT/boot/efi/EFI/debian/grub.cfg"

# Estructura Apple CoreServices para arranque nativo Mac
cp -v "$MNT/boot/efi/EFI/BOOT/BOOTX64.EFI" "$MNT/boot/efi/System/Library/CoreServices/boot.efi"
cat << 'PLIST' > "$MNT/boot/efi/System/Library/CoreServices/SystemVersion.plist"
<xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>ProductBuildVersion</key>
    <string>26.4</string>
    <key>ProductName</key>
    <string>Android 17 Desktop</string>
    <key>ProductVersion</key>
    <string>17.0</string>
</dict>
</plist>
PLIST

echo "[6/6] Limpiando entradas viejas en la NVRAM de Apple con efibootmgr..."
# Eliminar entradas previas huérfanas
for bootnum in $(efibootmgr | grep -E "Ubuntu|Mac OS|debian" | awk '{print $1}' | sed 's/Boot//' | sed 's/\*//'); do
    efibootmgr -b "$bootnum" -B 2>/dev/null || true
done

# Crear entrada limpia primaria para Android 17
efibootmgr -c -d "$INTERNAL_DISK" -p 1 -L "Android 17 Clean" -l '\EFI\BOOT\BOOTX64.EFI' 2>/dev/null || true

sync
umount "$MNT/boot/efi"
umount "$MNT"

echo "=========================================================="
echo "🎉 ¡INSTALACIÓN 100% LIMPIA DE ANDROID 17 COMPLETADA!"
echo "   Todas las particiones anteriores fueron eliminadas."
echo "   Reiniciando en Android 17 en 5 segundos..."
echo "=========================================================="
speaker-test -t sine -f 880 -l 1 >/dev/null 2>&1 &
sleep 0.8
killall -9 speaker-test 2>/dev/null || true
sleep 5
reboot -f
REMOTE_CLEAN

echo "✅ Protocolo finalizado exitosamente."
