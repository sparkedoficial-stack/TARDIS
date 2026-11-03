#!/usr/bin/env bash
# Snapshot de sistema para reconstrucción de TARDIS / GODWORKS SYSTEM v26.4
set -uo pipefail
BASE="/run/media/timemachine/Hyper jump/GODWORKS_TARDIS_BACKUP_2026-11-03/03_SISTEMA"
mkdir -p "$BASE"/{paquetes,systemd/unidades_usuario,systemd/unidades_sistema,red,hardware,kernel,entornos_python,etc,proyectos}

h() { echo; echo "## $*"; }

# ---------------------------------------------------------------- 1. SISTEMA
{
  echo "GENERADO: $(date -Is)"
  echo "HOSTNAME: $(hostname)"
  echo "USUARIO: $(id)"
  echo "KERNEL: $(uname -a)"
  h "OS RELEASE"; cat /etc/os-release
  h "LSB RELEASE"; lsb_release -a 2>/dev/null
  h "UPTIME"; uptime
} > "$BASE/00_sistema_general.txt"

lscpu > "$BASE/hardware/lscpu.txt" 2>&1
lsblk -o NAME,SIZE,TYPE,FSTYPE,LABEL,UUID,MOUNTPOINT,MODEL,SERIAL > "$BASE/hardware/lsblk.txt" 2>&1
lsblk -J > "$BASE/hardware/lsblk.json" 2>&1
lsusb > "$BASE/hardware/lsusb.txt" 2>&1
lspci -nn > "$BASE/hardware/lspci.txt" 2>&1
free -h > "$BASE/hardware/memoria.txt" 2>&1
df -hT > "$BASE/hardware/discos_df.txt" 2>&1
cat /proc/mounts > "$BASE/hardware/mounts.txt" 2>&1
cp /etc/fstab "$BASE/hardware/fstab.txt" 2>/dev/null
cp /etc/crypttab "$BASE/hardware/crypttab.txt" 2>/dev/null
for f in /sys/class/dmi/id/{sys_vendor,product_name,product_version,board_vendor,board_name,bios_version,bios_date}; do
  echo "$(basename $f): $(cat $f 2>/dev/null)"
done > "$BASE/hardware/dmi.txt" 2>&1
nvidia-smi > "$BASE/hardware/nvidia_smi.txt" 2>&1 || true

# ---------------------------------------------------------------- 2. PAQUETES
dpkg --get-selections > "$BASE/paquetes/dpkg_selections.txt" 2>&1
apt-mark showmanual > "$BASE/paquetes/apt_manual.txt" 2>&1
apt list --installed 2>/dev/null > "$BASE/paquetes/apt_instalados.txt"
snap list > "$BASE/paquetes/snap_list.txt" 2>&1
flatpak list --app --columns=application,version,origin > "$BASE/paquetes/flatpak_list.txt" 2>&1 || true
pip3 list 2>/dev/null > "$BASE/paquetes/pip_sistema.txt"
npm list -g --depth=0 2>/dev/null > "$BASE/paquetes/npm_global.txt"
gem list 2>/dev/null > "$BASE/paquetes/gems.txt" || true
cargo install --list 2>/dev/null > "$BASE/paquetes/cargo.txt" || true

# ------------------------------------------------------------------ 3. KERNEL
{
  echo "## PARAMETROS CMDLINE"; cat /proc/cmdline
  echo; echo "## SYSCTL NO DEFAULT"
  sysctl -a 2>/dev/null | head -400
} > "$BASE/kernel/cmdline_sysctl.txt" 2>&1

# ---------------------------------------------------------------- 4. PYTHON
python3 --version > "$BASE/entornos_python/versiones.txt" 2>&1
echo "VENVS ENCONTRADOS:" >> "$BASE/entornos_python/versiones.txt"
find /home/timemachine -maxdepth 4 -name "pyvenv.cfg" -printf '%h\n' 2>/dev/null >> "$BASE/entornos_python/versiones.txt"
while read -r v; do
  [ -x "$v/bin/pip" ] || continue
  n=$(echo "$v" | tr '/' '_')
  "$v/bin/pip" freeze > "$BASE/entornos_python/requirements${n}.txt" 2>/dev/null
  "$v/bin/python" --version >> "$BASE/entornos_python/versiones.txt" 2>/dev/null
done < <(find /home/timemachine -maxdepth 4 -name "pyvenv.cfg" -printf '%h\n' 2>/dev/null)

# ---------------------------------------------------------------- 5. SYSTEMD
systemctl list-unit-files --no-pager > "$BASE/systemd/unidades_sistema/listado.txt" 2>&1
systemctl list-units --type=service --state=running --no-pager > "$BASE/systemd/unidades_sistema/activos.txt" 2>&1
systemctl --user list-unit-files --no-pager > "$BASE/systemd/unidades_usuario/listado.txt" 2>&1
systemctl --user list-units --type=service --state=running --no-pager > "$BASE/systemd/unidades_usuario/activos.txt" 2>&1
systemctl --user list-timers --all --no-pager > "$BASE/systemd/unidades_usuario/timers.txt" 2>&1
systemctl list-timers --all --no-pager > "$BASE/systemd/unidades_sistema/timers.txt" 2>&1
for u in $(systemctl --user list-unit-files --state=enabled --no-pager --plain 2>/dev/null | awk '{print $1}'); do
  systemctl --user cat "$u" > "$BASE/systemd/unidades_usuario/$u.txt" 2>/dev/null
done
cp -a /home/timemachine/.config/systemd/user "$BASE/systemd/unidades_usuario/archivos_originales" 2>/dev/null
for u in $(systemctl list-unit-files --state=enabled --no-pager --plain 2>/dev/null | awk '{print $1}' | grep -iE 'tardis|godworks|ftl|gia|ollama|imac|sovereign|tailscale'); do
  systemctl cat "$u" > "$BASE/systemd/unidades_sistema/$u.txt" 2>/dev/null
done

# -------------------------------------------------------------------- 6. RED
ip -br addr > "$BASE/red/ip_addr.txt" 2>&1
ip route > "$BASE/red/rutas.txt" 2>&1
nmcli -t dev status > "$BASE/red/nmcli_dev.txt" 2>&1
nmcli -t con show > "$BASE/red/nmcli_conexiones.txt" 2>&1
cat /etc/resolv.conf > "$BASE/red/resolv.conf.txt" 2>&1
cat /etc/hosts > "$BASE/red/hosts.txt" 2>&1
cp -a /etc/netplan "$BASE/red/netplan" 2>/dev/null
cp -a /etc/NetworkManager/system-connections "$BASE/red/nm_conexiones" 2>/dev/null
ss -tulpn 2>/dev/null > "$BASE/red/puertos_escuchando.txt"

# -------------------------------------------------------------------- 7. ETC
tar -C / -czf "$BASE/etc/etc_esencial.tar.gz" \
  etc/default/grub \
  etc/apt/sources.list etc/apt/sources.list.d \
  etc/systemd/system etc/systemd/user \
  etc/udev/rules.d \
  etc/modprobe.d etc/modules-load.d \
  etc/X11 etc/gdm3 etc/environment etc/profile.d \
  etc/security/limits.d \
  etc/plymouth etc/grub.d \
  etc/fstab etc/hostname etc/hosts \
  etc/bluetooth etc/pulse etc/wireplumber \
  etc/logind.conf etc/sysctl.d \
  2>/dev/null || true

# -------------------------------------------------------------- 8. PROYECTOS
{
  echo "## REPOS GIT EN HOME"
  find /home/timemachine -maxdepth 5 -name .git -type d -printf '%h\n' 2>/dev/null | while read -r g; do
    echo "--- $g"
    git -C "$g" remote -v 2>/dev/null
    git -C "$g" log -1 --format='ultimo_commit: %H %ci %s' 2>/dev/null
    git -C "$g" status --porcelain 2>/dev/null | head -5
  done
} > "$BASE/proyectos/repos_git.txt" 2>&1

{
  echo "## BINARIOS EN ~/.local/bin"
  ls -la /home/timemachine/.local/bin 2>/dev/null
  echo; echo "## BINARIOS /usr/local/bin"
  ls -la /usr/local/bin 2>/dev/null
} > "$BASE/proyectos/ejecutables.txt" 2>&1

echo "SNAPSHOT COMPLETO: $(date -Is)"
