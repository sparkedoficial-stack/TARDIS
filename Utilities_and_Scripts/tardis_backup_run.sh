#!/usr/bin/env bash
# Backup soberano: Hyper Jump (NTFS) <- /home/timemachine
set -uo pipefail

SRC="/home/timemachine"
BASE="/run/media/timemachine/Hyper jump/GODWORKS_TARDIS_BACKUP_2026-11-03"
LOG="$BASE/05_LOGS"
mkdir -p "$LOG"

stamp() { date '+%Y-%m-%d %H:%M:%S'; }

echo "[$(stamp)] === INICIO BACKUP ===" | tee -a "$LOG/run.log"

# ---------------------------------------------------------------- 1. GODWORKS
echo "[$(stamp)] FASE 1: GODWORKS SYSTEM ($(du -sh "$SRC/Escritorio/GODWORKS SYSTEM" | cut -f1))" | tee -a "$LOG/run.log"
rsync -rltD --numeric-ids --info=progress2 --stats \
      --exclude='__pycache__/' \
      --exclude='*.pyc' \
      "$SRC/Escritorio/GODWORKS SYSTEM/" \
      "$BASE/01_GODWORKS_SYSTEM/" > "$LOG/rsync_godworks.log" 2>&1
RC1=$?
echo "[$(stamp)] FASE 1 terminada rc=$RC1" | tee -a "$LOG/run.log"

# ------------------------------------------------------------------- 2. HOME
echo "[$(stamp)] FASE 2: HOME COMPLETO" | tee -a "$LOG/run.log"
rsync -rltD --numeric-ids --info=progress2 --stats \
      --exclude='/Escritorio/GODWORKS SYSTEM/' \
      --exclude='.cache/' \
      "$SRC/" \
      "$BASE/02_HOME_COMPLETO/" > "$LOG/rsync_home.log" 2>&1
RC2=$?
echo "[$(stamp)] FASE 2 terminada rc=$RC2" | tee -a "$LOG/run.log"

# --------------------------------------------------------------- 3. METADATOS
echo "[$(stamp)] FASE 3: metadatos de permisos" | tee -a "$LOG/run.log"
{
  echo "# Inventario de permisos, propietarios y timestamps"
  find "$SRC" -xdev -printf '%m;%u;%g;%s;%TY-%Tm-%Td %TH:%TM:%TS;%p\n' 2>/dev/null
} > "$BASE/03_SISTEMA/inventario_permisos_home.csv"

tar -C / -czf "$BASE/03_SISTEMA/metadatos_home.tar.gz" \
    --exclude='home/timemachine/.cache' \
    --exclude='home/timemachine/Escritorio/GODWORKS SYSTEM/vault' \
    --exclude='home/timemachine/Escritorio/GODWORKS SYSTEM/data' \
    --exclude='home/timemachine/.local/share/Steam' \
    --exclude='home/timemachine/.ollama' \
    --exclude='home/timemachine/.nvm' \
    --exclude='home/timemachine/.gemini' \
    --exclude='home/timemachine/Descargas' \
    --exclude='home/timemachine/omarchy_payload' \
    --exclude='home/timemachine/snap' \
    home/timemachine 2> "$LOG/tar_metadatos.err" || true

echo "[$(stamp)] === BACKUP FINALIZADO rc1=$RC1 rc2=$RC2 ===" | tee -a "$LOG/run.log"
df -h "$BASE" | tail -1 | tee -a "$LOG/run.log"
