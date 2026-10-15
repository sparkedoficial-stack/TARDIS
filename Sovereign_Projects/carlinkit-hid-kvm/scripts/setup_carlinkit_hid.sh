#!/bin/sh
# ==============================================================================
# CARLINKIT TO UNIVERSAL USB-C KEYBOARD & MOUSE (HID) CONVERTER
# Godworks System & TARDIS Sovereign Hardware Modification
#
# Configures the internal USB Device Controller (UDC) into a plug-and-play
# USB Composite Human Interface Device (HID) recognized by any PC, Mac,
# Linux, Android, iPad, or Smart TV via USB-C.
# ==============================================================================

set -e

GADGET_DIR="/sys/kernel/config/usb_gadget/carlinkit_hid"

echo "[*] Initializing USB Composite HID Gadget..."

# 1. Stop any existing gadget or legacy Carlinkit AutoKit daemon
if [ -d "$GADGET_DIR" ]; then
    echo "[*] Cleaning up previous gadget..."
    if [ -f "$GADGET_DIR/UDC" ]; then
        echo "" > "$GADGET_DIR/UDC" || true
    fi
    rm -f "$GADGET_DIR/configs/c.1/hid.usb0" 2>/dev/null || true
    rm -f "$GADGET_DIR/configs/c.1/hid.usb1" 2>/dev/null || true
    rmdir "$GADGET_DIR/configs/c.1/strings/0x409" 2>/dev/null || true
    rmdir "$GADGET_DIR/configs/c.1" 2>/dev/null || true
    rmdir "$GADGET_DIR/functions/hid.usb0" 2>/dev/null || true
    rmdir "$GADGET_DIR/functions/hid.usb1" 2>/dev/null || true
    rmdir "$GADGET_DIR/strings/0x409" 2>/dev/null || true
    rmdir "$GADGET_DIR" 2>/dev/null || true
fi

# Kill stock Carlinkit AutoKit/CarPlay daemon if running
killall autobox 2>/dev/null || true
killall box 2>/dev/null || true
killall linkserver 2>/dev/null || true

# 2. Ensure kernel modules are loaded
modprobe libcomposite 2>/dev/null || true

# 3. Mount configfs if not already mounted
if ! mount | grep -q "/sys/kernel/config"; then
    mkdir -p /sys/kernel/config
    mount -t configfs none /sys/kernel/config
fi

# 4. Create USB Gadget Definition
mkdir -p "$GADGET_DIR"
cd "$GADGET_DIR"

# Spoof high-compatibility Logitech USB Composite Keyboard & Mouse
echo 0x046d > idVendor    # Logitech, Inc.
echo 0xc31c > idProduct   # Keyboard/Mouse Composite Device
echo 0x0200 > bcdUSB      # USB 2.0 (High Speed)
echo 0x0100 > bcdDevice   # Device Release 1.0.0
echo 0x00   > bDeviceClass
echo 0x00   > bDeviceSubClass
echo 0x00   > bDeviceProtocol

# English (US) strings
mkdir -p strings/0x409
echo "536AE5AA17D2HID"                     > strings/0x409/serialnumber
echo "Logitech"                            > strings/0x409/manufacturer
echo "USB Optical Mouse & Keyboard Combo"  > strings/0x409/product

# Configuration definition
mkdir -p configs/c.1
mkdir -p configs/c.1/strings/0x409
echo "HID Composite Configuration" > configs/c.1/strings/0x409/configuration
echo 250                           > configs/c.1/MaxPower # 500mA
echo 0x80                          > configs/c.1/bmAttributes # Bus-powered

# ==============================================================================
# 5. FUNCTION 0: USB KEYBOARD (/dev/hidg0)
# ==============================================================================
mkdir -p functions/hid.usb0
echo 1 > functions/hid.usb0/subclass      # Boot Interface Subclass
echo 1 > functions/hid.usb0/protocol      # Keyboard
echo 8 > functions/hid.usb0/report_length # 8-byte standard keyboard report

# Standard 104-key USB Keyboard Report Descriptor (63 bytes)
printf '\x05\x01\x09\x06\xa1\x01\x05\x07\x19\xe0\x29\xe7\x15\x00\x25\x01\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x03\x95\x05\x75\x01\x05\x08\x19\x01\x29\x05\x91\x02\x95\x01\x75\x03\x91\x03\x95\x06\x75\x08\x15\x00\x25\x65\x05\x07\x19\x00\x29\x65\x81\x00\xc0' > functions/hid.usb0/report_desc

# ==============================================================================
# 6. FUNCTION 1: USB MOUSE (/dev/hidg1)
# ==============================================================================
mkdir -p functions/hid.usb1
echo 1 > functions/hid.usb1/subclass      # Boot Interface Subclass
echo 2 > functions/hid.usb1/protocol      # Mouse
echo 4 > functions/hid.usb1/report_length # 4-byte standard mouse report (Buttons, X, Y, Wheel)

# Standard 3-Button Optical Mouse with Scroll Wheel Report Descriptor (52 bytes)
printf '\x05\x01\x09\x02\xa1\x01\x09\x01\xa1\x00\x05\x09\x19\x01\x29\x03\x15\x00\x25\x01\x75\x01\x95\x03\x81\x02\x75\x05\x95\x01\x81\x03\x05\x01\x09\x30\x09\x31\x09\x38\x15\x81\x25\x7f\x75\x08\x95\x03\x81\x06\xc0\xc0' > functions/hid.usb1/report_desc

# 7. Link Functions into Configuration
ln -s functions/hid.usb0 configs/c.1/
ln -s functions/hid.usb1 configs/c.1/

# 8. Bind Gadget to Physical USB Device Controller (UDC)
UDC_NAME=$(ls /sys/class/udc | head -n 1)
if [ -z "$UDC_NAME" ]; then
    echo "[-] Error: No USB Device Controller (UDC) found on this hardware!" >&2
    exit 1
fi

echo "[*] Binding gadget to UDC: $UDC_NAME"
echo "$UDC_NAME" > UDC

# 9. Ensure read/write permissions for control server
chmod 666 /dev/hidg0 2>/dev/null || true
chmod 666 /dev/hidg1 2>/dev/null || true

echo "[+] SUCCESS: Carlinkit is now an active USB Keyboard & Mouse (HID) Client!"
echo "    - Keyboard node: /dev/hidg0"
echo "    - Mouse node   : /dev/hidg1"
