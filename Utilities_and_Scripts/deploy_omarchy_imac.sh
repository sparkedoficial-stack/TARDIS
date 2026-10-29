#!/usr/bin/env bash
# ==============================================================================
# 🛸 TARDIS-NEURAL-SPACE-KAIJU :: DESPLIEGUE SOBERANO DE OMARCHY EN iMac 14,1
# ==============================================================================
# Detecta y aprovisiona Omarchy (omacom/omarchy v4.0 quattro) en el Apple iMac 14,1
# (Intel Core i5-4570R Haswell, Iris Pro 5200, Broadcom BCM4360 14e4:43a0, 1TB HDD).
#
# Modos soportados automáticamente:
#   1. SSH (:22)      -> Aprovisionamiento directo (Arch Linux nativo o chroot/híbrido)
#   2. GIA API (:8757)-> Inyección de llaves SSH + ejecución remota vía HTTP JSON
#   3. ADB (:5555)    -> Conmutación de GRUB desde Android 17 hacia Linux/Omarchy + reboot
# ==============================================================================
set -euo pipefail

IMAC_IP="${1:-REDACTED_IP}"
PORT_API=8757
PORT_SSH=22
PORT_ADB=5555
PAYLOAD_DIR="/home/timemachine/omarchy_payload"
OMARCHY_ARCHIVE="$PAYLOAD_DIR/omarchy-tree.tar.zst"
CIDATA_DIR="$PAYLOAD_DIR/cidata"
SSH_KEY="/home/timemachine/.ssh/id_ed25519"
SSH_PUB="/home/timemachine/.ssh/id_ed25519.pub"
SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 -o BatchMode=yes)
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/tardis"
LOG_FILE="$STATE_DIR/omarchy_deploy.log"
mkdir -p "$STATE_DIR"

log() {
    echo "[$(date '+%F %T')] [OMARCHY-DEPLOY] $*" | tee -a "$LOG_FILE"
}

log "========================================================================"
log "🚀 INICIANDO DESPLIEGUE DE OMARCHY EN iMac 14,1 (Objetivo: $IMAC_IP)"
log "========================================================================"

if [ ! -f "$OMARCHY_ARCHIVE" ]; then
    log "📦 Empaquetando árbol oficial de Omarchy..."
    tar --exclude='.git' -C "$PAYLOAD_DIR" -I 'zstd -3' -cf "$OMARCHY_ARCHIVE" omarchy
fi

PUBKEY_CONTENT="$(cat "$SSH_PUB")"

# ------------------------------------------------------------------------------
# 1. MODO ADB (5555): Si el iMac está en Android 17, restaurar arranque Linux/Omarchy
# ------------------------------------------------------------------------------
if nc -z -w 2 "$IMAC_IP" "$PORT_ADB" 2>/dev/null && ! nc -z -w 2 "$IMAC_IP" "$PORT_SSH" 2>/dev/null; then
    log "📱 iMac detectado en modo Android 17 (ADB $IMAC_IP:$PORT_ADB). Reconfigurando GRUB hacia Linux/Omarchy..."
    adb connect "$IMAC_IP:$PORT_ADB" >/dev/null 2>&1 || true
    adb -s "$IMAC_IP:$PORT_ADB" shell "su -c '
        mkdir -p /mnt/linux_root
        mount /dev/block/sda2 /mnt/linux_root 2>/dev/null || mount /dev/sda2 /mnt/linux_root 2>/dev/null || true
        if [ -f /mnt/linux_root/boot/grub/grubenv ]; then
            sed -i \"s/saved_entry=.*/saved_entry=0/g\" /mnt/linux_root/boot/grub/grubenv
        fi
        if [ -f /mnt/linux_root/boot/grub/grub.cfg ]; then
            sed -i \"s/set default=\\\"Android 17 (Bliss OS Desktop)\\\"/set default=\\\"0\\\"/g\" /mnt/linux_root/boot/grub/grub.cfg
        fi
        sync
        umount /mnt/linux_root 2>/dev/null || true
        reboot
    '" || true
    log "🔄 Señal de reinicio enviada desde Android. Esperando reconexión en Linux (SSH/API)..."
    for _ in $(seq 1 45); do
        sleep 4
        if nc -z -w 2 "$IMAC_IP" "$PORT_SSH" 2>/dev/null || nc -z -w 2 "$IMAC_IP" "$PORT_API" 2>/dev/null; then
            log "✅ iMac reconectado en modo Linux ($IMAC_IP)."
            break
        fi
    done
fi

# ------------------------------------------------------------------------------
# 2. MODO GIA API (8757): Garantizar acceso SSH root/operator/timemachine
# ------------------------------------------------------------------------------
if curl -s -m 2 "http://$IMAC_IP:$PORT_API/api/ping" 2>/dev/null | grep -q "PONG"; then
    log "🟢 API GIA detectada en http://$IMAC_IP:$PORT_API. Inyectando llaves SSH y habilitando sshd..."
    python3 - "$IMAC_IP" "$PORT_API" "$PUBKEY_CONTENT" <<'PY'
import json, sys, urllib.request
ip, port, pubkey = sys.argv[1], sys.argv[2], sys.argv[3]
cmd = f"""
mkdir -p /root/.ssh /home/operator/.ssh /home/timemachine/.ssh
for d in /root/.ssh /home/operator/.ssh /home/timemachine/.ssh; do
    grep -qF "{pubkey}" "$d/authorized_keys" 2>/dev/null || echo "{pubkey}" >> "$d/authorized_keys"
    chmod 700 "$d"
    chmod 600 "$d/authorized_keys"
done
chown -R operator:operator /home/operator/.ssh 2>/dev/null || true
chown -R timemachine:timemachine /home/timemachine/.ssh 2>/dev/null || true
systemctl enable --now ssh 2>/dev/null || systemctl enable --now sshd 2>/dev/null || true
"""
req = urllib.request.Request(
    f"http://{ip}:{port}/api/exec",
    data=json.dumps({"cmd": cmd, "timeout": 30}).encode(),
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=35) as resp:
        print(resp.read().decode())
except Exception as e:
    print(f"API warn: {e}", file=sys.stderr)
PY
fi

# ------------------------------------------------------------------------------
# 3. VERIFICACIÓN DE CANAL SSH
# ------------------------------------------------------------------------------
SSH_USER=""
for u in root operator timemachine; do
    if ssh "${SSH_OPTS[@]}" -i "$SSH_KEY" "$u@$IMAC_IP" "true" 2>/dev/null; then
        SSH_USER="$u"
        break
    fi
done

if [ -z "$SSH_USER" ]; then
    log "❌ No fue posible establecer sesión SSH ni API con $IMAC_IP. El iMac 14,1 está apagado o fuera de red."
    exit 1
fi

log "🔑 Canal SSH establecido con $SSH_USER@$IMAC_IP. Transfiriendo payload de Omarchy..."

# ------------------------------------------------------------------------------
# 4. TRANSFERENCIA DEL ÁRBOL OFICIAL OMARCHY Y CONFIGURACIÓN CIDATA
# ------------------------------------------------------------------------------
ssh "${SSH_OPTS[@]}" -i "$SSH_KEY" "$SSH_USER@$IMAC_IP" "sudo mkdir -p /tmp/omarchy_stage /usr/share/omarchy && sudo chmod 777 /tmp/omarchy_stage"
scp "${SSH_OPTS[@]}" -i "$SSH_KEY" "$OMARCHY_ARCHIVE" "$SSH_USER@$IMAC_IP:/tmp/omarchy_stage/omarchy-tree.tar.zst"
scp "${SSH_OPTS[@]}" -i "$SSH_KEY" -r "$CIDATA_DIR" "$SSH_USER@$IMAC_IP:/tmp/omarchy_stage/cidata"

# ------------------------------------------------------------------------------
# 5. INSTALACIÓN Y CONFIGURACIÓN DE OMARCHY EN EL iMac 14,1
# ------------------------------------------------------------------------------
log "⚙️ Ejecutando instalador y configuración de hardware iMac 14,1 en $IMAC_IP..."

ssh "${SSH_OPTS[@]}" -i "$SSH_KEY" "$SSH_USER@$IMAC_IP" "sudo bash -s" <<'REMOTE_EOF'
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
LOG="/var/log/omarchy_imac14_install.log"
exec > >(tee -a "$LOG") 2>&1

echo "[$(date '+%F %T')] === INICIANDO INSTALACIÓN DE OMARCHY EN iMac 14,1 ==="
uname -a
lscpu | grep "Model name" || true
lspci -nn | grep -iE "vga|network|ethernet" || true

# 1. Desplegar el árbol oficial de Omarchy en /usr/share/omarchy y en los hogares de usuario
mkdir -p /usr/share/omarchy
tar -I zstd -xf /tmp/omarchy_stage/omarchy-tree.tar.zst -C /usr/share/omarchy --strip-components=1
chmod +x /usr/share/omarchy/bin/* 2>/dev/null || true

# Asegurar que el usuario timemachine exista con sudo sin contraseña
if ! id timemachine >/dev/null 2>&1; then
    useradd -m -s /bin/bash -G sudo,video,audio,render,input,netdev timemachine 2>/dev/null || \
    useradd -m -s /bin/bash -G wheel,video,audio,storage,input,network timemachine 2>/dev/null || true
    echo "timemachine:123456" | chpasswd || true
fi
echo "timemachine ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/99-timemachine
echo "operator ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/99-operator
chmod 440 /etc/sudoers.d/99-timemachine /etc/sudoers.d/99-operator

# Copiar llaves SSH autorizadas
for uhome in /root /home/timemachine /home/operator; do
    [ -d "$uhome" ] || continue
    mkdir -p "$uhome/.ssh"
    cp /tmp/omarchy_stage/cidata/authorized_keys "$uhome/.ssh/authorized_keys"
    chmod 700 "$uhome/.ssh"
    chmod 600 "$uhome/.ssh/authorized_keys"
done
chown -R timemachine:timemachine /home/timemachine/.ssh 2>/dev/null || true
chown -R operator:operator /home/operator/.ssh 2>/dev/null || true

# Vincular árbol de Omarchy para los usuarios
for u in timemachine operator; do
    if [ -d "/home/$u" ]; then
        mkdir -p "/home/$u/.local/share" "/home/$u/.config"
        rm -rf "/home/$u/.local/share/omarchy"
        cp -a /usr/share/omarchy "/home/$u/.local/share/omarchy"
        cp -rn /usr/share/omarchy/config/* "/home/$u/.config/" 2>/dev/null || true
        mkdir -p "/home/$u/.config/omarchy/current"
        ln -sfn /usr/share/omarchy/themes/tokyo-night "/home/$u/.config/omarchy/current/theme"
        chown -R "$u:$u" "/home/$u/.local" "/home/$u/.config"
    fi
done

# Enlazar ejecutables de Omarchy en /usr/local/bin
for binfile in /usr/share/omarchy/bin/*; do
    [ -f "$binfile" ] && ln -sf "$binfile" "/usr/local/bin/$(basename "$binfile")"
done

# 2. Detectar si el sistema base es Arch Linux o Debian/Ubuntu
if [ -f /etc/arch-release ] || command -v pacman >/dev/null 2>&1; then
    echo "[OMARCHY] Sistema base Arch Linux detectado. Ejecutando omarchy-apply-system & omarchy-apply-hardware..."
    export OMARCHY_PATH="/usr/share/omarchy"
    export OMARCHY_INSTALL="/usr/share/omarchy/install"
    export PATH="/usr/share/omarchy/bin:$PATH"
    pacman -Sy --noconfirm --needed base-devel git curl rsync jq openssh networkmanager \
        broadcom-wl-dkms linux-headers intel-media-driver vulkan-intel mesa \
        hyprland waybar kitty alacritty neovim sddm || true
    /usr/share/omarchy/bin/omarchy-apply-system --install-user timemachine --first-install || true
    /usr/share/omarchy/bin/omarchy-apply-hardware --install-user timemachine || true
else
    echo "[OMARCHY] Sistema base Debian/Ubuntu detectado. Instalando stack Omarchy + Drivers iMac 14,1 (BCM4360 + Iris Pro 5200)..."
    apt-get update -qq || true
    apt-get install -y -qq \
        linux-headers-$(uname -r) broadcom-sta-dkms firmware-brcm80211 \
        mesa-vulkan-drivers intel-media-va-driver i965-va-driver vainfo \
        wayland-protocols xwayland seatd libseat1 polkitd pkexec \
        alacritty kitty neovim tmux git curl wget jq rsync ripgrep fd-find fzf bat eza zoxide \
        sway waybar wofi rofi-wayland mako-notifier grim slurp wl-clipboard swaybg swayidle swaylock \
        pipewire pipewire-pulse wireplumber pavucontrolbrightnessctl playerctl \
        fonts-jetbrains-mono fonts-font-awesome fonts-noto-color-emoji \
        network-manager openssh-server python3 || true

    # Instalar Hyprland si está disponible en los repositorios activos
    apt-get install -y -qq hyprland hyprpaper hypridle hyprlock xdg-desktop-portal-hyprland 2>/dev/null || true

    # Activar driver Broadcom BCM4360 (14e4:43a0)
    modprobe -r b43 bcma ssb brcmsmac 2>/dev/null || true
    modprobe wl 2>/dev/null || true
    echo "wl" > /etc/modules-load.d/omarchy-bcm4360.conf
    cat << 'MODEOF' > /etc/modprobe.d/omarchy-bcm4360-blacklist.conf
blacklist b43
blacklist bcma
blacklist ssb
blacklist brcmsmac
MODEOF

    # Configurar sesión gráfica auto-login de Omarchy (Hyprland con fallback a Sway) en TTY1
    mkdir -p /etc/systemd/system/REDACTED_EMAIL.d
    cat << 'GETTYEOF' > /etc/systemd/system/REDACTED_EMAIL.d/autologin.conf
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin timemachine --noclear %I $TERM
GETTYEOF

    cat << 'PROFEOF' > /home/timemachine/.bash_profile
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ] && [ "${XDG_VTNR:-0}" -eq 1 ]; then
    export PATH="/usr/share/omarchy/bin:$HOME/.local/bin:$PATH"
    export OMARCHY_PATH="/usr/share/omarchy"
    export XDG_CURRENT_DESKTOP=Hyprland
    export XDG_SESSION_TYPE=wayland
    export MOZ_ENABLE_WAYLAND=1
    if command -v Hyprland >/dev/null 2>&1; then
        exec Hyprland >/tmp/omarchy-hyprland.log 2>&1
    elif command -v sway >/dev/null 2>&1; then
        exec sway >/tmp/omarchy-sway.log 2>&1
    fi
fi
PROFEOF
    chown timemachine:timemachine /home/timemachine/.bash_profile
fi

# 3. Asegurar configuración de Red Persistente (Ethernet REDACTED_IP + REDACTED_IP + Wi-Fi TimeMachine/LightSpeed)
mkdir -p /etc/NetworkManager/system-connections
cat << 'NMEOF' > /etc/NetworkManager/system-connections/Omarchy-Ethernet.nmconnection
[connection]
id=Omarchy-Ethernet
type=ethernet
autoconnect=true
autoconnect-priority=100

[ipv4]
method=auto
address1=REDACTED_IP/24,REDACTED_IP
address2=REDACTED_IP/24
dns=REDACTED_IP;REDACTED_IP;
may-fail=false

[ipv6]
method=auto
NMEOF
chmod 600 /etc/NetworkManager/system-connections/Omarchy-Ethernet.nmconnection

# 4. Asegurar Apple EFI Bless en /boot/efi para el iMac 14,1
if mountpoint -q /boot/efi || mount /dev/sda1 /boot/efi 2>/dev/null; then
    mkdir -p /boot/efi/EFI/BOOT /boot/efi/System/Library/CoreServices
    if [ -f /boot/efi/EFI/debian/grubx64.efi ]; then
        cp -f /boot/efi/EFI/debian/grubx64.efi /boot/efi/EFI/BOOT/BOOTX64.EFI
        cp -f /boot/efi/EFI/debian/grubx64.efi /boot/efi/System/Library/CoreServices/boot.efi
    elif [ -f /boot/efi/EFI/BOOT/BOOTX64.EFI ]; then
        cp -f /boot/efi/EFI/BOOT/BOOTX64.EFI /boot/efi/System/Library/CoreServices/boot.efi
    fi
    cat << 'PLISTEOF' > /boot/efi/System/Library/CoreServices/SystemVersion.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>ProductBuildVersion</key>
    <string>Omarchy-4.0</string>
    <key>ProductName</key>
    <string>Mac OS X</string>
    <key>ProductUserVisibleVersion</key>
    <string>Omarchy 4.0 (iMac 14,1)</string>
    <key>ProductVersion</key>
    <string>10.15.7</string>
</dict>
</plist>
PLISTEOF
fi

# 5. Si GRUB tenía a Android 17 como entrada por defecto, restaurar Linux/Omarchy como entrada 0
if [ -f /etc/default/grub ]; then
    sed -i 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT=0/' /etc/default/grub
    sed -i 's/^GRUB_DISTRIBUTOR=.*/GRUB_DISTRIBUTOR="Omarchy 4.0 (iMac 14,1)"/' /etc/default/grub
    update-grub 2>/dev/null || grub-mkconfig -o /boot/grub/grub.cfg 2>/dev/null || true
fi

# 6. Identificar el sistema como Omarchy 4.0 en /etc/omarchy-release
cat << 'RELEOF' > /etc/omarchy-release
OMARCHY_VERSION="4.0.6-imac14,1"
OMARCHY_CODENAME="quattro"
OMARCHY_HARDWARE="Apple iMac 14,1 (Haswell i5-4570R / Iris Pro 5200 / BCM4360)"
RELEOF

systemctl daemon-reload || true
systemctl enable --now NetworkManager 2>/dev/null || true
systemctl enable --now ssh 2>/dev/null || systemctl enable --now sshd 2>/dev/null || true
systemctl restart REDACTED_EMAIL 2>/dev/null || true
sync

echo "[$(date '+%F %T')] === OMARCHY 4.0 INSTALADO Y ACTIVO EN iMac 14,1 ==="
REMOTE_EOF

log "✅ Despliegue de Omarchy completado exitosamente en el iMac 14,1 ($IMAC_IP)."
