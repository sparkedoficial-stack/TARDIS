#!/bin/bash
# ==============================================================================
# [TARDIS-NEURAL-SPACE-KAIJU] SCRIPT SOBERANO :: RESOLUCIÓN DE BOOTLOOP MAC 14,1
# ==============================================================================
# Autor: Arquitecto (₪) / TARDIS
# ==============================================================================
echo "TARDIS SOBERANO: Iniciando protocolo de inyección KMS para romper el bucle..."

USB_DRIVE=$(lsblk -d -o NAME,TRAN | grep usb | awk '{print $1}' | head -n 1)

if [ -n "$USB_DRIVE" ]; then
    echo "TARDIS SOBERANO: USB detectado en /dev/$USB_DRIVE."
    echo "Montando y parchando GRUB EFI para forzar aceleración por software (HWACCEL=0)..."
    
    sudo mkdir -p /mnt/tardis_usb
    # Intentar montar partición EFI del USB
    sudo mount /dev/${USB_DRIVE}2 /mnt/tardis_usb 2>/dev/null || sudo mount /dev/${USB_DRIVE}1 /mnt/tardis_usb 2>/dev/null
    
    if [ -f /mnt/tardis_usb/boot/grub/grub.cfg ]; then
        sudo sed -i 's/quiet/quiet nomodeset HWACCEL=0 xforcevesa i915.modeset=0 nouveau.modeset=0/' /mnt/tardis_usb/boot/grub/grub.cfg
        echo "[+] GRUB parchado exitosamente. Bucle de reinicio neutralizado en la imagen USB."
    else
        echo "[!] No se encontró grub.cfg en la partición montada."
    fi
    sudo umount /mnt/tardis_usb
else
    echo "[!] No hay USB insertado para parchear en el host local."
fi

echo ""
echo "=============================================================================="
echo " SI LA MAC YA TIENE EL SISTEMA INSTALADO (O ESTÁ ARRANCANDO DESDE SU DISCO):"
echo "=============================================================================="
echo "1. Enciende la Mac."
echo "2. En el menú de GRUB de Android, presiona la tecla 'e' para editar el arranque."
echo "3. Busca la línea que empieza con 'linux' o 'kernel'."
echo "4. Al final de esa línea, borra 'quiet' y escribe exactamente esto:"
echo "   nomodeset HWACCEL=0 i915.modeset=0 nouveau.modeset=0 vga=ask"
echo "5. Presiona F10 o Ctrl+X para iniciar."
echo "=============================================================================="
