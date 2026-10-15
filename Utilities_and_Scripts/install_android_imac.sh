#!/bin/bash
set -e
echo "TARDIS SOBERANO: Iniciando instalación de Android-x86..."
sudo mkdir -p /mnt/iso
sudo mount -o loop /home/timemachine/android-x86.iso /mnt/iso

echo "TARDIS SOBERANO: Copiando archivos del sistema operativo..."
sudo mkdir -p /android
sudo cp /mnt/iso/kernel /android/
sudo cp /mnt/iso/initrd.img /android/
sudo cp /mnt/iso/system.sfs /android/
if [ -f /mnt/iso/ramdisk.img ]; then
    sudo cp /mnt/iso/ramdisk.img /android/
fi
sudo mkdir -p /android/data
sudo umount /mnt/iso

echo "TARDIS SOBERANO: Configurando GRUB..."
sudo bash -c 'cat << "EOGRUB" >> /etc/grub.d/40_custom
menuentry "Android-x86" {
    insmod part_gpt
    insmod ext2
    search --no-floppy --set=root --file /android/kernel
    linux /android/kernel root=/dev/ram0 SRC=/android androidboot.hardware=android_x86_64 androidboot.selinux=permissive quiet
    initrd /android/initrd.img
}
EOGRUB'

sudo sed -i 's/GRUB_DEFAULT=0/GRUB_DEFAULT="Android-x86"/' /etc/default/grub
sudo update-grub

echo "TARDIS SOBERANO: Instalación completada. Reiniciando la Mac en Android..."
sudo reboot
