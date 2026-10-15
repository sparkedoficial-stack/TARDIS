#!/bin/bash
# ==============================================================================
# CARLINKIT USB DRIVE PROVISIONING & FLASH PREPARATION ENGINE
# Formats USB to FAT32 (MBR) and deploys full HID KVM payload suite
# ==============================================================================
set -euo pipefail

TARGET_DEV="/dev/sda"
PARTITION="${TARGET_DEV}1"
MOUNT_POINT="/mnt/carlinkit_usb_flash"
SOURCE_DIR="/home/timemachine/carlinkit-hid-kvm/payload_dist"

echo "[1/6] Realizando auditoría de seguridad del dispositivo objetivo ($TARGET_DEV)..."
IS_USB=$(udevadm info --query=property --name="$TARGET_DEV" | grep -c "ID_BUS=usb" || true)
if [ "$IS_USB" -lt 1 ]; then
    echo "[-] ERROR CRÍTICO: $TARGET_DEV no es una unidad USB. Abortando por seguridad." >&2
    exit 1
fi

ROOT_DISK=$(lsblk -no pkname $(findmnt -n -o SOURCE /))
if [[ "$TARGET_DEV" == "/dev/$ROOT_DISK" ]]; then
    echo "[-] ERROR CRÍTICO: $TARGET_DEV es el disco del sistema operativo. Abortando." >&2
    exit 1
fi
echo "[+] Dispositivo verificado: USB Mass Storage seguro para aprovisionamiento."

echo "[2/6] Desmontando particiones previas en $TARGET_DEV..."
for part in $(ls -1 ${TARGET_DEV}* 2>/dev/null); do
    sudo umount "$part" 2>/dev/null || true
done

echo "[3/6] Creando tabla de particiones MBR (MS-DOS) y partición primaria FAT32..."
sudo wipefs -a "$TARGET_DEV"
sudo parted -s "$TARGET_DEV" mklabel msdos
sudo parted -s "$TARGET_DEV" mkpart primary fat32 1MiB 100%
sudo parted -s "$TARGET_DEV" set 1 boot on

sudo partprobe "$TARGET_DEV"
sleep 1
sudo udevadm settle

echo "[4/6] Formateando sistema de archivos FAT32 en $PARTITION con etiqueta CARLINKIT..."
sudo mkfs.vfat -F 32 -n "CARLINKIT" "$PARTITION"

echo "[5/6] Montando partición y copiando suite completa de payloads..."
sudo mkdir -p "$MOUNT_POINT"
sudo mount "$PARTITION" "$MOUNT_POINT"

# Sincronizar payload_dist
sudo cp -r "$SOURCE_DIR"/* "$MOUNT_POINT/"

# Añadir aliases universales para compatibilidad con todos los cargadores de Carlinkit
sudo cp "$MOUNT_POINT/auto_run.sh" "$MOUNT_POINT/autorun.sh"
sudo cp "$MOUNT_POINT/auto_run.sh" "$MOUNT_POINT/U2W.sh"

# Copiar documentación
sudo cp "/home/timemachine/carlinkit-hid-kvm/README.md" "$MOUNT_POINT/"

# Generar guía de instrucciones en texto plano legible en cualquier sistema
cat << 'EOF' | sudo tee "$MOUNT_POINT/INSTRUCCIONES_MODIFICACION.txt" > /dev/null
================================================================================
⚡ GUÍA DE MODIFICACIÓN HARDWARE - CARLINKIT A TECLADO Y RATÓN VIRTUAL (HID KVM)
================================================================================

Esta memoria USB ha sido aprovisionada con el firmware y motor de inyección HID.

PASOS PARA COMPLETAR LA MODIFICACIÓN EN EL CARLINKIT:

1. DESCONECTAR Y PREPARAR:
   - Desconecta esta memoria USB de tu computadora.

2. CONECTAR AL CARLINKIT:
   - Conecta esta memoria USB al puerto USB-A hembra de tu adaptador Carlinkit.

3. ALIMENTAR EL DONGLE:
   - Enchufa el extremo USB-C del Carlinkit a una fuente de alimentación USB estándar
     (cargador de teléfono, puerto USB de PC o hub USB alimentado).
   - ¡NO LO HAGAS DENTRO DEL COCHE! Usa un cargador estable.

4. EJECUCIÓN AUTOMÁTICA DEL PAYLOAD:
   - El bootloader del Carlinkit detectará 'auto_run.sh' / 'factory.sh' en la raíz.
   - La luz LED del Carlinkit cambiará de color o parpadeará mientras instala
     los controladores de Gadget USB HID (/dev/hidg0 y /dev/hidg1) y el servidor web.
   - Una vez finalizado (unos 30-45 segundos), el LED quedará en estado fijo.

5. CONEXIÓN Y USO:
   - Ahora conecta el extremo USB-C del Carlinkit a cualquier dispositivo que
     desees controlar (PC, Mac, iPad, Android, Smart TV, consola o servidor).
     El sistema lo reconocerá de inmediato como un conjunto de Teclado y Ratón Logitech.
   - Desde tu teléfono móvil, busca la red Wi-Fi emitida por el Carlinkit
     (por defecto: AutoKit_xxxx o similar, clave: 12345678).
   - Abre el navegador web en:
     http://REDACTED_IP:8080

¡Listo! Ya tienes el control total como ratón táctil y teclado físico universal.
================================================================================
EOF

sudo chmod -R 755 "$MOUNT_POINT"

echo "[6/6] Sincronizando búferes del kernel (sync) y desmontando unidad..."
sync
sudo umount "$MOUNT_POINT"
sudo rm -rf "$MOUNT_POINT"

echo "[+] SUCESSO TOTAL: La memoria USB está 100% lista para modificar el Carlinkit."
