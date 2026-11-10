#!/usr/bin/env bash
# ============================================================================
#  TARDIS :: Fase B — reparar y verificar la USB TARDIS_KIT (exFAT)
#  Se ejecuta DESPUÉS de la fase A (Hyper jump) y de forma serializada.
# ============================================================================
set -uo pipefail

LOG="/tmp/tardis_fase_b.log"
HJ_MNT="/run/media/timemachine/Hyper jump"
USB_MNT="/run/media/timemachine/TARDIS_KIT"
PATCHER_G="/home/timemachine/tardis_patch_manifest_generic.py"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

USB_DEV=$(readlink -f "/dev/disk/by-label/TARDIS_KIT" 2>/dev/null)
[ -b "$USB_DEV" ] || { log "USB no presente; abortando"; exit 1; }
NAME="${USB_DEV##*/}"
log "Dispositivo USB: $USB_DEV"

# 1. Desmontar
if findmnt -no TARGET "$USB_MNT" >/dev/null 2>&1; then
  log "Desmontando $USB_MNT"
  timeout 120 udisksctl unmount -b "$USB_DEV" >> "$LOG" 2>&1 || \
  timeout 120 udisksctl unmount -f -b "$USB_DEV" >> "$LOG" 2>&1
fi
for i in $(seq 1 20); do
  findmnt -no TARGET "$USB_MNT" >/dev/null 2>&1 || break
  sleep 2
done

# 2. Reparar exFAT (fsck.exfat vía udisks)
log "Reparando exFAT"
timeout 300 gdbus call --system --dest org.freedesktop.UDisks2 \
  --object-path "/org/freedesktop/UDisks2/block_devices/$NAME" \
  --method org.freedesktop.UDisks2.Filesystem.Repair "{}" >> "$LOG" 2>&1
sleep 3

# 3. Montar
for i in 1 2 3 4 5; do
  timeout 120 udisksctl mount -b "$USB_DEV" >> "$LOG" 2>&1 && break
  sleep 4
done
findmnt -no TARGET,SOURCE,FSTYPE,OPTIONS "$USB_MNT" | tee -a "$LOG"

# 4. Documentos actualizados desde Hyper jump
if [ -d "$HJ_MNT/GODWORKS_TARDIS_BACKUP_2026-11-03/04_RECONSTRUCCION" ]; then
  log "Copiando documentos maestros"
  cp -a "$HJ_MNT/GODWORKS_TARDIS_BACKUP_2026-11-03/00_LEEME_PRIMERO.md" \
        "$USB_MNT/01_RECONSTRUCCION/00_LEEME_COPIA_MAESTRA.md" 2>/dev/null
  cp -a "$HJ_MNT/GODWORKS_TARDIS_BACKUP_2026-11-03/04_RECONSTRUCCION/." \
        "$USB_MNT/01_RECONSTRUCCION/" 2>/dev/null
fi

# 5. Paquete de claves y credenciales
log "Copiando claves y credenciales"
CRED="$USB_MNT/11_CLAVES_Y_CREDENCIALES"
mkdir -p "$CRED"
for item in .ssh .gnupg .netrc .npmrc .pypirc .docker .config/git .config/gh .config/huggingface; do
  [ -e "/home/timemachine/$item" ] || continue
  mkdir -p "$CRED/$(dirname "$item")"
  rsync -rlt --no-links "/home/timemachine/$item" "$CRED/$(dirname "$item")/" >> "$LOG" 2>&1
done
sync

# 6. Manifiesto
log "Parcheando manifiesto USB"
python3 "$PATCHER_G" "$USB_MNT" \
  01_RECONSTRUCCION 02_SISTEMA 03_GODWORKS_SYSTEM 04_CONFIG_USUARIO \
  05_PROYECTOS_TARDIS 06_MODELOS 07_DISTRIBUCION_TARDIS 08_MODELOS_GGUF \
  09_DATOS_RUNTIME 10_MODELOS_OLLAMA 11_CLAVES_Y_CREDENCIALES >> "$LOG" 2>&1

# 7. Verificación completa
log "Verificando manifiesto USB"
( cd "$USB_MNT" && ionice -c 3 nice -n 15 sha256sum -c MANIFIESTO_SHA256.txt ) > /tmp/check_usb2.log 2>&1
OK=$(grep -c 'OK$' /tmp/check_usb2.log); FAIL=$(grep -c FAILED /tmp/check_usb2.log)
log "USB: OK=$OK FAILED=$FAIL"
grep FAILED /tmp/check_usb2.log | head -20 >> "$LOG"

# 8. Desmontaje limpio
sync
log "Desmontando para flush"
timeout 180 udisksctl unmount -b "$USB_DEV" >> "$LOG" 2>&1
log "=== FASE B COMPLETADA ==="
