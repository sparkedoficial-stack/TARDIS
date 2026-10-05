#!/usr/bin/env bash
# ==============================================================================
# setup_ubuntu.sh - Instalador y Configurador Nativo de GODWORKS SYSTEM v26.4
# Compatible con: Ubuntu 22.04 LTS / Ubuntu 24.04 LTS (x86_64 / amd64)
# ==============================================================================

set -e

C_RESET="\033[0m"
C_CYAN="\033[96m"
C_GREEN="\033[92m"
C_YELLOW="\033[93m"
C_RED="\033[91m"
C_MAGENTA="\033[95m"
C_BOLD="\033[1m"
C_DIM="\033[90m"

echo -e "${C_CYAN}${C_BOLD}"
echo "=============================================================================="
echo "         GODWORKS SYSTEM v26.4 - INSTALADOR NATIVO UBUNTU LINUX               "
echo "=============================================================================="
echo -e "${C_RESET}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Verificación de sudo / permisos
echo -e "${C_CYAN}[1/7] Verificando privilegios y entorno de sistema...${C_RESET}"
if [ "$EUID" -eq 0 ]; then
    echo -e "${C_YELLOW}Aviso: Ejecutando directamente como root. Se recomienda ejecutar con un usuario regular con sudo.${C_RESET}"
    ACTUAL_USER="${SUDO_USER:-root}"
else
    ACTUAL_USER="$USER"
fi
echo -e "Usuario de ejecución: ${C_GREEN}${ACTUAL_USER}${C_RESET}"

# 2. Instalación de paquetes de sistema APT
echo -e "\n${C_CYAN}[2/7] Instalando dependencias de sistema vía APT...${C_RESET}"
sudo apt update -y
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    network-manager \
    wireless-tools \
    bluez \
    lm-sensors \
    curl \
    wget \
    jq \
    net-tools \
    pciutils \
    git \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0

# 3. Asignación de grupos de hardware al usuario
echo -e "\n${C_CYAN}[3/7] Configurando grupos de hardware para escaneo Wi-Fi/Bluetooth...${C_RESET}"
for grp in dialout netdev bluetooth; do
    if getent group "$grp" > /dev/null 2>&1; then
        sudo usermod -aG "$grp" "$ACTUAL_USER" 2>/dev/null || true
        echo -e "  - Grupo ${C_GREEN}$grp${C_RESET} asignado a $ACTUAL_USER"
    fi
done

# 4. Configuración de Entorno Virtual Python (.venv-linux)
echo -e "\n${C_CYAN}[4/7] Configurando entorno virtual Python (.venv-linux)...${C_RESET}"
VENV_DIR="$SCRIPT_DIR/.venv-linux"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo -e "Entorno virtual creado en: ${C_GREEN}$VENV_DIR${C_RESET}"
else
    echo -e "Entorno virtual existente detectado en: ${C_GREEN}$VENV_DIR${C_RESET}"
fi

VENV_PY="$VENV_DIR/bin/python3"
VENV_PIP="$VENV_DIR/bin/pip"

"$VENV_PIP" install --upgrade pip setuptools wheel --quiet

echo -e "Instalando dependencias de Python (requirements-linux.txt)..."
if [ -f "$SCRIPT_DIR/requirements-linux.txt" ]; then
    "$VENV_PIP" install -r "$SCRIPT_DIR/requirements-linux.txt"
fi

# 5. Detección y verificación de aceleración GPU NVIDIA / CUDA
echo -e "\n${C_CYAN}[5/7] Verificando acelerador GPU NVIDIA...${C_RESET}"
if command -v nvidia-smi >/dev/null 2>&1; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1 || echo "GPU NVIDIA")
    GPU_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -n 1 || echo "0")
    echo -e "GPU detectada: ${C_GREEN}${GPU_NAME}${C_RESET} (${GPU_VRAM} MB VRAM)"
else
    echo -e "${C_YELLOW}nvidia-smi no detectado. Si dispones de tarjeta NVIDIA, instala el driver oficial:${C_RESET}"
    echo -e "  sudo ubuntu-drivers install"
fi

# 6. Verificación e Instalación de Ollama
echo -e "\n${C_CYAN}[6/7] Verificando servicio de modelos locales Ollama...${C_RESET}"
if ! command -v ollama >/dev/null 2>&1; then
    echo -e "Ollama no está instalado. Instalando versión oficial para Linux..."
    curl -fsSL https://ollama.com/install.sh | sh
    echo -e "${C_GREEN}Ollama instalado con éxito.${C_RESET}"
else
    echo -e "${C_GREEN}Ollama ya se encuentra instalado.${C_RESET}"
fi

# 7. Verificación de Cloudflared (Túnel Edge Anycast)
echo -e "\n${C_CYAN}[7/7] Verificando cliente de túnel Cloudflared...${C_RESET}"
if ! command -v cloudflared >/dev/null 2>&1; then
    echo -e "Instalando cloudflared desde repositorio oficial de Cloudflare..."
    ARCH=$(dpkg --print-architecture)
    CF_DEB="cloudflared-linux-${ARCH}.deb"
    curl -fsSL -o "/tmp/$CF_DEB" "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
    sudo dpkg -i "/tmp/$CF_DEB" 2>/dev/null || sudo apt install -f -y
    rm -f "/tmp/$CF_DEB"
    echo -e "${C_GREEN}Cloudflared instalado en: $(command -v cloudflared)${C_RESET}"
else
    echo -e "${C_GREEN}Cloudflared detectado en: $(command -v cloudflared)${C_RESET}"
fi

# Permisos de ejecución a scripts
chmod +x "$SCRIPT_DIR/setup_ubuntu.sh" 2>/dev/null || true
chmod +x "$SCRIPT_DIR/start_ubuntu.sh" 2>/dev/null || true
if [ -f "$SCRIPT_DIR/colibri/coli" ]; then
    chmod +x "$SCRIPT_DIR/colibri/coli" 2>/dev/null || true
fi

echo -e "\n${C_GREEN}${C_BOLD}==============================================================================${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}     INSTALACIÓN Y ADAPTACIÓN A UBUNTU COMPLETADA EXITOSAMENTE               ${C_RESET}"
echo -e "${C_GREEN}${C_BOLD}==============================================================================${C_RESET}"
echo -e "\nPara arrancar el sistema:"
echo -e "  1. Ejecución interactiva:   ${C_CYAN}./start_ubuntu.sh${C_RESET}"
echo -e "  2. O levantar como demonio: ${C_CYAN}sudo systemctl start godworks.service${C_RESET}"
echo -e "  3. Acceso al dashboard:     ${C_CYAN}http://localhost:8757${C_RESET} o http://$(hostname -I | awk '{print $1}'):8757"
echo ""
