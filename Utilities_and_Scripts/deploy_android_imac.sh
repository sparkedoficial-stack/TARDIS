#!/usr/bin/env bash
# ==============================================================================
# ⚡ DESPLIEGUE AUTÓNOMO :: ANDROID 17 / BLISS OS EN iMAC 14,1 (100% REMOTO)
# ==============================================================================
set -e

SSH_KEY="/home/timemachine/.ssh/id_ed25519"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=3"

detect_imac_ip() {
    # 1. IP estática LAN
    if ping -c 1 -W 1 REDACTED_IP >/dev/null 2>&1; then
        echo "REDACTED_IP"
        return 0
    fi
    # 2. IP rescate directo
    if ping -c 1 -W 1 REDACTED_IP >/dev/null 2>&1; then
        echo "REDACTED_IP"
        return 0
    fi
    # 3. mDNS
    if ping -c 1 -W 1 imac-gia.local >/dev/null 2>&1; then
        echo "imac-gia.local"
        return 0
    fi
    # 4. Escaneo por API GIA (8757) o SSH (22)
    local ips
    ips=$(ip neigh show 2>/dev/null | grep -E "192\.168\.1\." | awk '{print $1}')
    for ip in $ips; do
        if curl -s -m 0.5 "http://$ip:8757/api/ping" 2>/dev/null | grep -q "PONG"; then
            echo "$ip"
            return 0
        fi
        if nc -z -w 1 "$ip" 22 2>/dev/null; then
            if ssh $SSH_OPTS -i "$SSH_KEY" root@"$ip" "hostname" 2>/dev/null | grep -q "imac"; then
                echo "$ip"
                return 0
            fi
        fi
    done
    echo ""
}

TARGET_IP="${1:-}"
if [ -z "$TARGET_IP" ]; then
    echo "[*] Buscando iMac en la red..."
    TARGET_IP=$(detect_imac_ip)
fi

if [ -z "$TARGET_IP" ]; then
    echo "❌ Error: No se detectó el iMac en la red."
    echo "Por favor conecta el cable Ethernet entre el iMac y el router."
    exit 1
fi

USER="root"
echo "========================================================================"
echo "⚡ DESPLEGANDO ANDROID 17 EN EL DISCO INTERNO DE 1TB DEL iMAC 14,1"
echo "Objetivo: $TARGET_IP"
echo "========================================================================"

echo "[1/4] Verificando conexión remota..."
if ! ping -c 1 -W 2 "$TARGET_IP" >/dev/null 2>&1; then
    echo "❌ Error: El host $TARGET_IP no responde a ping."
    exit 1
fi
echo "✅ Conexión establecida con $TARGET_IP."

echo "[2/4] Preparando estructura de Android en el disco interno del iMac..."
ssh $SSH_OPTS -i "$SSH_KEY" "$USER@$TARGET_IP" bash << 'REMOTE'
set -e
mkdir -p /android /android/data
chmod 777 /android/data
echo "[iMac] Directorio /android preparado."
REMOTE

echo "[3/4] Transfiriendo archivos del sistema Android (Kernel, Initrd, System)..."
PAYLOAD_DIR="/home/timemachine/android_payload"
if [ ! -f "$PAYLOAD_DIR/system.sfs" ]; then
    echo "❌ Error: Payload de Android incompleto en $PAYLOAD_DIR."
    exit 1
fi

scp $SSH_OPTS -i "$SSH_KEY" "$PAYLOAD_DIR"/kernel "$USER@$TARGET_IP:/android/"
scp $SSH_OPTS -i "$SSH_KEY" "$PAYLOAD_DIR"/initrd.img "$USER@$TARGET_IP:/android/"
if [ -f "$PAYLOAD_DIR/install.img" ]; then
    scp $SSH_OPTS -i "$SSH_KEY" "$PAYLOAD_DIR"/install.img "$USER@$TARGET_IP:/android/"
fi
scp $SSH_OPTS -i "$SSH_KEY" "$PAYLOAD_DIR"/system.sfs "$USER@$TARGET_IP:/android/"
echo "✅ Archivos de sistema transferidos exitosamente."

echo "[4/4] Configurando GRUB para arranque dual de Android 17..."
ssh $SSH_OPTS -i "$SSH_KEY" "$USER@$TARGET_IP" bash << 'REMOTE'
set -e
cat << "GRUB_ENTRY" > /etc/grub.d/40_android
#!/bin/sh
exec tail -n +3 $0
menuentry "Android 17 (Bliss OS Desktop)" --class android-x86 --class android --class os {
    insmod part_gpt
    insmod ext2
    search --no-floppy --set=root --file /android/kernel
    linux /android/kernel root=/dev/ram0 SRC=/android androidboot.hardware=android_x86_64 androidboot.selinux=permissive quiet PC_MODE=1 FFMPEG_CODEC=1 FFMPEG_PREFER_C2=1
    initrd /android/initrd.img
}

menuentry "Android 17 (Safe Graphics - nomodeset)" --class android-x86 --class android --class os {
    insmod part_gpt
    insmod ext2
    search --no-floppy --set=root --file /android/kernel
    linux /android/kernel root=/dev/ram0 SRC=/android androidboot.hardware=android_x86_64 androidboot.selinux=permissive quiet nomodeset HWACCEL=0
    initrd /android/initrd.img
}
GRUB_ENTRY
chmod +x /etc/grub.d/40_android

sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=3/' /etc/default/grub
sed -i 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT="Android 17 (Bliss OS Desktop)"/' /etc/default/grub
update-grub

echo "=========================================================="
echo "✅ ANDROID 17 INSTALADO CON ÉXITO EN EL iMAC 14,1"
echo "Reiniciando el iMac directamente en Android 17..."
echo "=========================================================="
sync
reboot
REMOTE

echo "🎉 Protocolo completado. El iMac 14,1 está reiniciando en Android 17."
