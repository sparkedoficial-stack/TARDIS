#!/bin/bash
# ==============================================================================
# ⚡ SMART BOOTABLE USB CREATOR FOR iMAC 14,1 & CARLINKIT REMOTE ENGINE
# Formats USB with GPT (EFI + Android 17 / Bliss OS) + Carlinkit Autonomous Payload
# ==============================================================================
set -euo pipefail

TARGET_DEV="${1:-}"
if [ -z "$TARGET_DEV" ] || [ ! -b "$TARGET_DEV" ]; then
    echo "❌ Error: Especifica un dispositivo de bloque válido. Ejemplo: $0 /dev/sda" >&2
    exit 1
fi

echo "========================================================================"
echo "⚡ PREPARANDO DISPOSITIVO BOOTEABLE INTELIGENTE PARA iMAC 14,1 ($TARGET_DEV)"
echo "========================================================================"

# Auditoría de seguridad
ROOT_DISK=$(lsblk -no pkname $(findmnt -n -o SOURCE /))
if [[ "$TARGET_DEV" == "/dev/$ROOT_DISK" ]]; then
    echo "[-] ERROR CRÍTICO: $TARGET_DEV es el disco del sistema operativo. Abortando." >&2
    exit 1
fi

echo "[1/6] Desmontando particiones en $TARGET_DEV y borrando firmas previas..."
for part in $(ls -1 ${TARGET_DEV}* 2>/dev/null); do
    sudo umount "$part" 2>/dev/null || true
done
sudo wipefs -a "$TARGET_DEV"

echo "[2/6] Creando tabla de particiones GPT para Apple EFI (iMac 14,1)..."
sudo parted -s "$TARGET_DEV" mklabel gpt
sudo parted -s "$TARGET_DEV" mkpart "IMAC_EFI" fat32 1MiB 1025MiB
sudo parted -s "$TARGET_DEV" set 1 esp on
sudo parted -s "$TARGET_DEV" set 1 boot on
sudo parted -s "$TARGET_DEV" mkpart "ANDROID" ext4 1025MiB 100%

sudo partprobe "$TARGET_DEV"
sleep 1
sudo udevadm settle

PART_PREFIX=""
if [[ "$TARGET_DEV" =~ [0-9]$ ]]; then PART_PREFIX="p"; fi
EFI_PART="${TARGET_DEV}${PART_PREFIX}1"
ROOT_PART="${TARGET_DEV}${PART_PREFIX}2"

echo "[3/6] Formateando particiones: EFI (FAT32) y ANDROID (ext4)..."
sudo mkfs.vfat -F 32 -n "IMAC_EFI" "$EFI_PART"
sudo mkfs.ext4 -F -L "ANDROID" "$ROOT_PART"

echo "[4/6] Montando partición EFI y desplegando cargador nativo Apple + Payloads Carlinkit..."
MNT_EFI="/mnt/imac_smart_efi"
sudo mkdir -p "$MNT_EFI"
sudo mount "$EFI_PART" "$MNT_EFI"

# 4.1 Desplegar estructura de booteo Apple EFI / GRUB
sudo mkdir -p "$MNT_EFI/EFI/BOOT" "$MNT_EFI/EFI/debian" "$MNT_EFI/System/Library/CoreServices"

if [ -f "/boot/efi/EFI/BOOT/BOOTX64.EFI" ]; then
    sudo cp -v "/boot/efi/EFI/BOOT/BOOTX64.EFI" "$MNT_EFI/EFI/BOOT/BOOTX64.EFI"
elif [ -f "/boot/efi/EFI/ubuntu/grubx64.efi" ]; then
    sudo cp -v "/boot/efi/EFI/ubuntu/grubx64.efi" "$MNT_EFI/EFI/BOOT/BOOTX64.EFI"
fi
sudo cp -v "$MNT_EFI/EFI/BOOT/BOOTX64.EFI" "$MNT_EFI/System/Library/CoreServices/boot.efi"

# Configuración GRUB optimizada para iMac 14,1
cat << 'EOF_GRUB' | sudo tee "$MNT_EFI/EFI/BOOT/grub.cfg" > /dev/null
set default=0
set timeout=3
terminal_output console

menuentry "Android 17 / Bliss OS (iMac 14,1 Desktop)" --class android-x86 --class android --class os {
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

# Apple CoreServices Bless
cat << 'EOF_PLIST' | sudo tee "$MNT_EFI/System/Library/CoreServices/SystemVersion.plist" > /dev/null
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>ProductBuildVersion</key>
    <string>26.4</string>
    <key>ProductName</key>
    <string>Android 17 iMac 14,1</string>
    <key>ProductVersion</key>
    <string>17.0</string>
</dict>
</plist>
EOF_PLIST

# 4.2 Desplegar suite de control total Carlinkit en la raíz de la partición FAT32
echo "[*] Sincronizando scripts de control remoto y Wi-Fi 0hack en EFI..."
sudo cp -r /home/timemachine/carlinkit-hid-kvm/payload_dist/* "$MNT_EFI/"

# 4.3 Asegurar todos los aliases de arranque del Carlinkit
for alias in autorun.sh factory.sh update.sh U2W.sh AutoBox.sh autobox.sh AutoKit.sh autokit.sh run.sh install.sh; do
    sudo cp "$MNT_EFI/auto_run.sh" "$MNT_EFI/$alias"
    sudo chmod +x "$MNT_EFI/$alias"
done

sudo sync
sudo umount "$MNT_EFI"
sudo rm -rf "$MNT_EFI"

echo "[5/6] Montando partición ANDROID e inyectando imagen de sistema..."
MNT_ROOT="/mnt/imac_smart_root"
sudo mkdir -p "$MNT_ROOT"
sudo mount "$ROOT_PART" "$MNT_ROOT"

sudo mkdir -p "$MNT_ROOT/android" "$MNT_ROOT/android/data"
sudo chmod 777 "$MNT_ROOT/android/data"

SRC_PAYLOAD="/home/timemachine/android_payload"
if [ -d "$SRC_PAYLOAD" ]; then
    sudo cp -v "$SRC_PAYLOAD/kernel" "$MNT_ROOT/android/kernel"
    sudo cp -v "$SRC_PAYLOAD/initrd.img" "$MNT_ROOT/android/initrd.img"
    sudo cp -v "$SRC_PAYLOAD/system.sfs" "$MNT_ROOT/android/system.sfs"
    [ -f "$SRC_PAYLOAD/install.img" ] && sudo cp -v "$SRC_PAYLOAD/install.img" "$MNT_ROOT/android/install.img" || true
else
    echo "[-] Advertencia: $SRC_PAYLOAD no encontrado. Omitiendo copia de Android."
fi

echo "[6/6] Sincronizando búferes del disco (sync) y desmontando..."
sudo sync
sudo umount "$MNT_ROOT"
sudo rm -rf "$MNT_ROOT"

echo "========================================================================"
echo "🎉 DISPOSITIVO BOOTEABLE INTELIGENTE COMPLETADO CON ÉXITO:"
echo "   - iMac 14,1: Partición GPT EFI ('IMAC_EFI') lista para arrancar con [Option/Alt]."
echo "   - Android 17: Partición ext4 ('ANDROID') con sistema completo inyectado."
echo "   - Carlinkit Control: Wi-Fi '0hack' (clave: REDACTED_PHONE) + SSH + KVM Web 8080."
echo "========================================================================"
