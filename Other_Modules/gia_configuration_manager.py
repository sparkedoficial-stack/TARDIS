import json
import os
import sys
import datetime
from pathlib import Path

# Obtener directorio base para configuración
try:
    from core.config import get_settings
    SETTINGS = get_settings()
    CONFIG_DIR = SETTINGS.appdata_dir
except ImportError:
    CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"

CONFIG_FILE = CONFIG_DIR / "gia_agent_config.json"
AUDIT_LOG = CONFIG_DIR / "agent_audit.log"

def log_audit(action, detail, verdict="ALLOW"):
    """Función simple de auditoría para registrar cambios de configuración."""
    try:
        from agent_safety import audit
        audit(action, detail, verdict=verdict)
    except ImportError:
        timestamp = datetime.datetime.now().isoformat()
        try:
            with open(AUDIT_LOG, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] [{verdict}] [{action}] {detail}\n")
        except Exception:
            pass

def create_configuration(config_data: dict):
    """Crea o sobrescribe la configuración del agente."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=4)
    log_audit("config_create", f"Configuration created with {len(config_data)} keys", verdict="ALLOW")
    print(f"Configuración creada en {CONFIG_FILE}")

def update_configuration(config_data: dict):
    """Actualiza la configuración existente, o la crea si no existe."""
    current = load_configuration() or {}
    if not isinstance(current, dict):
        current = {}
    current.update(config_data)
    create_configuration(current)
    log_audit("config_update", f"Configuration updated with keys: {list(config_data.keys())}", verdict="ALLOW")
    print("Configuración actualizada.")

def delete_configuration():
    """Elimina el archivo de configuración del agente."""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
        log_audit("config_delete", "Configuration file deleted", verdict="ALLOW")
        print("Configuración eliminada.")
    else:
        print("La configuración no existe.")

def load_configuration():
    """Carga la configuración actualizada del agente."""
    if not CONFIG_FILE.exists():
        print("La configuración no existe. Cargando por defecto.")
        log_audit("config_load", "Default configuration loaded (not found)", verdict="ALLOW")
        try:
            from core.config import get_settings
            return get_settings().to_dict()
        except ImportError:
            return {}
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            log_audit("config_load", "Configuration loaded successfully", verdict="ALLOW")
            return data
    except Exception as e:
        print(f"Error cargando configuración: {e}")
        log_audit("config_error", f"Error loading config: {e}", verdict="BLOCK")
        return {}

def main():
    if len(sys.argv) < 2:
        print("Uso: python -m gia_configuration_manager load_configuration | create | update | delete")
        sys.exit(1)
        
    cmd = sys.argv[1]
    if cmd == "load_configuration":
        config = load_configuration()
        print(json.dumps(config, indent=2))
    elif cmd == "create":
        create_configuration({"agent_version": "26.4", "status": "active", "updated_at": datetime.datetime.now().isoformat()})
    elif cmd == "update":
        update_configuration({"status": "updated", "last_check": datetime.datetime.now().isoformat()})
    elif cmd == "delete":
        delete_configuration()
    else:
        print(f"Comando desconocido: {cmd}")

if __name__ == "__main__":
    main()
