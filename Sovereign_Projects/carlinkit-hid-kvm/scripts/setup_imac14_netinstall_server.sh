#!/usr/bin/env bash
# ==============================================================================
# Servidor Soberano de Instalación en Red de Ubuntu 24.04 LTS para iMac 14,1
# Control total sin periféricos físicos (Carlinkit USB + Ethernet)
# ==============================================================================
set -e

IFACE="enp2s0"
HOST_IP=$(ip -4 addr show dev "$IFACE" | grep -oP '(?<=inet\s)\d+(\.\d+){3}')
NETBOOT_DIR="/var/lib/tftpboot/imac"
HTTP_PORT=8089

echo "========================================================================"
echo "⚡ SERVIDOR DE DESPLIEGUE DESATENDIDO UBUNTU EN RED (iMAC 14,1)"
echo "   Interfaz Ethernet: $IFACE | IP Servidor: $HOST_IP"
echo "========================================================================"

# 1. Preparar directorio TFTP / Netboot
sudo mkdir -p "$NETBOOT_DIR"
sudo cp -v "/home/timemachine/ubuntu_payload/netboot.xyz.efi" "$NETBOOT_DIR/bootx64.efi"
sudo cp -v "/home/timemachine/ubuntu_payload/netboot.xyz.efi" "$NETBOOT_DIR/netboot.xyz.efi"
sudo chmod -R 777 "$NETBOOT_DIR"

# 2. Configurar servidor HTTP para Cloud-Init Autoinstall
HTTP_ROOT="/var/www/imac_autoinstall"
sudo mkdir -p "$HTTP_ROOT"

cat << EOF_USERDATA | sudo tee "$HTTP_ROOT/user-data" > /dev/null
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

cat << 'EOF_METADATA' | sudo tee "$HTTP_ROOT/meta-data" > /dev/null
instance-id: imac14-autoinstall-01
local-hostname: imac14-ubuntu
EOF_METADATA

sudo chmod -R 777 "$HTTP_ROOT"

# 3. Levantar servidor HTTP de autoinstall desacoplado (PID independiente)
echo "[*] Iniciando servidor HTTP Cloud-Init en puerto $HTTP_PORT..."
sudo killall -9 python3_autoinstall_http 2>/dev/null || true
nohup python3 -m http.server "$HTTP_PORT" --directory "$HTTP_ROOT" </dev/null >/tmp/autoinstall_http.log 2>&1 &
disown

# 4. Configurar e iniciar ProxyDHCP / TFTP con dnsmasq
DNSMASQ_CONF="/tmp/imac_proxy_dnsmasq.conf"
cat << EOF_DNSMASQ | sudo tee "$DNSMASQ_CONF" > /dev/null
# ProxyDHCP para arranque en red UEFI de Apple iMac 14,1
interface=$IFACE
bind-interfaces
port=0
dhcp-range=$HOST_IP,proxy

# Opciones PXE / UEFI Boot
dhcp-vendorclass=set:apple,AAPL
dhcp-vendorclass=set:apple_bsdp,AAPLBSDPC
dhcp-match=set:efi-x86_64,option:client-arch,7
dhcp-match=set:efi-x86_64,option:client-arch,9
dhcp-match=set:efi-x86_64,option:client-arch,11

dhcp-boot=tag:efi-x86_64,bootx64.efi,,$HOST_IP
dhcp-boot=tag:apple,bootx64.efi,,$HOST_IP
dhcp-boot=tag:!efi-x86_64,bootx64.efi,,$HOST_IP

# Servidor TFTP Integrado
enable-tftp
tftp-root=$NETBOOT_DIR
tftp-secure
log-dhcp
log-queries
EOF_DNSMASQ

echo "[*] Iniciando servicio ProxyDHCP / TFTP en $IFACE..."
sudo killall dnsmasq 2>/dev/null || true
sudo dnsmasq -C "$DNSMASQ_CONF" -d > /tmp/dnsmasq_netboot.log 2>&1 &

echo "========================================================================"
echo "🎉 SERVIDOR DE ARRANQUE EN RED ACTIVO:"
echo "   - ProxyDHCP / TFTP: Escuchando en $IFACE ($HOST_IP)"
echo "   - Cloud-Init HTTP: http://$HOST_IP:$HTTP_PORT/user-data"
echo "   - Carga útil EFI: $NETBOOT_DIR/bootx64.efi (iPXE / Netboot Universal)"
echo "========================================================================"
