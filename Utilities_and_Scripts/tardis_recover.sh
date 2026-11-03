#!/usr/bin/env bash
# ============================================================================
#  TARDIS :: Recuperación automática tras desconexión del hub USB (2026-11-03)
#
#  Espera a que reaparezcan las dos unidades, repara/monta, sincroniza los
#  cambios vivos, parchea y verifica los manifiestos SHA-256, y escribe un
#  informe. Se ejecuta desacoplado del TTY.
#
#  Uso:  nohup bash tardis_recover.sh </dev/null >/dev/null 2>&1 &
# ============================================================================
set -uo pipefail

HJ_UUID="183AB3153AB2EEBE"
HJ_MNT="/run/media/timemachine/Hyper jump"
USB_LABEL="TARDIS_KIT"
USB_MNT="/run/media/timemachine/TARDIS_KIT"
LOG="/tmp/tardis_recover.log"
DEADLINE=$(( $(date +%s) + 43200 ))   # 12 h
PATCHER="/home/timemachine/tardis_patch_manifest.py"
PATCHER_G="/home/timemachine/tardis_patch_manifest_generic.py"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }
say() { log "$*"; }

wait_for() {  # $1 = ruta by-*, $2 = etiqueta
  while [ ! -e "$1" ]; do
    [ "$(date +%s)" -gt "$DEADLINE" ] && { say "TIMEOUT esperando $2"; return 1; }
    sleep 15
  done
  say "Detectado $2 -> $(readlink -f "$1")"
  return 0
}

repair_and_mount() {  # $1 = /dev/xxx  $2 = punto de montaje
  local dev="$1" mnt="$2" name="${1##*/}" i
  for i in 1 2 3; do
    say "Repair $dev (intento $i)"
    timeout 180 gdbus call --system --dest org.freedesktop.UDisks2 \
      --object-path "/org/freedesktop/UDisks2/block_devices/$name" \
      --method org.freedesktop.UDisks2.Filesystem.Repair "{}" >> "$LOG" 2>&1
    sleep 3
    if timeout 120 udisksctl mount -b "$dev" >> "$LOG" 2>&1; then
      findmnt -no TARGET,SOURCE,FSTYPE,OPTIONS "$mnt" >> "$LOG" 2>&1
      case "$(findmnt -no OPTIONS "$mnt" 2>/dev/null)" in
        *rw*) say "Montado rw: $mnt"; return 0 ;;
        *) say "Montado pero NO rw: $mnt" ;;
      esac
    fi
    sleep 5
  done
  return 1
}

say "=== VIGILANTE DE RECUPERACIÓN INICIADO (hub USB desconectado) ==="

# ---------------------------------------------------------------- 1. HYPER JUMP
if wait_for "/dev/disk/by-uuid/$HJ_UUID" "Hyper jump"; then
  HJ_DEV=$(readlink -f "/dev/disk/by-uuid/$HJ_UUID")
  if repair_and_mount "$HJ_DEV" "$HJ_MNT"; then
    R="$HJ_MNT/GODWORKS_TARDIS_BACKUP_2026-11-03"
    if [ -d "$R" ]; then
      say "Sincronizando delta del HOME"
      rsync -rltD --numeric-ids --stats \
        --exclude='Escritorio/GODWORKS SYSTEM/' --exclude='.cache/' \
        /home/timemachine/ "$R/02_HOME_COMPLETO/" >> "$LOG" 2>&1
      say "Sincronizando delta de GODWORKS"
      rsync -rltD --numeric-ids --stats \
        --exclude='__pycache__/' --exclude='*.pyc' \
        "/home/timemachine/Escritorio/GODWORKS SYSTEM/" "$R/01_GODWORKS_SYSTEM/" >> "$LOG" 2>&1

      if [ -f "$R/MANIFIESTO_SHA256.txt" ]; then
        CUT=$(( $(stat -c %Y "$R/MANIFIESTO_SHA256.txt") - 120 ))
        say "Parcheando manifiesto (cutoff=$CUT)"
        python3 "$PATCHER" "$CUT" >> "$LOG" 2>&1
      fi

      say "Verificando manifiesto completo de Hyper jump (puede tardar ~30 min)"
      ( cd "$R" && sha256sum -c MANIFIESTO_SHA256.txt ) > /tmp/check_recover_hj.log 2>&1
      OK=$(grep -c 'OK$' /tmp/check_recover_hj.log); FAIL=$(grep -c FAILED /tmp/check_recover_hj.log)
      say "Hyper jump: OK=$OK FAILED=$FAIL"
    else
      say "ERROR: no existe $R"
    fi
  fi
fi

# ---------------------------------------------------------------------- 2. USB
if wait_for "/dev/disk/by-label/$USB_LABEL" "TARDIS_KIT"; then
  USB_DEV=$(readlink -f "/dev/disk/by-label/$USB_LABEL")
  if repair_and_mount "$USB_DEV" "$USB_MNT"; then
    if [ -d "$HJ_MNT/GODWORKS_TARDIS_BACKUP_2026-11-03" ]; then
      say "Actualizando docs del kit desde Hyper jump"
      cp -a "$HJ_MNT/GODWORKS_TARDIS_BACKUP_2026-11-03/00_LEEME_PRIMERO.md" \
            "$USB_MNT/01_RECONSTRUCCION/00_LEEME_COPIA_MAESTRA.md" 2>/dev/null
      cp -a "$HJ_MNT/GODWORKS_TARDIS_BACKUP_2026-11-03/04_RECONSTRUCCION/." \
            "$USB_MNT/01_RECONSTRUCCION/" 2>/dev/null
    fi
    say "Copiando paquete de claves y credenciales"
    CRED="$USB_MNT/11_CLAVES_Y_CREDENCIALES"
    mkdir -p "$CRED"
    for item in .ssh .gnupg .netrc .npmrc .pypirc .docker .config/git .config/gh .config/huggingface; do
      [ -e "/home/timemachine/$item" ] || continue
      mkdir -p "$CRED/$(dirname "$item")"
      rsync -rlt --no-links "/home/timemachine/$item" "$CRED/$(dirname "$item")/" >> "$LOG" 2>&1
    done

    say "Parcheando manifiesto USB (todas las carpetas)"    python3 "$PATCHER_G" "$USB_MNT" \
      01_RECONSTRUCCION 02_SISTEMA 03_GODWORKS_SYSTEM 04_CONFIG_USUARIO \
      05_PROYECTOS_TARDIS 06_MODELOS 07_DISTRIBUCION_TARDIS 08_MODELOS_GGUF \
      09_DATOS_RUNTIME 10_MODELOS_OLLAMA 11_CLAVES_Y_CREDENCIALES >> "$LOG" 2>&1
    say "Verificando manifiesto USB"
    ( cd "$USB_MNT" && sha256sum -c MANIFIESTO_SHA256.txt ) > /tmp/check_recover_usb.log 2>&1
    OKU=$(grep -c 'OK$' /tmp/check_recover_usb.log); FAILU=$(grep -c FAILED /tmp/check_recover_usb.log)
    say "USB: OK=$OKU FAILED=$FAILU"
  fi
fi

# ------------------------------------------------------------------ 3. INFORME
REPORT="/tmp/tardis_recover_report.md"
{
  echo "# Informe de recuperación post-desconexión"
  echo
  echo "- Generado: $(date -Is)"
  echo "- Hyper jump: ${OK:-?} OK / ${FAIL:-?} FAILED"
  echo "- USB TARDIS_KIT: ${OKU:-?} OK / ${FAILU:-?} FAILED"
  echo
  echo "## Fallos Hyper jump"
  grep FAILED /tmp/check_recover_hj.log 2>/dev/null | head -30
  echo
  echo "## Fallos USB"
  grep FAILED /tmp/check_recover_usb.log 2>/dev/null | head -30
} > "$REPORT" 2>&1
[ -d "$HJ_MNT/GODWORKS_TARDIS_BACKUP_2026-11-03/05_LOGS" ] && \
  cp -a "$REPORT" "$HJ_MNT/GODWORKS_TARDIS_BACKUP_2026-11-03/05_LOGS/" 2>/dev/null

# ------------------------------------------------------- 4. DESMONTAJE LIMPIO
say "Desmontando para vaciar cachés (flush)"
timeout 120 udisksctl unmount -b "${USB_DEV:-/dev/null}" >> "$LOG" 2>&1
timeout 120 udisksctl unmount -b "${HJ_DEV:-/dev/null}" >> "$LOG" 2>&1
sync
say "=== FIN DEL VIGILANTE ==="
