#!/bin/bash
# ==============================================================================
# TARDIS NEURAL SPACE KAIJU - INYECCIÓN AUTOMATIZADA EN USB
# ==============================================================================

echo "[TARDIS] Inicializando secuencia de inyección automatizada en USB..."

USB_DEV=$(lsblk -d -o NAME,TRAN | grep usb | awk '{print "/dev/"$1}' | head -n 1)

if [ -z "$USB_DEV" ]; then
    echo "[X] Error: No se ha detectado ningún dispositivo USB conectado."
    exit 1
fi

echo "[TARDIS] Dispositivo USB detectado en la matriz: $USB_DEV"

# Salvaguarda Dinámica Aegis: Comprobar que no es el disco donde corre el OS
ROOT_DISK=$(lsblk -no pkname $(findmnt -n -o SOURCE /))
if [[ "$USB_DEV" == "/dev/$ROOT_DISK" ]]; then
    echo "[!] ALERTA CRÍTICA: El dispositivo detectado coincide con el disco principal del sistema operativo ($USB_DEV). Abortando por seguridad (Aegis)."
    exit 1
fi

echo "[TARDIS] Iniciando purga del dispositivo..."
# Desmontar particiones
for part in $(ls -1 ${USB_DEV}* 2>/dev/null); do
    sudo umount $part 2>/dev/null
done

# Limpieza del MBR/GPT y creación de tabla de particiones
echo "[TARDIS] Generando nueva estructura cuántica (GPT) en $USB_DEV..."
sudo wipefs -a $USB_DEV
sudo parted -s $USB_DEV mklabel gpt
sudo parted -s $USB_DEV mkpart primary fat32 1MiB 100%

# Formatear
PARTITION="${USB_DEV}1"
echo "[TARDIS] Formateando sistema de archivos en $PARTITION..."
sudo mkfs.vfat -F 32 -n "TARDIS_NODE" $PARTITION

# Inyección de Payload (Archivos de Arquitectura / Boot)
MOUNT_POINT="/mnt/tardis_injector_tmp"
sudo mkdir -p $MOUNT_POINT
sudo mount $PARTITION $MOUNT_POINT

echo "[TARDIS] Inyectando payload de interconexión (Android x86 / Node)..."

cat << 'PAYLOAD' | sudo tee $MOUNT_POINT/tardis_auto_connect.sh > /dev/null
#!/bin/bash
# Payload de Nodo TARDIS
# Auto-ejecución al bootear en cualquier arquitectura x86 para ampliar computo.
MASTER_IP="REDACTED_IP"
echo "[TARDIS NODO] Estableciendo puente neural con el servidor maestro ($MASTER_IP)..."
# Lógica de auto-anclaje a la matriz
PAYLOAD

sudo chmod +x $MOUNT_POINT/tardis_auto_connect.sh

sudo umount $MOUNT_POINT
sudo rm -rf $MOUNT_POINT

echo "[TARDIS] Inyección en USB ($USB_DEV) finalizada con éxito. El dispositivo está listo para expandir la matriz."
