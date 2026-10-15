#!/bin/sh
# ==============================================================================
# CARLINKIT WI-FI AP RECONFIGURATION: SSID "0hack" | WPA2 "REDACTED_PHONE"
# ==============================================================================

NEW_SSID="0hack"
NEW_PASS="REDACTED_PHONE"

echo "=== [0hack MOD] RECONFIGURANDO PUNTO DE ACCESO WI-FI A: $NEW_SSID ===" > /dev/console 2>/dev/null || true

# 1. Detectar archivo de configuración activo de hostapd mediante /proc
ACTIVE_HOSTAPD_CONF=""
if pgrep hostapd >/dev/null 2>&1; then
    for pid in $(pgrep hostapd); do
        cmd=$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null || true)
        for arg in $cmd; do
            if [ -f "$arg" ] && grep -q "ssid=" "$arg" 2>/dev/null; then
                ACTIVE_HOSTAPD_CONF="$arg"
                break 2
            fi
        done
    done
fi

# 2. Lista de posibles ubicaciones de configuración de Wi-Fi / hostapd
TARGET_CONFS="$ACTIVE_HOSTAPD_CONF /etc/hostapd.conf /etc/hostapd/hostapd.conf /tmp/hostapd.conf /data/hostapd.conf /userdata/hostapd.conf /etc/wireless/hostapd.conf /etc/config.ini /data/config.ini"

MODIFIED=0
for conf in $TARGET_CONFS; do
    if [ -f "$conf" ] && [ -w "$conf" ]; then
        echo "[+] Modificando archivo: $conf" > /dev/console 2>/dev/null || true
        [ ! -f "${conf}.orig" ] && cp "$conf" "${conf}.orig" 2>/dev/null || true
        
        # Actualizar SSID
        if grep -q "^ssid=" "$conf"; then
            sed -i "s/^ssid=.*/ssid=$NEW_SSID/" "$conf"
        elif grep -q "ssid\s*=" "$conf"; then
            sed -i "s/ssid\s*=.*/ssid=$NEW_SSID/" "$conf"
        fi
        
        # Actualizar o insertar WPA Passphrase
        if grep -q "^wpa_passphrase=" "$conf"; then
            sed -i "s/^wpa_passphrase=.*/wpa_passphrase=$NEW_PASS/" "$conf"
        elif grep -q "wpa_passphrase\s*=" "$conf"; then
            sed -i "s/wpa_passphrase\s*=.*/wpa_passphrase=$NEW_PASS/" "$conf"
        else
            echo "wpa_passphrase=$NEW_PASS" >> "$conf"
        fi

        # Reemplazar claves y nombres de fábrica en archivos INI
        sed -i "s/12345678/$NEW_PASS/g" "$conf" 2>/dev/null || true
        sed -i "s/AutoKit_[^ \"']*/$NEW_SSID/g" "$conf" 2>/dev/null || true
        sed -i "s/AutoKit/$NEW_SSID/g" "$conf" 2>/dev/null || true

        MODIFIED=1
    fi
done

# 3. Si no existe ninguno o el rootfs es read-only, crear configuración dedicada en /tmp
if [ "$MODIFIED" -eq 0 ] || [ -z "$ACTIVE_HOSTAPD_CONF" ]; then
    FALLBACK_CONF="/tmp/hostapd_0hack.conf"
    echo "[+] Creando configuración dedicada en $FALLBACK_CONF" > /dev/console 2>/dev/null || true
    cat << EOF > "$FALLBACK_CONF"
interface=wlan0
driver=nl80211
ssid=$NEW_SSID
hw_mode=a
channel=36
wmm_enabled=1
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=$NEW_PASS
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP
rsn_pairwise=CCMP
EOF
    ACTIVE_HOSTAPD_CONF="$FALLBACK_CONF"
fi

# 4. Reiniciar daemon hostapd con la nueva configuración
if pgrep hostapd >/dev/null 2>&1; then
    echo "[*] Reiniciando hostapd..." > /dev/console 2>/dev/null || true
    killall -9 hostapd 2>/dev/null || true
    sleep 1
    if [ -n "$ACTIVE_HOSTAPD_CONF" ] && [ -f "$ACTIVE_HOSTAPD_CONF" ]; then
        hostapd -B "$ACTIVE_HOSTAPD_CONF" 2>/dev/null || /usr/sbin/hostapd -B "$ACTIVE_HOSTAPD_CONF" 2>/dev/null || true
    fi
fi

echo "=== [0hack MOD] RED WI-FI ACTIVA: SSID=$NEW_SSID | PASSWORD=$NEW_PASS ===" > /dev/console 2>/dev/null || true
