#!/bin/bash
# ==============================================================================
# CARLINKIT VIRTUAL KVM LOCAL SYSTEMD SERVICE INSTALLER
# Sets up uinput permissions and configures the detached background service.
# ==============================================================================
set -euo pipefail

SERVICE_PATH="/etc/systemd/system/carlinkit-hid.service"
LOG_FILE="/var/log/carlinkit_hid.log"

echo "[*] Configuring uinput kernel permissions..."
sudo modprobe uinput || true

# Udev rule to allow reliable access
cat << 'EOF' | sudo tee /etc/udev/rules.d/99-carlinkit-uinput.rules > /dev/null
KERNEL=="uinput", MODE="0660", GROUP="input", TAG+="uaccess"
EOF
sudo udevadm control --reload-rules || true
sudo udevadm trigger || true

echo "[*] Creating systemd service: $SERVICE_PATH"
cat << EOF | sudo tee "$SERVICE_PATH" > /dev/null
[Unit]
Description=Carlinkit Universal Virtual Mouse and Keyboard (HID) Engine
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/timemachine/carlinkit-hid-kvm
ExecStart=/usr/bin/python3 /home/timemachine/carlinkit-hid-kvm/server/carlinkit_hid_server.py
Restart=always
RestartSec=3
KillMode=process
StandardInput=null
StandardOutput=append:$LOG_FILE
StandardError=append:$LOG_FILE

[Install]
WantedBy=multi-user.target
EOF

sudo touch "$LOG_FILE"
sudo chmod 644 "$LOG_FILE"

echo "[*] Reloading and starting carlinkit-hid service..."
sudo systemctl daemon-reload
sudo systemctl enable carlinkit-hid.service
sudo systemctl restart carlinkit-hid.service

sleep 1
if sudo systemctl is-active --quiet carlinkit-hid.service; then
    echo "[+] SUCCESS: carlinkit-hid service is active and running!"
else
    echo "[-] Service failed to start. Journal logs:"
    sudo journalctl -u carlinkit-hid.service -n 20 --no-pager
    exit 1
fi
