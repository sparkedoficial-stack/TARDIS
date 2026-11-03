#!/usr/bin/env bash
# Kit soberano de reconstrucción TARDIS para USB de 32 GB (exFAT)
set -uo pipefail

SRC="/home/timemachine"
PROJ="$SRC/Escritorio/GODWORKS SYSTEM"
HJ="/run/media/timemachine/Hyper jump/GODWORKS_TARDIS_BACKUP_2026-11-03"
USB="/run/media/timemachine/TARDIS_KIT"

log() { printf '\033[1;36m▸ %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m✔ %s\033[0m\n' "$*"; }

[ -d "$USB" ] || { echo "USB no montada"; exit 1; }

mkdir -p "$USB"/{01_RECONSTRUCCION,02_SISTEMA,03_GODWORKS_SYSTEM,04_CONFIG_USUARIO,05_PROYECTOS_TARDIS,06_MODELOS}

# ---------------------------------------------------------------- 1. DOCS
log "1/6 Documentación de reconstrucción"
cp -a "$HJ/00_LEEME_PRIMERO.md" "$USB/" 2>/dev/null
cp -a "$HJ/04_RECONSTRUCCION/." "$USB/01_RECONSTRUCCION/" 2>/dev/null
ok "Docs copiados"

# --------------------------------------------------------------- 2. SISTEMA
log "2/6 Snapshot del sistema operativo"
if command -v rsync >/dev/null; then
  rsync -rlt --no-links --info=progress2 "$HJ/03_SISTEMA/" "$USB/02_SISTEMA/" 2>/dev/null
else
  cp -a "$HJ/03_SISTEMA/." "$USB/02_SISTEMA/"
fi
ok "Snapshot copiado"

# -------------------------------------------------------------- 3. CÓDIGO
log "3/6 Código fuente de GODWORKS SYSTEM"
rsync -rlt --no-links --info=progress2 \
  --exclude='vault/' \
  --exclude='data/' \
  --exclude='dist/' \
  --exclude='tardis_custom_rom/' \
  --exclude='_selfmod_backups/' \
  --exclude='conversations_archive/' \
  --exclude='videos/' \
  --exclude='.venv-linux/' \
  --exclude='.venv-whatsapp/' \
  --exclude='.venv-build-*/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='*.log' \
  "$PROJ/" "$USB/03_GODWORKS_SYSTEM/" 2>/dev/null
ok "Código copiado"

# ------------------------------------------------------------ 4. CONFIG USUARIO
log "4/6 Configuración de usuario y skills soberanas"
rsync -rlt --no-links \
  "$SRC/.agents/"            "$USB/04_CONFIG_USUARIO/.agents/" 2>/dev/null
rsync -rlt --no-links \
  "$SRC/.ftl/"               "$USB/04_CONFIG_USUARIO/.ftl/" 2>/dev/null
rsync -rlt --no-links \
  "$SRC/.tardis/"            "$USB/04_CONFIG_USUARIO/.tardis/" 2>/dev/null
rsync -rlt --no-links \
  --exclude='*/node_modules/' --exclude='*/Cache/' \
  "$SRC/.config/opencode/"   "$USB/04_CONFIG_USUARIO/.config_opencode/" 2>/dev/null
rsync -rlt --no-links \
  "$SRC/.config/systemd/user/" "$USB/04_CONFIG_USUARIO/systemd_user/" 2>/dev/null
for f in .bashrc .bash_aliases .profile .tmux.conf .gitconfig .pam_environment \
         .tardis_bin .tardisos_issue .tardisos_issue_net .tardisos_lsb_release \
         .tardisos_os_release .tardisos_profile.sh .tardisos_logo.svg \
         .tardisos_logo_text.svg .claude.json .tardis_ipad_sync_state.json; do
  cp -a "$SRC/$f" "$USB/04_CONFIG_USUARIO/" 2>/dev/null
done
mkdir -p "$USB/04_CONFIG_USUARIO/bin"
cp -a "$SRC/.local/bin/." "$USB/04_CONFIG_USUARIO/bin/" 2>/dev/null
ok "Configuración copiada"

# ------------------------------------------------------------ 5. PROYECTOS
log "5/6 Proyectos satélite TARDIS"
for d in modulos_ftl tardis_visual_engine TARDIS_Portfolio vw-control; do
  [ -d "$SRC/$d" ] || continue
  rsync -rlt --no-links --exclude='__pycache__/' --exclude='.git/' \
        "$SRC/$d/" "$USB/05_PROYECTOS_TARDIS/$d/" 2>/dev/null
done
ok "Proyectos copiados"

# --------------------------------------------------------------- 6. MODELOS
log "6/6 Modelfiles de IA local"
cp -a "$PROJ/Modelfile.kaiju" "$PROJ/Modelfile.mundo-sin-censura" "$USB/06_MODELOS/" 2>/dev/null
cp -a "$PROJ/TARDIS-NEURAL-SPACE-KAIJU-v27.SPEC.md" "$USB/06_MODELOS/" 2>/dev/null
ok "ModelFiles copiados"

echo
df -h "$USB" | tail -1
echo "TAMANO TOTAL DEL KIT: $(du -sh "$USB" | cut -f1)"
