#!/bin/bash
# ==============================================================================
# CARLINKIT USB HID & VIRTUAL INPUT PAYLOAD PACKAGER
# Generates a universal flash package for Carlinkit dongles and Linux systems.
# ==============================================================================
set -euo pipefail

BASE_DIR="/home/timemachine/carlinkit-hid-kvm"
OUTPUT_DIR="$BASE_DIR/payload_dist"

echo "[*] Packaging Carlinkit USB-C HID KVM Payload..."
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR" "$OUTPUT_DIR/web"

# Copy primary binaries and interfaces
cp "$BASE_DIR/scripts/setup_carlinkit_hid.sh" "$OUTPUT_DIR/setup_hid.sh"
cp "$BASE_DIR/server/carlinkit_hid_server.py" "$OUTPUT_DIR/hid_server.py"
cp "$BASE_DIR/web/index.html" "$OUTPUT_DIR/web/index.html"
chmod +x "$OUTPUT_DIR/setup_hid.sh" "$OUTPUT_DIR/hid_server.py"

# 1. Systemd Service Definition
cat << 'EOF' > "$OUTPUT_DIR/carlinkit-hid.service"
[Unit]
Description=Carlinkit Universal Virtual Keyboard & Mouse (HID) Engine
After=network.target

[Service]
Type=simple
User=root
ExecStartPre=-/etc/carlinkit_hid/setup_hid.sh
ExecStart=/usr/bin/python3 /etc/carlinkit_hid/hid_server.py
Restart=always
RestartSec=3
KillMode=process
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 2. Universal Autorun Script for USB Drive (FAT32)
cat << 'EOF' > "$OUTPUT_DIR/auto_run.sh"
#!/bin/sh
# Carlinkit USB Firmware Autorun Hook
echo "=== [CARLINKIT MOD] INICIANDO INSTALACIÓN HARDWARE HID KVM ===" > /dev/console

TARGET_DIR="/etc/carlinkit_hid"
mkdir -p "$TARGET_DIR" "$TARGET_DIR/web"

CUR_DIR=$(dirname "$0")
cp "$CUR_DIR/setup_hid.sh" "$TARGET_DIR/"
cp "$CUR_DIR/hid_server.py" "$TARGET_DIR/"
cp "$CUR_DIR/web/index.html" "$TARGET_DIR/web/"
cp "$CUR_DIR/carlinkit-hid.service" /etc/systemd/system/ 2>/dev/null || true

chmod +x "$TARGET_DIR/setup_hid.sh" "$TARGET_DIR/hid_server.py"

# Stop legacy Carlinkit CarPlay/Android Auto daemons
killall -9 autobox 2>/dev/null || true
killall -9 box 2>/dev/null || true
killall -9 linkserver 2>/dev/null || true

# Systemd autostart if available
if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload 2>/dev/null || true
    systemctl enable carlinkit-hid.service 2>/dev/null || true
    systemctl restart carlinkit-hid.service 2>/dev/null || true
else
    # Init.d / rc.local fallback
    if [ -f /etc/rc.local ]; then
        grep -q "carlinkit_hid" /etc/rc.local || sed -i '/exit 0/i /etc/carlinkit_hid/setup_hid.sh\npython3 /etc/carlinkit_hid/hid_server.py &\n' /etc/rc.local
    fi
    /etc/carlinkit_hid/setup_hid.sh
    python3 /etc/carlinkit_hid/hid_server.py &
fi

echo "=== [CARLINKIT MOD] HARDWARE HID VIRTUAL KVM ACTIVO Y LISTO ===" > /dev/console
EOF

chmod +x "$OUTPUT_DIR/auto_run.sh"
cp "$OUTPUT_DIR/auto_run.sh" "$OUTPUT_DIR/factory.sh"
cp "$OUTPUT_DIR/auto_run.sh" "$OUTPUT_DIR/update.sh"

# 3. Network Deployer (SSH / Telnet to REDACTED_IP)
cat << 'EOF' > "$OUTPUT_DIR/install_network.sh"
#!/bin/bash
# Despliegue remoto vía Wi-Fi hacia el Carlinkit (REDACTED_IP)
TARGET_IP="${1:-REDACTED_IP}"
echo "[*] Conectando con Carlinkit en: $TARGET_IP"

ssh-keyscan -H "$TARGET_IP" >> ~/.ssh/known_hosts 2>/dev/null || true
sshpass -p "root" scp -o StrictHostKeyChecking=no -r $(dirname "$0")/* "root@$TARGET_IP:/tmp/" 2>/dev/null || scp -r $(dirname "$0")/* "root@$TARGET_IP:/tmp/"

ssh -o StrictHostKeyChecking=no "root@$TARGET_IP" "sh /tmp/auto_run.sh"
echo "[+] Despliegue remoto completado con éxito."
EOF
chmod +x "$OUTPUT_DIR/install_network.sh"

echo "[+] Paquete generado exitosamente en: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
