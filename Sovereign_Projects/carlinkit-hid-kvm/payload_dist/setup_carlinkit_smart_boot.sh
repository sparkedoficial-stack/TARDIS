#!/bin/sh
# ==============================================================================
# CARLINKIT SMART BOOT ENGINE FOR iMAC 14,1 (COMPOSITE GADGET: STORAGE + HID)
# Allows the Mac to boot from the attached USB storage while keeping full
# Wi-Fi remote access (SSH & Web KVM) open to the Carlinkit SoC.
# ==============================================================================
set -e

GADGET_DIR="/sys/kernel/config/usb_gadget/carlinkit_smart_boot"

# Forzar LUZ ROJA FIJA CONTINUA (Sin parpadeo ni intermitencia)
for t in /sys/class/leds/*/trigger; do [ -f "$t" ] && echo none > "$t" 2>/dev/null || true; done
for led in /sys/class/leds/*green* /sys/class/leds/*blue*; do [ -f "$led/brightness" ] && echo 0 > "$led/brightness" 2>/dev/null || true; done
for led in /sys/class/leds/*red*; do [ -f "$led/brightness" ] && echo 1 > "$led/brightness" 2>/dev/null || true; done

echo "[*] Configurando Gadget Inteligente para arranque de iMac 14,1..." > /dev/console 2>/dev/null || true

# 1. Limpieza de gadgets previos
if [ -d "$GADGET_DIR" ]; then
    if [ -f "$GADGET_DIR/UDC" ]; then
        echo "" > "$GADGET_DIR/UDC" || true
    fi
    rm -f "$GADGET_DIR/configs/c.1/mass_storage.usb0" 2>/dev/null || true
    rm -f "$GADGET_DIR/configs/c.1/hid.usb0" 2>/dev/null || true
    rm -f "$GADGET_DIR/configs/c.1/hid.usb1" 2>/dev/null || true
    rmdir "$GADGET_DIR/configs/c.1/strings/0x409" 2>/dev/null || true
    rmdir "$GADGET_DIR/configs/c.1" 2>/dev/null || true
    rmdir "$GADGET_DIR/functions/mass_storage.usb0" 2>/dev/null || true
    rmdir "$GADGET_DIR/functions/hid.usb0" 2>/dev/null || true
    rmdir "$GADGET_DIR/functions/hid.usb1" 2>/dev/null || true
    rmdir "$GADGET_DIR/strings/0x409" 2>/dev/null || true
    rmdir "$GADGET_DIR" 2>/dev/null || true
fi

# 2. Asegurar módulos
modprobe libcomposite 2>/dev/null || true

# 3. Montar configfs
if ! mount | grep -q "/sys/kernel/config"; then
    mkdir -p /sys/kernel/config
    mount -t configfs none /sys/kernel/config
fi

# 4. Crear Gadget
mkdir -p "$GADGET_DIR"
cd "$GADGET_DIR"

# Spoof Apple Bootable Device
echo 0x05ac > idVendor     # Apple, Inc.
echo 0x12a8 > idProduct    # Composite
echo 0x0210 > bcdUSB       # USB 2.1
echo 0x0100 > bcdDevice

mkdir -p strings/0x409
echo "Apple, Inc."                         > strings/0x409/manufacturer
echo "Smart Mac Boot & Remote Engine"     > strings/0x409/product
echo "536AE5AA17D2BOOT"                   > strings/0x409/serialnumber

mkdir -p configs/c.1
mkdir -p configs/c.1/strings/0x409
echo "iMac 14,1 Boot + Remote KVM"        > configs/c.1/strings/0x409/configuration
echo 500                                  > configs/c.1/MaxPower
echo 0x80                                 > configs/c.1/bmAttributes

# ==============================================================================
# FUNCIÓN 1: USB MASS STORAGE GADGET (UNIDAD BOOTEABLE PARA EL iMAC)
# ==============================================================================
mkdir -p functions/mass_storage.usb0
echo 1 > functions/mass_storage.usb0/stall
echo 0 > functions/mass_storage.usb0/lun.0/cdrom
echo 0 > functions/mass_storage.usb0/lun.0/ro
echo 0 > functions/mass_storage.usb0/lun.0/nofua
echo 1 > functions/mass_storage.usb0/lun.0/removable

# Detectar memoria física en puerto USB-A del Carlinkit
BACKING_STORAGE=""
for dev in /dev/sda /dev/sdb /dev/mmcblk0; do
    if [ -b "$dev" ]; then
        BACKING_STORAGE="$dev"
        break
    fi
done

if [ -n "$BACKING_STORAGE" ]; then
    echo "[+] Exponiendo $BACKING_STORAGE como disco de arranque..." > /dev/console 2>/dev/null || true
    echo "$BACKING_STORAGE" > functions/mass_storage.usb0/lun.0/file
fi

# ==============================================================================
# FUNCIÓN 2 & 3: TECLADO Y RATÓN HID (KVM FÍSICO PARA CONTROL REMOTO)
# ==============================================================================
mkdir -p functions/hid.usb0
echo 1 > functions/hid.usb0/subclass
echo 1 > functions/hid.usb0/protocol
echo 8 > functions/hid.usb0/report_length
printf '\x05\x01\x09\x06\xa1\x01\x05\x07\x19\xe0\x29\xe7\x15\x00\x25\x01\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x03\x95\x05\x75\x01\x05\x08\x19\x01\x29\x05\x91\x02\x95\x01\x75\x03\x91\x03\x95\x06\x75\x08\x15\x00\x25\x65\x05\x07\x19\x00\x29\x65\x81\x00\xc0' > functions/hid.usb0/report_desc

mkdir -p functions/hid.usb1
echo 1 > functions/hid.usb1/subclass
echo 2 > functions/hid.usb1/protocol
echo 4 > functions/hid.usb1/report_length
printf '\x05\x01\x09\x02\xa1\x01\x09\x01\xa1\x00\x05\x09\x19\x01\x29\x03\x15\x00\x25\x01\x75\x01\x95\x03\x81\x02\x75\x05\x95\x01\x81\x03\x05\x01\x09\x30\x09\x31\x09\x38\x15\x81\x25\x7f\x75\x08\x95\x03\x81\x06\xc0\xc0' > functions/hid.usb1/report_desc

# Enlazar funciones
[ -n "$BACKING_STORAGE" ] && ln -s functions/mass_storage.usb0 configs/c.1/
ln -s functions/hid.usb0 configs/c.1/
ln -s functions/hid.usb1 configs/c.1/

# Activar en UDC
UDC_NAME=$(ls /sys/class/udc | head -n 1)
echo "$UDC_NAME" > UDC

echo "[+] DISCO BOOTEABLE INTELIGENTE Y KVM ACTIVOS EN UDC: $UDC_NAME" > /dev/console 2>/dev/null || true
