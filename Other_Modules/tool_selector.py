"""
tool_selector.py - Subconjunto dinamico de tools para modelos pequenos.
=======================================================================

Los modelos de 7b pierden precision cuando se les ofrecen 35 tools a la vez.
Este selector, de forma DETERMINISTA (sin llamada extra al modelo, coste 0),
elige solo las tools relevantes para la tarea del turno: categorias que
coinciden con las palabras clave de la tarea + un nucleo siempre presente.

Si ninguna categoria coincide, devuelve el set completo (recall > precision:
mejor ofrecer de mas que dejar al agente sin la tool que necesita).

API:
    select_tool_names(task, recent_text="") -> set[str]
    subset_schema(full_schema, task, recent_text="") -> list[dict]
"""
from __future__ import annotations

# Tools que SIEMPRE se ofrecen (nucleo esencial para operar con seguridad y autosuficiencia)
CORE = {"run_shell", "read_file", "write_file", "list_dir", "finish", "speak"}

# Auto-inclusión de herramientas sintetizadas dinámicamente en segundo plano
try:
    from pathlib import Path
    _dyn_dir = Path(__file__).resolve().parent / "dynamic_tools"
    if _dyn_dir.is_dir():
        for _f in _dyn_dir.glob("*.py"):
            if not _f.name.startswith("__"):
                CORE.add(_f.stem)
except Exception:
    pass

# Agrupacion de tools por dominio
CATEGORIES = {
    "files": {"read_file", "write_file", "list_dir", "search_files", "grep_files"},
    "shell_os": {"run_shell", "install_software", "uninstall_software",
                 "free_compute", "reboot_pc"},
    "gui": {"screenshot", "gui_click", "gui_type", "gui_key", "list_windows",
            "focus_window", "type_into_window", "open_app"},
    "screen": {"read_screen", "read_window", "screenshot", "vlm_inspect_screen",
               "vlm_inspect_image", "vlm_watch_condition"},
    "web": {"web_search", "web_fetch", "search_browsers"},
    "sensors": {"list_cameras", "capture_photo", "list_microphones",
                "record_audio", "read_sensors", "read_em_spectrum",
                "rf_detect_presence", "rf_spatial_density"},
    "voice": {"speak"},
    "ios": {"ios_devices", "ios_info", "ios_apps", "ios_install", "ios_uninstall",
            "ios_screenshot", "ios_media"},
    "self_code": {"self_rewrite_file", "evolve_own_code", "list_code_backups",
                  "restore_code_backup", "request_self_improvement",
                  "spawn_subagent", "consolidate_subconscious", "improve_context"},
    "tardis_subsystems": {"tardis_control_os", "tardis_manage_network", "tardis_audit_traffic",
                          "tardis_query_vault", "tardis_trigger_sensor", "tardis_causal_divergence",
                          "tardis_manage_packages", "tardis_system_self_repair", "tardis_notify_bridge"},
}

# Palabras clave (en espanol e ingles) que activan cada categoria
KEYWORDS = {
    "files": ("archivo", "archivos", "carpeta", "carpetas", "directorio", "fichero",
              "leer", "escribe", "escribir", "guardar", "file", "folder", "path",
              "ruta", "documento", "txt", "json", "csv", "buscar archivo", "grep",
              "contenido de", "crea un archivo", "renombra", "mueve", "listar"),
    "shell_os": ("comando", "powershell", "cmd", "ejecuta", "correr", "proceso",
                 "servicio", "instala", "instalar", "desinstala", "winget",
                 "reinicia", "reiniciar", "apaga", "shutdown", "libera", "memoria",
                 "cpu", "ram", "cierra programa", "matar proceso", "kill"),
    "gui": ("clic", "click", "raton", "mouse", "teclado", "teclea", "escribe en",
            "ventana", "boton", "abre app", "abrir", "pantalla",
            "interfaz", "barra", "chat", "navega", "pega", "arrastra"),
    "screen": ("pantalla", "leer pantalla", "que hay en pantalla", "ocr",
               "captura de pantalla", "screenshot", "que dice", "leer ventana",
               "ver la pantalla", "mira la pantalla", "en pantalla", "vision",
               "vlm", "mira", "ojos", "inspecciona imagen", "espera que termine", "render"),
    "web": ("internet", "busca en", "google", "web", "noticia", "precio",
            "actual", "reciente", "descarga de", "url", "http", "pagina",
            "navegador", "historial", "marcadores", "en linea", "online"),
    "sensors": ("camara", "foto", "fotografia", "microfono", "audio", "graba",
                "grabar", "sensor", "temperatura", "bateria", "webcam", "sonido",
                "escucha", "captura foto", "espectro", "radar", "presencia",
                "wifi", "rf", "electromagnetico", "perturbacion"),
    "voice": ("habla", "di ", "dime en voz", "voz alta", "bocina", "pronuncia",
              "reproduce", "responde por voz"),
    "ios": ("iphone", "ios", "apple", "ipa", "celular", "movil usb", "dispositivo usb"),
    "self_code": ("mejora tu codigo", "reescribe tu", "modifica tu", "tu propio",
                  "auto-mejora", "evoluciona", "mejorate", "tu codigo", "backup",
                  "restaura", "self", "improvement", "mejora del sistema",
                  "subagente", "enjambre", "subconsciente", "consolida", "sueño", "swarm",
                  "contexto agentico", "directrices"),
    "tardis_subsystems": ("tardis", "subsistema", "herramienta", "herramientas",
                          "red", "wifi", "hotspot", "timemachine", "trafico",
                          "intruso", "boveda", "vault", "radar", "geon", "causal",
                          "ecca", "reparar", "auto-reparacion", "diagnostico",
                          "centinela", "bridge", "antigravity", "bloquea",
                          "desbloquea", "volumen"),
}


def select_tool_names(task: str, recent_text: str = "") -> set:
    """Devuelve el subconjunto de nombres de tools relevantes para la tarea."""
    text = (task + " " + recent_text).lower()
    selected = set(CORE)
    matched_any = False
    for cat, kws in KEYWORDS.items():
        if any(k in text for k in kws):
            selected |= CATEGORIES.get(cat, set())
            matched_any = True
    if not matched_any:
        # Sin senal clara: no arriesgar recall, se decide arriba con full set.
        return set()   # senal para "usa todo"
    return selected


def subset_schema(full_schema: list, task: str, recent_text: str = "",
                  max_tools: int = 16) -> list:
    """Filtra el TOOLS_SCHEMA completo al subconjunto relevante.
    Si no hay match claro o el subconjunto seria demasiado pequeno, devuelve
    el schema completo (recall primero)."""
    names = select_tool_names(task, recent_text)
    if not names:
        return full_schema      # sin senal -> todo
    subset = [t for t in full_schema
              if t.get("function", {}).get("name") in names]
    # Garantiza que el nucleo CORE este siempre presente si existe en el schema
    have = {t["function"]["name"] for t in subset}
    for must in CORE:
        if must not in have:
            for t in full_schema:
                if t.get("function", {}).get("name") == must:
                    subset.append(t)
                    have.add(must)
                    break
    # Si por alguna razon quedo muy corto, mejor dar el set completo
    if len(subset) < 4:
        return full_schema
    return subset[:max_tools]


def stats(full_schema: list, task: str) -> dict:
    sub = subset_schema(full_schema, task)
    return {"task": task[:60], "full": len(full_schema), "subset": len(sub),
            "tools": [t["function"]["name"] for t in sub]}


if __name__ == "__main__":
    import json
    import sys
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
    from gia_agent import TOOLS_SCHEMA
    tests = [
        "Crea un archivo readme.txt en el escritorio con la fecha de hoy",
        "Busca en internet la ultima version de Python y dime cual es",
        "Toma una foto con la camara y guardala",
        "Lee lo que hay en la pantalla y resumelo",
        "Cierra los programas mas pesados para liberar memoria",
        "Habla y salu­dame por las bocinas",
        "Mejora tu propio codigo del archivo voice.py",
        "Charlemos un rato sobre arquitectura",
    ]
    for t in tests:
        s = stats(TOOLS_SCHEMA, t)
        print(f"[{s['subset']}/{s['full']}] {s['task']}")
        print("   ", ", ".join(s["tools"]))
