#!/bin/sh
# ==============================================================================
# CARLINKIT UNIVERSAL HID KVM AUTORUN HOOK (EMBEDDED RESILIENT ENGINE)
# Compatible with CPC200-U2W, U2AW, CCPA, 3.0, 4.0, 5.0 and all BusyBox builds
# ==============================================================================

# Feedback to system console
echo "=== [CARLINKIT MOD] INICIANDO INSTALACIÓN HARDWARE HID KVM ===" > /dev/console 2>/dev/null || true

# LED indicator activity: Forzar LUZ ROJA FIJA CONTINUA (Sin parpadeo ni intermitencia)
CUR_DIR="$(cd "$(dirname "$0")" && pwd)"
[ -f "$CUR_DIR/set_carlinkit_led_solid_red.sh" ] && sh "$CUR_DIR/set_carlinkit_led_solid_red.sh" &
for t in /sys/class/leds/*/trigger; do [ -f "$t" ] && echo none > "$t" 2>/dev/null || true; done
for led in /sys/class/leds/*green* /sys/class/leds/*blue*; do [ -f "$led/brightness" ] && echo 0 > "$led/brightness" 2>/dev/null || true; done
for led in /sys/class/leds/*red*; do [ -f "$led/brightness" ] && echo 1 > "$led/brightness" 2>/dev/null || true; done

# Ensure target working directory
TARGET_DIR="/etc/carlinkit_hid"
if ! mkdir -p "$TARGET_DIR" 2>/dev/null; then
    TARGET_DIR="/tmp/carlinkit_hid"
    mkdir -p "$TARGET_DIR" 2>/dev/null || TARGET_DIR="$CUR_DIR"
fi

mkdir -p "$TARGET_DIR/web" 2>/dev/null || true
cp "$CUR_DIR/setup_hid.sh" "$TARGET_DIR/" 2>/dev/null || true
cp "$CUR_DIR/hid_server.py" "$TARGET_DIR/" 2>/dev/null || true
cp "$CUR_DIR/carlinkit_sentinel.py" "$TARGET_DIR/" 2>/dev/null || true
cp "$CUR_DIR/set_carlinkit_led_solid_red.sh" "$TARGET_DIR/" 2>/dev/null || true
cp "$CUR_DIR/web/index.html" "$TARGET_DIR/web/" 2>/dev/null || true
cp "$CUR_DIR/carlinkit-hid.service" /etc/systemd/system/ 2>/dev/null || true

chmod +x "$TARGET_DIR/setup_hid.sh" "$TARGET_DIR/hid_server.py" "$TARGET_DIR/carlinkit_sentinel.py" "$TARGET_DIR/set_carlinkit_led_solid_red.sh" 2>/dev/null || true

# Stop legacy Carlinkit CarPlay/Android Auto daemons
killall -9 autobox 2>/dev/null || true
killall -9 box 2>/dev/null || true
killall -9 linkserver 2>/dev/null || true
killall -9 carplay 2>/dev/null || true

# Reconfigure Wi-Fi AP to SSID "0hack" and password "REDACTED_PHONE"
cp "$CUR_DIR/setup_wifi_0hack.sh" "$TARGET_DIR/" 2>/dev/null || true
chmod +x "$TARGET_DIR/setup_wifi_0hack.sh" 2>/dev/null || true
sh "$TARGET_DIR/setup_wifi_0hack.sh" 2>/dev/null || sh "$CUR_DIR/setup_wifi_0hack.sh" 2>/dev/null || true

# Register autostart for future reboots
if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload 2>/dev/null || true
    systemctl enable carlinkit-hid.service 2>/dev/null || true
fi

if [ -w /etc/init.d/rcS ]; then
    grep -q "carlinkit_hid" /etc/init.d/rcS || echo "$TARGET_DIR/setup_hid.sh &" >> /etc/init.d/rcS
    grep -q "setup_wifi_0hack" /etc/init.d/rcS || echo "$TARGET_DIR/setup_wifi_0hack.sh &" >> /etc/init.d/rcS
    grep -q "carlinkit_sentinel" /etc/init.d/rcS || echo "python3 $TARGET_DIR/carlinkit_sentinel.py &" >> /etc/init.d/rcS
elif [ -w /etc/rc.local ]; then
    grep -q "carlinkit_hid" /etc/rc.local || sed -i '/exit 0/i '"$TARGET_DIR"'/setup_hid.sh\n'"$TARGET_DIR"'/setup_wifi_0hack.sh\npython3 '"$TARGET_DIR"'/carlinkit_sentinel.py &\npython3 '"$TARGET_DIR"'/hid_server.py &\n' /etc/rc.local
fi

# Execute hardware USB Gadget setup (Smart Boot for Mac 14,1 + HID KVM)
cp "$CUR_DIR/setup_carlinkit_smart_boot.sh" "$TARGET_DIR/" 2>/dev/null || true
chmod +x "$TARGET_DIR/setup_carlinkit_smart_boot.sh" 2>/dev/null || true

if [ -f "$TARGET_DIR/setup_carlinkit_smart_boot.sh" ]; then
    sh "$TARGET_DIR/setup_carlinkit_smart_boot.sh" >/dev/console 2>&1 || sh "$TARGET_DIR/setup_hid.sh" >/dev/console 2>&1 || true
elif [ -f "$TARGET_DIR/setup_hid.sh" ]; then
    sh "$TARGET_DIR/setup_hid.sh" >/dev/console 2>&1 || true
else
    sh "$CUR_DIR/setup_hid.sh" >/dev/console 2>&1 || true
fi

# Launch server daemon and sentinel (Device Identifier & Sovereign Controller)
if command -v python3 >/dev/null 2>&1; then
    python3 "$TARGET_DIR/carlinkit_sentinel.py" >/var/log/carlinkit_sentinel.log 2>&1 &
    python3 "$TARGET_DIR/hid_server.py" >/dev/null 2>&1 &
elif command -v python >/dev/null 2>&1; then
    python "$TARGET_DIR/carlinkit_sentinel.py" >/var/log/carlinkit_sentinel.log 2>&1 &
    python "$TARGET_DIR/hid_server.py" >/dev/null 2>&1 &
elif command -v busybox >/dev/null 2>&1 && busybox --list | grep -q "httpd"; then
    busybox httpd -p 8080 -h "$TARGET_DIR/web" 2>/dev/null &
fi

# Maintain Solid Red LED strictly (Zero blinking / no intermission)
[ -f "$TARGET_DIR/set_carlinkit_led_solid_red.sh" ] && sh "$TARGET_DIR/set_carlinkit_led_solid_red.sh" >/dev/null 2>&1 &

echo "=== [CARLINKIT MOD] HARDWARE HID VIRTUAL KVM ACTIVO Y LISTO ===" > /dev/console 2>/dev/null || true
