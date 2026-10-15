#!/usr/bin/env bash
# ==============================================================================
# ⚡ GIA AUTONOMOUS AI OS - BUILDER & INJECTOR FOR IMAC 14,1 (USB)
# Target Hardware: iMac 14,1 (Intel Core i5-4570R, 8GB RAM, Iris Pro 5200, BCM4360, BCM57766)
# Remote Management: Ethernet Auto-DHCP + Static Alias + SSH (keys pre-configured) + GIA API
# ==============================================================================

set -euo pipefail

USB_DEV="/dev/sda"
BUILD_DIR="/home/timemachine/imac_build"
MNT_DIR="/mnt/usb_root"
HOST_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIaEVSS7RhCsxLn73/FHljl/kuu1mvON+9iUiTudk7/t timemachine@timemachine-ASUS-TUF-Gaming-A15-FA506IC-FA506IC"

echo "========================================================================"
echo "⚡ INICIANDO COMPILACIÓN Y DESPLIEGUE DEL SISTEMA OPERATIVO GIA (iMac 14,1)"
echo "========================================================================"

# 1. VERIFICACIONES DE SEGURIDAD Y DISPOSITIVOS
echo "[1/7] Verificando disco USB objetivo..."
if [ ! -b "$USB_DEV" ]; then
    echo "❌ Error: Dispositivo $USB_DEV no encontrado."
    exit 1
fi

ROOT_DISK=$(lsblk -no pkname "$(findmnt -n -o SOURCE /)" 2>/dev/null || echo "nvme0n1")
if [[ "$USB_DEV" == *"$ROOT_DISK"* ]]; then
    echo "❌ ALERTA CRÍTICA: $USB_DEV coincide con el disco raíz del host ($ROOT_DISK). Abortando."
    exit 1
fi

echo "  -> Dispositivo verificado: $USB_DEV (114.6 GB USB)"

# Desmontar cualquier partición montada en $USB_DEV
echo "[2/7] Desmontando particiones activas en $USB_DEV..."
sudo umount ${USB_DEV}* 2>/dev/null || true
sudo wipefs -a "$USB_DEV"

# 2. PARTICIONADO GPT Y SISTEMA DE ARCHIVOS
echo "[3/7] Creando tabla de particiones GPT y formateando..."
sudo parted -s "$USB_DEV" mklabel gpt
sudo parted -s "$USB_DEV" mkpart "IMAC_EFI" fat32 1MiB 1025MiB
sudo parted -s "$USB_DEV" set 1 esp on
sudo parted -s "$USB_DEV" mkpart "IMAC_ROOT" ext4 1025MiB 100%
sudo udevadm settle

EFI_PART="${USB_DEV}1"
ROOT_PART="${USB_DEV}2"

echo "  -> Formateando $EFI_PART (FAT32 EFI)..."
sudo mkfs.vfat -F32 -n "IMAC_EFI" "$EFI_PART"

echo "  -> Formateando $ROOT_PART (ext4 ROOT)..."
sudo mkfs.ext4 -F -L "IMAC_ROOT" "$ROOT_PART"
sudo udevadm settle

# 3. CONSTRUCCIÓN DEL SISTEMA BASE DEBIAN CON DEBOOTSTRAP
echo "[4/7] Construyendo sistema base Debian Bookworm en NVMe ($BUILD_DIR)..."
sudo rm -rf "$BUILD_DIR"
sudo mkdir -p "$BUILD_DIR"

sudo debootstrap --arch=amd64 bookworm "$BUILD_DIR" http://deb.debian.org/debian/

# Configurar DNS en chroot
sudo tee "$BUILD_DIR/etc/resolv.conf" > /dev/null << 'EOF'
nameserver REDACTED_IP
nameserver REDACTED_IP
EOF

# Configurar repositorios APT con contrib y non-free-firmware
sudo tee "$BUILD_DIR/etc/apt/sources.list" > /dev/null << 'EOF'
deb http://deb.debian.org/debian bookworm main contrib non-free non-free-firmware
deb http://deb.debian.org/debian bookworm-updates main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security bookworm-security main contrib non-free non-free-firmware
EOF

# Configurar montaje fstab del USB
sudo tee "$BUILD_DIR/etc/fstab" > /dev/null << 'EOF'
LABEL=IMAC_ROOT   /           ext4    defaults,noatime,errors=remount-ro   0 1
LABEL=IMAC_EFI    /boot/efi   vfat    umask=0077                           0 1
tmpfs             /tmp        tmpfs   defaults,noatime,mode=1777           0 0
EOF

# 4. INSTALACIÓN DE CONTROLADORES Y PAQUETES DENTRO DE CHROOT
echo "[5/7] Configurando controladores iMac 14,1 y servicios de control remoto..."

# Montar sistemas virtuales para chroot inicial
sudo mount --bind /dev "$BUILD_DIR/dev"
sudo mount --bind /dev/pts "$BUILD_DIR/dev/pts"
sudo mount -t proc /proc "$BUILD_DIR/proc"
sudo mount -t sysfs /sys "$BUILD_DIR/sys"

# Script interno de aprovisionamiento
sudo tee "$BUILD_DIR/setup_internal.sh" > /dev/null << 'INNER_EOF'
#!/usr/bin/env bash
set -e
export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C

apt-get update

# Drivers Haswell iMac 14,1:
# - Broadcom BCM4360 Wi-Fi: broadcom-sta-dkms
# - Broadcom BCM57766 Gigabit Ethernet: tg3 (kernel)
# - Intel Iris Pro 5200: i915 (kernel) + intel-microcode
apt-get install -y --no-install-recommends \
    linux-image-amd64 \
    linux-headers-amd64 \
    intel-microcode \
    firmware-linux-free \
    firmware-linux-nonfree \
    firmware-misc-nonfree \
    firmware-brcm80211 \
    broadcom-sta-dkms \
    dkms \
    build-essential \
    grub-efi-amd64 \
    efibootmgr \
    openssh-server \
    network-manager \
    wpasupplicant \
    wireless-tools \
    avahi-daemon \
    libnss-mdns \
    python3 \
    python3-pip \
    python3-venv \
    python3-psutil \
    python3-requests \
    python3-fastapi \
    python3-uvicorn \
    python3-rich \
    python3-prompt-toolkit \
    git \
    curl \
    wget \
    sudo \
    htop \
    tmux \
    nano \
    rsync \
    pciutils \
    usbutils \
    ethtool \
    parted \
    dosfstools \
    e2fsprogs \
    iproute2 \
    net-tools \
    iputils-ping \
    ca-certificates \
    locales

# Configurar locales
echo "en_US.UTF-8 UTF-8" > /etc/locale.gen
locale-gen en_US.UTF-8

# Hostname
echo "imac-gia" > /etc/hostname
cat << 'EOF' > /etc/hosts
127.0.0.1   localhost
REDACTED_IP   imac-gia imac

::1         localhost ip6-localhost ip6-loopback
ff02::1     ip6-allnodes
ff02::2     ip6-allrouters
EOF

# Red: Ethernet Auto-DHCP + Link-Local + Fallback alias
mkdir -p /etc/NetworkManager/system-connections/
chmod 700 /etc/NetworkManager/system-connections/

cat << 'EOF' > /etc/NetworkManager/system-connections/Ethernet-Auto.nmconnection
[connection]
id=Ethernet-Auto
uuid=a1b2c3d4-e5f6-4a1b-8c2d-3e4f5a6b7c8d
type=ethernet
autoconnect=true
autoconnect-priority=100

[ethernet]

[ipv4]
method=auto
never-default=false
address1=REDACTED_IP/24
address2=REDACTED_IP/24

[ipv6]
method=auto
addr-gen-mode=default
EOF
chmod 600 /etc/NetworkManager/system-connections/Ethernet-Auto.nmconnection

# Pre-configurar Wi-Fi conocidas
cat << 'EOF' > /etc/NetworkManager/system-connections/LightSpeed.nmconnection
[connection]
id=LightSpeed
uuid=7a7d4535-00da-42a2-b202-54587c5653dc
type=wifi
autoconnect=true
autoconnect-priority=50

[wifi]
mode=infrastructure
ssid=LightSpeed

[wifi-security]
key-mgmt=wpa-psk
psk=REDACTED_PHONE

[ipv4]
method=auto

[ipv6]
method=auto
EOF
chmod 600 /etc/NetworkManager/system-connections/LightSpeed.nmconnection

cat << 'EOF' > /etc/NetworkManager/system-connections/TimeMachine-Hotspot.nmconnection
[connection]
id=TimeMachine-Hotspot
uuid=09fbed67-ab8b-4328-8679-b4d62a43f8aa
type=wifi
autoconnect=true
autoconnect-priority=60

[wifi]
mode=infrastructure
ssid=TimeMachine

[wifi-security]
key-mgmt=wpa-psk
psk=987654321

[ipv4]
method=auto

[ipv6]
method=auto
EOF
chmod 600 /etc/NetworkManager/system-connections/TimeMachine-Hotspot.nmconnection

# Servicio auxiliar para alias IP estática inmediata en interfaz ethernet
cat << 'EOF' > /etc/systemd/system/imac-ip-alias.service
[Unit]
Description=Asignación Inmediata de Alias IP en Ethernet
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'IFACE=$(ip -o link show | awk -F": " "{print \$2}" | grep -E "^(en|eth)" | head -n 1); if [ -n "$IFACE" ]; then ip addr add REDACTED_IP/24 dev $IFACE 2>/dev/null || true; ip addr add REDACTED_IP/24 dev $IFACE 2>/dev/null || true; fi'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl enable imac-ip-alias.service || true

# Configuración de Usuarios
# 1. root
echo "root:root" | chpasswd

# 2. operator
id -u operator &>/dev/null || useradd -m -s /bin/bash -g users -G sudo,adm,dialout,plugdev,netdev operator
echo "operator:operator" | chpasswd
echo "operator ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/operator
chmod 440 /etc/sudoers.d/operator

# 3. timemachine
id -u timemachine &>/dev/null || useradd -m -s /bin/bash -u 1000 -g users -G sudo,adm,dialout,plugdev,netdev,audio,video timemachine
echo "timemachine:timemachine" | chpasswd
echo "timemachine ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/timemachine
chmod 440 /etc/sudoers.d/timemachine

# SSH Daemon y Claves Autorizadas
mkdir -p /etc/ssh/sshd_config.d/
cat << 'EOF' > /etc/ssh/sshd_config.d/99-imac-remote.conf
PermitRootLogin yes
PasswordAuthentication yes
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
ClientAliveInterval 30
ClientAliveCountMax 5
EOF

for u in root home/operator home/timemachine; do
    sshdir="/$u/.ssh"
    mkdir -p "$sshdir"
    chmod 700 "$sshdir"
    echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIaEVSS7RhCsxLn73/FHljl/kuu1mvON+9iUiTudk7/t timemachine@timemachine-ASUS-TUF-Gaming-A15-FA506IC-FA506IC" > "$sshdir/authorized_keys"
    chmod 600 "$sshdir/authorized_keys"
done
chown -R operator:users /home/operator/.ssh
chown -R timemachine:users /home/timemachine/.ssh

# Avahi mDNS (imac-gia.local e imac.local)
sed -i 's/#publish-workstation=yes/publish-workstation=yes/' /etc/avahi/avahi-daemon.conf 2>/dev/null || true

# Variables globales de entorno
cat << 'EOF' > /etc/environment
PATH="/home/timemachine/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
GIA_AUTH_TOKEN="REDACTED"
GIA_TOKEN="REDACTED"
GIA_API_URL="http://127.0.0.1:8757"
OLLAMA_HOST="http://127.0.0.1:11434"
GIA_MODEL="TARDIS-NEURAL-SPACE-KAIJU"
CLAUDE_CODE_SKIP_PERMISSIONS="1"
FTL_AUTONOMOUS="1"
EOF

# Demonio de Reprogramación y Control Remoto GIA (Puerto 8757)
mkdir -p /opt/gia-core /opt/gia-core/snapshots

cat << 'EOF' > /opt/gia-core/reprogrammer_daemon.py
#!/usr/bin/env python3
"""
GIA Autonomous Reprogramming Node - Core Daemon v26.4
Architecture: Intel Core i5-4570R (4 cores) / 8GB RAM / Haswell Iris Pro 5200
Listens on port 8757 for remote control, bash execution, telemetry, and AST mutations.
"""
import sys, os, ast, json, time, shutil, socket, logging, subprocess
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

PORT = 8757
NODE_NAME = "iMac14,1-GIA-Node"
VERSION = "v26.4.0-reprogrammable"
SNAPSHOT_DIR = "/opt/gia-core/snapshots"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] GIA-Core: %(message)s",
    handlers=[
        logging.FileHandler("/var/log/gia-reprogrammer.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

def get_system_telemetry():
    cpu_count = os.cpu_count() or 4
    load1, load5, load15 = os.getloadavg()
    mem_total, mem_free, mem_avail = 0, 0, 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if parts[0] == "MemTotal:": mem_total = int(parts[1]) * 1024
                elif parts[0] == "MemFree:": mem_free = int(parts[1]) * 1024
                elif parts[0] == "MemAvailable:": mem_avail = int(parts[1]) * 1024
    except Exception:
        pass

    st = os.statvfs("/")
    disk_total = st.f_blocks * st.f_frsize
    disk_free = st.f_bavail * st.f_frsize

    ips = []
    try:
        res = subprocess.run(["ip", "-j", "a"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            ifaces = json.loads(res.stdout)
            for iface in ifaces:
                name = iface.get("ifname", "")
                if name == "lo": continue
                for addr in iface.get("addr_info", []):
                    if addr.get("family") == "inet":
                        ips.append({"iface": name, "ip": addr.get("local")})
    except Exception:
        pass

    return {
        "node": NODE_NAME,
        "version": VERSION,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "cpu": {
            "cores": cpu_count,
            "load_avg": [load1, load5, load15],
            "model": "Intel(R) Core(TM) i5-4570R CPU @ 2.70GHz"
        },
        "memory": {
            "total_bytes": mem_total,
            "available_bytes": mem_avail,
            "available_mb": round(mem_avail / (1024 * 1024), 2)
        },
        "disk": {
            "total_bytes": disk_total,
            "free_bytes": disk_free,
            "free_gb": round(disk_free / (1024 * 1024 * 1024), 2)
        },
        "network": ips,
        "status": "ONLINE"
    }

class GIARequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/api", "/api/"):
            self._send_json(200, {
                "system": "GIA Autonomous AI OS",
                "version": VERSION,
                "node": NODE_NAME,
                "endpoints": ["GET /api/status", "GET /api/telemetry", "POST /api/exec", "POST /api/install-to-disk"]
            })
        elif path in ("/api/status", "/api/telemetry"):
            self._send_json(200, get_system_telemetry())
        elif path == "/api/ping":
            self._send_json(200, {"status": "PONG", "timestamp": time.time()})
        else:
            self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try: payload = json.loads(body)
        except Exception: payload = {}

        if path == "/api/exec":
            cmd = payload.get("command")
            if not cmd:
                self._send_json(400, {"error": "command field required"})
                return
            try:
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
                self._send_json(200, {"returncode": res.returncode, "stdout": res.stdout, "stderr": res.stderr})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif path == "/api/install-to-disk":
            subprocess.Popen(["/usr/local/bin/imac-installer", "--auto"], stdout=open("/var/log/imac-install.log", "w"), stderr=subprocess.STDOUT)
            self._send_json(200, {"status": "INSTALLATION_STARTED", "log": "/var/log/imac-install.log"})
        else:
            self._send_json(404, {"error": "Not Found"})

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), GIARequestHandler)
    logging.info(f"GIA Server listening on port {PORT}...")
    server.serve_forever()
EOF
chmod +x /opt/gia-core/reprogrammer_daemon.py

# Servicio systemd GIA Reprogrammer
cat << 'EOF' > /etc/systemd/system/gia-reprogrammer.service
[Unit]
Description=GIA Autonomous Reprogramming Node v26.4
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/gia-core
ExecStart=/usr/bin/python3 /opt/gia-core/reprogrammer_daemon.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# CLI Local /usr/local/bin/gia
cat << 'EOF' > /usr/local/bin/gia
#!/usr/bin/env bash
API="http://127.0.0.1:8757"

case "$1" in
    status)
        curl -s "$API/api/status" | python3 -m json.tool || systemctl status gia-reprogrammer.service
        ;;
    telemetry)
        curl -s "$API/api/telemetry" | python3 -m json.tool
        ;;
    exec)
        shift
        curl -s -X POST -H "Content-Type: application/json" -d "{\"command\": \"$*\"}" "$API/api/exec" | python3 -m json.tool
        ;;
    install-to-disk)
        /usr/local/bin/imac-installer
        ;;
    wifi)
        shift
        case "$1" in
            list) nmcli dev wifi list ;;
            connect) nmcli dev wifi connect "$2" password "$3" ;;
            status) nmcli dev status ;;
            *) echo "Uso: gia wifi [list|connect <ssid> <password>|status]" ;;
        esac
        ;;
    help|*)
        echo "=== GIA Autonomous Node v26.4 ==="
        echo "Comandos: status, telemetry, exec '<cmd>', wifi, install-to-disk"
        ;;
esac
EOF
chmod +x /usr/local/bin/gia

# Instalador automatizado a disco interno
cat << 'EOF' > /usr/local/bin/imac-installer
#!/usr/bin/env bash
# Clona el sistema en ejecución desde el USB al disco interno del iMac 14,1
set -e

echo "=========================================================="
echo "   iMac 14,1 - GIA Autonomous AI OS Disk Installer        "
echo "=========================================================="

BOOT_DEV=$(findmnt -n -o SOURCE / | sed -r 's/p?[0-9]+$//')
echo "[*] Dispositivo USB de arranque: $BOOT_DEV"

CANDIDATES=()
for dev in /dev/sd[a-z] /dev/nvme[0-9]n[0-9]; do
    if [ -b "$dev" ] && [ "$dev" != "$BOOT_DEV" ]; then
        SIZE=$(lsblk -dn -o SIZE "$dev")
        MODEL=$(lsblk -dn -o MODEL "$dev" 2>/dev/null || echo "Disco Interno")
        CANDIDATES+=("$dev")
        echo "    - $dev ($SIZE, $MODEL)"
    fi
done

if [ ${#CANDIDATES[@]} -eq 0 ]; then
    echo "[!] No se encontró disco interno diferente a $BOOT_DEV!"
    exit 1
fi

TARGET="${CANDIDATES[0]}"

if [ "$1" != "--auto" ]; then
    echo ""
    read -p "¿Deseas instalar el sistema operativo en $TARGET? (s/n): " CONFIRM
    if [[ "$CONFIRM" != "s" && "$CONFIRM" != "S" && "$CONFIRM" != "y" ]]; then
        echo "Instalación cancelada."
        exit 0
    fi
fi

echo "[1/5] Particionando disco interno $TARGET con GPT..."
wipefs -a "$TARGET"
parted -s "$TARGET" mklabel gpt
parted -s "$TARGET" mkpart "IMAC_EFI" fat32 1MiB 1025MiB
parted -s "$TARGET" set 1 esp on
parted -s "$TARGET" mkpart "IMAC_ROOT" ext4 1025MiB 100%
udevadm settle

PART_PREFIX=""
if [[ "$TARGET" =~ [0-9]$ ]]; then PART_PREFIX="p"; fi

EFI_PART="${TARGET}${PART_PREFIX}1"
ROOT_PART="${TARGET}${PART_PREFIX}2"

echo "[2/5] Formateando particiones internas ($EFI_PART y $ROOT_PART)..."
mkfs.vfat -F32 -n "IMAC_INT_EFI" "$EFI_PART"
mkfs.ext4 -F -L "IMAC_INT_ROOT" "$ROOT_PART"

echo "[3/5] Montando y sincronizando sistema operativo..."
MNT="/mnt/imac_install"
mkdir -p "$MNT"
mount "$ROOT_PART" "$MNT"
mkdir -p "$MNT/boot/efi"
mount "$EFI_PART" "$MNT/boot/efi"

rsync -aHAXx --exclude={"/dev/*","/proc/*","/sys/*","/tmp/*","/run/*","/mnt/*","/media/*","/lost+found"} / "$MNT/"

echo "[4/5] Configurando fstab del disco interno..."
cat << FSTAB > "$MNT/etc/fstab"
LABEL=IMAC_INT_ROOT   /           ext4    defaults,noatime,errors=remount-ro   0 1
LABEL=IMAC_INT_EFI    /boot/efi   vfat    umask=0077                           0 1
tmpfs                 /tmp        tmpfs   defaults,noatime,mode=1777           0 0
FSTAB

echo "[5/5] Instalando GRUB EFI en disco interno..."
mount --bind /dev "$MNT/dev"
mount --bind /proc "$MNT/proc"
mount --bind /sys "$MNT/sys"

chroot "$MNT" grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=debian --recheck
chroot "$MNT" grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=BOOT --removable --recheck
chroot "$MNT" update-grub

mkdir -p "$MNT/boot/efi/System/Library/CoreServices"
cp "$MNT/boot/efi/EFI/BOOT/BOOTX64.EFI" "$MNT/boot/efi/System/Library/CoreServices/boot.efi" 2>/dev/null || true
cat << 'PLIST' > "$MNT/boot/efi/System/Library/CoreServices/SystemVersion.plist"
<xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>ProductBuildVersion</key>
    <string>26.4</string>
    <key>ProductName</key>
    <string>GIA Autonomous Linux</string>
    <key>ProductVersion</key>
    <string>26.4.0</string>
</dict>
</plist>
PLIST

umount "$MNT/dev" "$MNT/proc" "$MNT/sys" "$MNT/boot/efi" "$MNT" || true
echo "=========================================================="
echo "   ¡Instalación completada exitosamente!                  "
echo "   Puedes reiniciar y retirar la memoria USB.             "
echo "=========================================================="
EOF
chmod +x /usr/local/bin/imac-installer
ln -sf /usr/local/bin/imac-installer /root/install-to-internal-disk.sh

# MOTD de Bienvenida
cat << 'EOF' > /etc/motd

  ==============================================================
   ⚡ GIA AUTONOMOUS REMOTE CONTROL OS v26.4 (iMac 14,1)
   Hardware: Intel Core i5-4570R x4 | 8 GB RAM | Iris Pro 5200
  ==============================================================
   Control Remoto Ethernet: Activo (DHCP + IP fija de rescate REDACTED_IP)
   mDNS: ssh REDACTED_EMAIL  (Sin contraseña, clave inyectada)
   API Daemon: http://imac-gia.local:8757
   Comandos:
     gia status               -> Telemetría de hardware
     gia exec "<comando>"     -> Ejecución remota
     gia install-to-disk      -> Clonar a disco interno del iMac

EOF

# Habilitar servicios
systemctl enable gia-reprogrammer.service || true
systemctl enable avahi-daemon.service || true
systemctl enable NetworkManager.service || true
systemctl enable ssh.service || true

INNER_EOF

# Ejecutar aprovisionamiento en chroot
sudo chmod +x "$BUILD_DIR/setup_internal.sh"
sudo chroot "$BUILD_DIR" /bin/bash /setup_internal.sh
sudo rm -f "$BUILD_DIR/setup_internal.sh"

# Inyectar entorno FTL
echo "  -> Inyectando suite FTL en /home/timemachine/.ftl..."
if [ -d "/home/timemachine/.ftl" ]; then
    sudo cp -r /home/timemachine/.ftl "$BUILD_DIR/home/timemachine/"
    sudo chroot "$BUILD_DIR" chown -R timemachine:users /home/timemachine/.ftl
    if [ -f "$BUILD_DIR/home/timemachine/.ftl/ftl_cli.py" ]; then
        sudo chroot "$BUILD_DIR" ln -sf /home/timemachine/.ftl/ftl_cli.py /usr/local/bin/ftl
        sudo chmod +x "$BUILD_DIR/usr/local/bin/ftl" 2>/dev/null || true
    fi
fi

# Desmontar puntos virtuales del directorio de construcción
sudo umount -l "$BUILD_DIR/dev/pts" 2>/dev/null || true
sudo umount -l "$BUILD_DIR/dev" 2>/dev/null || true
sudo umount -l "$BUILD_DIR/proc" 2>/dev/null || true
sudo umount -l "$BUILD_DIR/sys" 2>/dev/null || true

# 5. SINCRONIZAR AL USB Y CONFIGURAR GRUB EFI
echo "[6/7] Sincronizando sistema al USB ($USB_DEV) e instalando GRUB EFI..."
sudo mkdir -p "$MNT_DIR"
sudo mount "$ROOT_PART" "$MNT_DIR"
sudo mkdir -p "$MNT_DIR/boot/efi"
sudo mount "$EFI_PART" "$MNT_DIR/boot/efi"

# Sincronización optimizada con rsync
sudo rsync -aHAXx --info=progress2 "$BUILD_DIR/" "$MNT_DIR/"

# Instalar GRUB EFI en el USB
sudo mount --bind /dev "$MNT_DIR/dev"
sudo mount --bind /dev/pts "$MNT_DIR/dev/pts"
sudo mount -t proc /proc "$MNT_DIR/proc"
sudo mount -t sysfs /sys "$MNT_DIR/sys"

sudo chroot "$MNT_DIR" grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=debian --recheck
sudo chroot "$MNT_DIR" grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=BOOT --removable --recheck
sudo chroot "$MNT_DIR" update-grub

# Configurar estructura Apple EFI para iMac 14,1
sudo mkdir -p "$MNT_DIR/boot/efi/System/Library/CoreServices"
sudo cp "$MNT_DIR/boot/efi/EFI/BOOT/BOOTX64.EFI" "$MNT_DIR/boot/efi/System/Library/CoreServices/boot.efi"
sudo tee "$MNT_DIR/boot/efi/System/Library/CoreServices/SystemVersion.plist" > /dev/null << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>ProductBuildVersion</key>
    <string>26.4</string>
    <key>ProductName</key>
    <string>GIA Autonomous Linux</string>
    <key>ProductVersion</key>
    <string>26.4.0</string>
</dict>
</plist>
PLIST

# Desmontar USB limpiamente
echo "[7/7] Desmontando USB y sincronizando buffers a disco..."
sudo umount -l "$MNT_DIR/dev/pts" "$MNT_DIR/dev" "$MNT_DIR/proc" "$MNT_DIR/sys" 2>/dev/null || true
sudo umount "$MNT_DIR/boot/efi"
sudo umount "$MNT_DIR"
sudo sync

echo "========================================================================"
echo "✨ SISTEMA OPERATIVO GIA (iMac 14,1) INSTALADO CON ÉXITO EN EL USB ($USB_DEV)"
echo "========================================================================"
