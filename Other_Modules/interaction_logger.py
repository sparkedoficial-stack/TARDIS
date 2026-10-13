"""
core/interaction_logger.py - GODWORKS SYSTEM · TARDIS Sistema de Vigilancia y Control Temporal
=============================================================================================
Registro Cronológico e Historial Fotográfico de Interacciones Locales.

Guarda de manera permanente:
- Día de la semana (Lunes, Martes, etc.) y fecha formateada (YYYY-MM-DD).
- Hora exacta de la interacción (HH:MM:SS) y timestamp UNIX.
- Tipo de interacción (presencia_visual, chat_conversacion, bautismo_identidad, captura_manual).
- Individuo detectado/asociado (Nombre, ID, Rol, Proximidad, Emoción).
- Foto del sistema / cámara en disco local (formato JPEG).
- Generación y actualización continua de 'galeria_local.html' para visualización directa en local.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("godworks.interaction_logger")

DAYS_ES = {
    0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves",
    4: "Viernes", 5: "Sábado", 6: "Domingo"
}

MONTHS_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}

# Rutas de almacenamiento en vw-control
VAULT_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
INTERACTIONS_DIR = VAULT_DIR / "interactions"
PHOTOS_DIR = INTERACTIONS_DIR / "photos"
LOG_FILE = INTERACTIONS_DIR / "interactions_history.json"
GALLERY_HTML_FILE = INTERACTIONS_DIR / "galeria_local.html"


class InteractionLogger:
    """Gestor unificado de historial y fotografías de interacciones."""

    _instance: Optional["InteractionLogger"] = None
    _lock = threading.Lock()

    def __init__(self, base_dir: Optional[Path] = None):
        self.interactions_dir = base_dir or INTERACTIONS_DIR
        self.photos_dir = self.interactions_dir / "photos"
        self.log_file = self.interactions_dir / "interactions_history.json"
        self.gallery_html = self.interactions_dir / "galeria_local.html"

        self.photos_dir.mkdir(parents=True, exist_ok=True)
        self._db_lock = threading.Lock()
        self._interactions: List[Dict[str, Any]] = []
        self._last_presence_log_ts: float = 0.0
        self._last_presence_id: str = ""

        self._load_log()

    @classmethod
    def get_instance(cls, base_dir: Optional[Path] = None) -> "InteractionLogger":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(base_dir=base_dir)
            return cls._instance

    def _load_log(self) -> None:
        """Carga el historial existente desde el archivo JSON."""
        with self._db_lock:
            if self.log_file.exists():
                try:
                    raw = self.log_file.read_text(encoding="utf-8")
                    data = json.loads(raw)
                    if isinstance(data, list):
                        self._interactions = data
                    elif isinstance(data, dict):
                        self._interactions = data.get("interactions", [])
                except Exception as e:
                    logger.warning(f"Aviso leyendo historial de interacciones: {e}")
                    self._interactions = []
            else:
                self._interactions = []

    def _save_log_unlocked(self) -> None:
        """Guarda el historial en disco y re-genera la galería HTML local."""
        try:
            payload = {
                "version": "26.4",
                "updated_ts": time.time(),
                "total_records": len(self._interactions),
                "interactions": self._interactions
            }
            self.log_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error guardando historial de interacciones: {e}")

        # Generar o actualizar galeria_local.html
        try:
            self._generate_html_gallery_unlocked()
        except Exception as e_html:
            logger.warning(f"Aviso generando galeria local HTML: {e_html}")

    def record_interaction(
        self,
        interaction_type: str,
        title: str,
        details: str = "",
        individual: Optional[Dict[str, Any]] = None,
        photo_b64: Optional[str] = None,
        photo_bytes: Optional[bytes] = None,
        capture_system_screenshot: bool = False,
        system_photo_b64: Optional[str] = None,
        extra_meta: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Registra una interacción con día, hora y fotografía.
        """
        now = time.time()
        local_t = time.localtime(now)

        day_name = DAYS_ES.get(local_t.tm_wday, "Desconocido")
        date_str = f"{local_t.tm_year:04d}-{local_t.tm_mon:02d}-{local_t.tm_mday:02d}"
        time_str = f"{local_t.tm_hour:02d}:{local_t.tm_min:02d}:{local_t.tm_sec:02d}"
        human_readable = f"{day_name}, {local_t.tm_mday} de {MONTHS_ES.get(local_t.tm_mon, '')} de {local_t.tm_year} a las {time_str}"
        iso_str = time.strftime("%Y-%m-%d %H:%M:%S", local_t)

        interact_id = f"interact_{int(now * 1000)}"
        photo_filename = f"{interact_id}.jpg"
        photo_dest = self.photos_dir / photo_filename

        has_photo = False
        thumb_b64_to_store = ""

        # 1. Guardar foto primaria (cámara o miniatura del individuo)
        if photo_bytes:
            try:
                photo_dest.write_bytes(photo_bytes)
                has_photo = True
            except Exception as e:
                logger.warning(f"Error escribiendo foto en disco: {e}")
        elif photo_b64 and photo_b64.startswith("data:"):
            try:
                _, b64data = photo_b64.split(",", 1)
                img_bytes = base64.b64decode(b64data)
                photo_dest.write_bytes(img_bytes)
                has_photo = True
                thumb_b64_to_store = photo_b64[:3000] # Mantener muestra rápida
            except Exception as e:
                logger.warning(f"Error decodificando foto base64: {e}")

        # 2. Si no hay foto de cámara o se solicita captura de pantalla del sistema
        sys_photo_filename = ""
        if capture_system_screenshot or not has_photo:
            try:
                from core.os_controller import get_os_controller
                raw_scr, scr_data_uri = get_os_controller().capture_screenshot(format="jpeg", quality=75, max_width=1024)
                if not has_photo:
                    # Usar captura de pantalla como foto principal
                    photo_dest.write_bytes(raw_scr)
                    has_photo = True
                    thumb_b64_to_store = scr_data_uri
                else:
                    # Guardar como foto adicional de pantalla
                    sys_photo_filename = f"{interact_id}_sys.jpg"
                    (self.photos_dir / sys_photo_filename).write_bytes(raw_scr)
            except Exception as e_scr:
                logger.warning(f"Aviso capturando foto de pantalla del sistema: {e_scr}")

        # Datos del individuo
        indiv = individual or {}
        indiv_id = indiv.get("id") or "desconocido"
        indiv_name = indiv.get("name") or "Usuario del Sistema"
        indiv_role = indiv.get("role") or "Operador"
        proximity = indiv.get("proximity") or "Frente al terminal"
        emotion = indiv.get("emotion") or indiv.get("primary") or "neutral"

        record = {
            "id": interact_id,
            "timestamp": now,
            "day_name": day_name,
            "date": date_str,
            "time": time_str,
            "human_readable": human_readable,
            "iso_datetime": iso_str,
            "type": interaction_type,
            "title": title,
            "details": details,
            "individual_id": indiv_id,
            "individual_name": indiv_name,
            "role": indiv_role,
            "proximity": proximity,
            "emotion": emotion,
            "photo_filename": photo_filename if has_photo else "",
            "photo_path": str(photo_dest) if has_photo else "",
            "photo_url": f"/api/interactions/photos/{photo_filename}" if has_photo else "",
            "system_photo_filename": sys_photo_filename,
            "system_photo_url": f"/api/interactions/photos/{sys_photo_filename}" if sys_photo_filename else "",
            "thumbnail_b64": thumb_b64_to_store,
            "extra": extra_meta or {}
        }

        with self._db_lock:
            # Insertar al principio (más reciente primero)
            self._interactions.insert(0, record)
            # Mantener hasta los últimos 500 registros para control de disco
            if len(self._interactions) > 500:
                self._interactions = self._interactions[:500]
            self._save_log_unlocked()

        return record

    def list_interactions(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Retorna el listado de interacciones ordenadas de más reciente a más antigua."""
        with self._db_lock:
            return self._interactions[offset:offset + limit]

    def get_interaction(self, interaction_id: str) -> Optional[Dict[str, Any]]:
        """Retorna los datos de una interacción específica."""
        with self._db_lock:
            for item in self._interactions:
                if item.get("id") == interaction_id:
                    return dict(item)
            return None

    def delete_interaction(self, interaction_id: str) -> bool:
        """Elimina un registro y su archivo de imagen asociado."""
        with self._db_lock:
            target_idx = None
            photo_file = None
            sys_file = None
            for idx, item in enumerate(self._interactions):
                if item.get("id") == interaction_id:
                    target_idx = idx
                    photo_file = item.get("photo_filename")
                    sys_file = item.get("system_photo_filename")
                    break

            if target_idx is not None:
                self._interactions.pop(target_idx)
                self._save_log_unlocked()
                # Borrar archivo físico
                if photo_file:
                    try:
                        p = self.photos_dir / photo_file
                        if p.exists(): p.unlink()
                    except Exception: pass
                if sys_file:
                    try:
                        p = self.photos_dir / sys_file
                        if p.exists(): p.unlink()
                    except Exception: pass
                return True
            return False

    def open_local_folder(self) -> Dict[str, Any]:
        """Abre la carpeta local de fotos en el explorador de archivos del sistema operativo."""
        folder = str(self.photos_dir.resolve())
        try:
            if sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "folder": folder, "message": f"Carpeta abierta en explorador local: {folder}"}
        except Exception as e:
            return {"ok": False, "folder": folder, "error": str(e)}

    def open_local_gallery_html(self) -> Dict[str, Any]:
        """Abre la galería HTML en el navegador local predeterminado."""
        gal = str(self.gallery_html.resolve())
        try:
            if sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", gal], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform == "win32":
                os.startfile(gal)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", gal], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "gallery_path": gal}
        except Exception as e:
            return {"ok": False, "gallery_path": gal, "error": str(e)}

    def _generate_html_gallery_unlocked(self) -> None:
        """Crea o actualiza el archivo HTML autónomo para ver fotos en local."""
        cards_html = []
        for it in self._interactions[:120]:
            photo_name = it.get("photo_filename") or ""
            photo_rel = f"photos/{photo_name}" if photo_name else ""
            indiv_name = it.get("individual_name", "Usuario")
            indiv_role = it.get("role", "Operador")
            day_str = it.get("day_name", "")
            date_str = it.get("date", "")
            time_str = it.get("time", "")
            itype = it.get("type", "interacción").replace("_", " ").title()
            title = it.get("title", "")
            details = it.get("details", "")

            img_tag = f'<a href="{photo_rel}" target="_blank"><img src="{photo_rel}" alt="{title}" class="card-img" onerror="this.style.display=\'none\'"></a>' if photo_rel else '<div class="no-img">Sin imagen</div>'

            cards_html.append(f"""
            <div class="card">
                <div class="img-container">{img_tag}</div>
                <div class="card-body">
                    <div class="badge-row">
                        <span class="badge day-badge">📅 {day_str} {date_str}</span>
                        <span class="badge time-badge">⏰ {time_str}</span>
                        <span class="badge type-badge">{itype}</span>
                    </div>
                    <h3 class="card-title">{title}</h3>
                    <div class="indiv-info">
                        <strong>👤 {indiv_name}</strong> &middot; <span class="role-text">{indiv_role}</span>
                    </div>
                    {f'<p class="details">{details}</p>' if details else ''}
                    <div class="file-link">
                        <small>📁 Archivo: <code>{photo_name}</code></small>
                    </div>
                </div>
            </div>
            """)

        cards_str = "\n".join(cards_html) if cards_html else '<p style="text-align:center; color:#94a3b8;">No hay interacciones registradas aún.</p>'

        html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>TARDIS - Galería Local de Interacciones & Fotos</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root {{
            --bg: #070d18;
            --surface: #0e1726;
            --border: #1e293b;
            --teal: #00d4c8;
            --gold: #ffd700;
            --text: #f1f5f9;
            --text-dim: #94a3b8;
        }}
        body {{
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace, sans-serif;
            margin: 0;
            padding: 20px;
        }}
        header {{
            max-width: 1200px;
            margin: 0 auto 24px auto;
            border-bottom: 1px solid var(--border);
            padding-bottom: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }}
        h1 {{
            margin: 0;
            font-size: 20px;
            color: var(--teal);
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .stats {{
            font-size: 13px;
            color: var(--gold);
            font-family: monospace;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 18px;
            max-width: 1200px;
            margin: 0 auto;
        }}
        .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 4px 16px rgba(0,0,0,0.4);
            display: flex;
            flex-direction: column;
            transition: transform 0.2s, border-color 0.2s;
        }}
        .card:hover {{
            transform: translateY(-2px);
            border-color: var(--teal);
        }}
        .img-container {{
            width: 100%;
            height: 200px;
            background: #000;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }}
        .card-img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            cursor: pointer;
            transition: opacity 0.2s;
        }}
        .card-img:hover {{ opacity: 0.9; }}
        .no-img {{
            color: var(--text-dim);
            font-size: 12px;
            font-style: italic;
        }}
        .card-body {{
            padding: 14px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            flex: 1;
        }}
        .badge-row {{
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }}
        .badge {{
            font-size: 10.5px;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 600;
            font-family: monospace;
        }}
        .day-badge {{ background: rgba(0, 212, 200, 0.15); color: var(--teal); border: 1px solid rgba(0, 212, 200, 0.3); }}
        .time-badge {{ background: rgba(255, 215, 0, 0.15); color: var(--gold); border: 1px solid rgba(255, 215, 0, 0.3); }}
        .type-badge {{ background: rgba(255, 255, 255, 0.08); color: var(--text-dim); }}
        .card-title {{
            margin: 4px 0 0 0;
            font-size: 14px;
            color: #fff;
        }}
        .indiv-info {{
            font-size: 12px;
            color: var(--text);
        }}
        .role-text {{ color: var(--text-dim); }}
        .details {{
            font-size: 11.5px;
            color: var(--text-dim);
            line-height: 1.4;
            margin: 4px 0;
        }}
        .file-link {{
            margin-top: auto;
            padding-top: 6px;
            border-top: 1px solid rgba(255,255,255,0.05);
            font-size: 10px;
            color: var(--text-dim);
        }}
        code {{
            background: rgba(0,0,0,0.3);
            padding: 2px 4px;
            border-radius: 3px;
            color: var(--teal);
        }}
    </style>
</head>
<body>
    <header>
        <div>
            <h1>📸 Registro e Historial de Interacciones & Fotos</h1>
            <div style="font-size:12px; color:var(--text-dim); margin-top:3px;">
                TARDIS &middot; Sistema de Vigilancia y Control Temporal &middot; Visualizador Local Autónomo
            </div>
        </div>
        <div class="stats">
            Registros: {len(self._interactions)} &middot; Última sincronización: {time.strftime('%H:%M:%S', time.localtime())}
        </div>
    </header>

    <div class="grid">
        {cards_str}
    </div>
</body>
</html>
"""
        self.gallery_html.write_text(html_content, encoding="utf-8")


_INTERACTION_LOGGER: Optional[InteractionLogger] = None

def get_interaction_logger() -> InteractionLogger:
    """Retorna la instancia singleton de InteractionLogger."""
    global _INTERACTION_LOGGER
    if _INTERACTION_LOGGER is None:
        _INTERACTION_LOGGER = InteractionLogger.get_instance()
    return _INTERACTION_LOGGER
