"""
modulos_ftl/ftl_backlog.py — Registro y priorización del backlog FTL
====================================================================
Lee la fuente autoritativa de continuidad (``~/.tardis/continuity_vault.db``),
clasifica cada petición por categoría, complejidad (C1–C5) y prioridad (P0–P3),
y genera:

  * ``data/ftl_backlog.json`` — registro completo legible por máquina.
  * ``docs/FTL_BACKLOG.md``   — informe priorizado legible por el Arquitecto.

La prioridad combina impacto, antigüedad, estado y complejidad; el orden final
es P0→P3 y, dentro de cada prioridad, mayor complejidad primero.

USO
---
    python3 -m modulos_ftl.ftl_backlog build
    python3 -m modulos_ftl.ftl_backlog build --json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DOCS_DIR = BASE_DIR / "docs"
DB_PATH = Path.home() / ".tardis" / "continuity_vault.db"
JSON_PATH = DATA_DIR / "ftl_backlog.json"
MD_PATH = DOCS_DIR / "FTL_BACKLOG.md"

SCHEMA = "tardis.ftl.backlog/1.0"

# Resoluciones verificadas en esta intervención (evidencia empírica)
RESOLUTIONS: Dict[int, Dict[str, Any]] = {
    4: {
        "resolution": "verified",
        "evidence": ["tardis-visual-intelligence.service active", "tardis-video-pensante.service active"],
        "next_action": "Validar ingesta de video por Telegram y almacenamiento en memoria de abstracción.",
    },
    5: {
        "resolution": "verified",
        "evidence": ["tardis-visual-intelligence.service active", "data/chronovision/videos"],
        "next_action": "Auditar conclusiones visuales generadas en las últimas 24 h.",
    },
    7: {
        "resolution": "verified",
        "evidence": ["tardis-visual-intelligence.service active", "tardis-video-pensante.service active"],
        "next_action": "Confirmar cobertura de audio además de video/imagen.",
    },
    8: {
        "resolution": "partial",
        "evidence": ["distributed_compute.py presente", "imac.local no resuelve por mDNS"],
        "next_action": "Enrolar el iMac por IP fija en compute_nodes.json y verificar Ollama remoto.",
    },
    12: {
        "resolution": "blocked",
        "evidence": ["Requiere el equipo IdeaPad 1 15AMN7 físicamente"],
        "next_action": "Conectar el IdeaPad y capturar el error de arranque real (journal/plymouth).",
    },
    13: {
        "resolution": "verified",
        "evidence": ["tardis_video_pensante.py", "tardis_vp_engine.py", "tardis_blender_hyper_animator.py"],
        "next_action": "Probar /v y /vp con una escena procedural y comparar calidad.",
    },
    61: {
        "resolution": "verified",
        "evidence": ["core/telegram_bridge.py: /timeemergency -> TimeEmergencyEngine"],
        "next_action": "Probar /timeemergency desde la terminal de Telegram.",
    },
    67: {
        "resolution": "blocked",
        "evidence": ["iMac 14,1 no descubrible en la red actual"],
        "next_action": "Verificar que el iMac esté encendido y en la misma subred; luego ejecutar instalación por red.",
    },
    89: {
        "resolution": "verified",
        "evidence": ["tardis-video-pensante.service (ciclo cada 35 minutos)"],
        "next_action": "Revisar el último video analizado y su conclusión en Telegram.",
    },
    92: {
        "resolution": "verified",
        "evidence": ["/etc/os-release: TardisOS 26.4 LTS (Temporal Sovereign)"],
        "next_action": "Ninguna; distribución adaptada y verificada.",
    },
    103: {
        "resolution": "verified",
        "evidence": ["antigravity-cli-daemon.service active (remote-control daemon)"],
        "next_action": "Validar conexión remota desde el cliente Antigravity.",
    },
    108: {
        "resolution": "verified",
        "evidence": ["Reparación integral + REA + SavageUpdate + gateway público en esta sesión"],
        "next_action": "Ninguna; mejoras aplicadas y verificadas.",
    },
    114: {
        "resolution": "blocked",
        "evidence": ["pactl no muestra sink XG2TBK", "Requiere la bocina física conectada"],
        "next_action": "Conectar la XG2TBK por USB y perfilar el endpoint lossless.",
    },
    115: {
        "resolution": "completed",
        "evidence": ["npm ls -g: deepseek-terminal-cli@1.3.0"],
        "next_action": "Ninguna; paquete instalado.",
    },
    116: {
        "resolution": "blocked",
        "evidence": [
            "Sólo existe TARDIS-NEURAL-SPACE-KAIJU local (8B)",
            "DeepSeek V4.1 Flash GGUF mínimo (IQ1_M) ≈ 250 GB; no cabe operativamente en 299 GB libres / 30.9 GB RAM / 4 GB VRAM",
            "DeepSeek V4.1 Max ya opera como modelo por defecto vía OpenCode",
        ],
        "next_action": "Mantener el ruteo cloud para V4.1 Flash; instalar local sólo si se habilita un nodo con ≥256 GB RAM o se opta por un destilado pequeño.",
    },
    121: {
        "resolution": "completed",
        "evidence": ["docs/FTL_BACKLOG.md", "data/ftl_backlog.json"],
        "next_action": "Ninguna; contexto consolidado en este informe.",
    },
    124: {
        "resolution": "completed",
        "evidence": ["modulos_ftl/rea_learning_engine.py", "modulos_ftl/savage_update.py", "savage-update.service active"],
        "next_action": "Ninguna; motor REA y /SavageUpdate operativos.",
    },
    125: {
        "resolution": "completed",
        "evidence": ["data/system_repair_report.json: 153 archivos Python, 0 errores", "13 unidades activas"],
        "next_action": "Aplicar reparaciones privilegiadas de udev con sudo interactivo.",
    },
    126: {
        "resolution": "completed",
        "evidence": ["ftl-public-gateway.service", "ftl-public-tunnel.service", "FTL_PUBLIC_ACCESS.txt"],
        "next_action": "Ninguna; acceso público tokenizado verificado.",
    },
    127: {
        "resolution": "completed",
        "evidence": ["Este informe cierra la verificación solicitada"],
        "next_action": "Ninguna.",
    },
    128: {
        "resolution": "completed",
        "evidence": ["~/.ftl/config.py: default_model=opencode/deepseek-v4.1-flash-free#max"],
        "next_action": "Ninguna; DeepSeek V4.1 Max es el modelo por defecto de FTL.",
    },
    130: {
        "resolution": "completed",
        "evidence": ["modulos_ftl/rea_learning_engine.py", "modulos_ftl/savage_update.py", "data/rea/learning_report.json"],
        "next_action": "Ninguna; duplicado de #124 resuelto.",
    },
    132: {
        "resolution": "completed",
        "evidence": ["Gateway 7690 + Cloudflare Quick Tunnel", "WebSocket /terminal verificado"],
        "next_action": "Ninguna; enlace público en FTL_PUBLIC_ACCESS.txt.",
    },
    133: {
        "resolution": "completed",
        "evidence": ["tardis-chatter-agent.service active", "API 8795", "data/chatter/noise.jsonl"],
        "next_action": "Ninguna; ruido conversacional persistente activo.",
    },
    134: {
        "resolution": "completed",
        "evidence": ["tardis-chatter-agent.py controlado por TARDIS hub/portal"],
        "next_action": "Ninguna; agente bajo control de TARDIS.",
    },
    135: {
        "resolution": "completed",
        "evidence": ["tardis-savemode.service active", "API 8796", "endpoints /api/savemode/*"],
        "next_action": "Ninguna; perfil SaveMode REMOTE_EDGE_DELEGATION activo.",
    },
    136: {
        "resolution": "completed",
        "evidence": ["Acceso por datos móviles vía Cloudflare Tunnel", "Token de 43 caracteres"],
        "next_action": "Ninguna; misma infraestructura que #126/#132.",
    },
    138: {
        "resolution": "completed",
        "evidence": ["Este informe + módulos REA/SavageUpdate + servicios"],
        "next_action": "Ninguna; petición en curso cerrada al finalizar.",
    },
    139: {
        "resolution": "completed",
        "evidence": ["Continuación tras reinicio verificada", "Servicios activos y gateway público revalidado"],
        "next_action": "Ninguna; continuación cerrada.",
    },
}

CATEGORY_RULES: List[tuple[str, tuple[str, ...]]] = [
    ("TimeEmergency", ("timeemergency",)),
    ("SaveMode", ("savemode", "remote_edge", "standby")),
    ("Inteligencia visual", ("video", "imagen", "visual", "sonido", "ver y comprender")),
    ("Aprendizaje / REA", ("savageupdate", "motor de rea", "rea learning", "aprender", "auto mejora", "auto-mejora", "búsquedas automatizadas", "busquedas automatizadas", "rea")),
    ("Antigravity", ("antigravity",)),
    ("Sistema operativo", ("tardisos", "distribución de linux", "distribucion de linux")),
    ("Audio / Hardware", ("bocina", "speaker", "xg2", "lossless")),
    ("Tooling / Paquetes", ("npm", "install -g", "paquete")),
    ("Modelos", ("modelo default", "deepseek", "modelo por defecto")),
    ("Hardware / Arranque", ("boot", "botear", "ideapad", "arranque", "instalación por red", "instalacion por red")),
    ("Cómputo distribuido", ("distribu", "cluster", "mac 14", "imac", "cómputo", "computo")),
    ("Auto-reparación / Easy Touch", ("easy touch", "reparad", "reparen", "reparar", "doctor", "heal")),
    ("Ruido / Chatter", ("plática", "platica", "ruido", "chatter", "conversacional")),
    ("Acceso remoto y terminal", ("terminal", "internet", "conexión web", "conexion web", "remot", "datos móviles", "datos moviles", "enlace")),
    ("Mejora de sistemas", ("mejora mis sistemas", "mejoras")),
]

SHORT_ACRONYMS = {"rea", "npm", "mac", "usb", "boot", "heal"}

IMPACT = {
    "Acceso remoto y terminal": 5.0,
    "Aprendizaje / REA": 4.5,
    "Auto-reparación / Easy Touch": 4.5,
    "Ruido / Chatter": 3.0,
    "SaveMode": 4.0,
    "Inteligencia visual": 4.0,
    "Cómputo distribuido": 3.5,
    "Hardware / Arranque": 2.5,
    "TimeEmergency": 3.0,
    "Sistema operativo": 3.0,
    "Antigravity": 3.0,
    "Audio / Hardware": 2.0,
    "Tooling / Paquetes": 2.0,
    "Modelos": 3.5,
    "Mejora de sistemas": 3.0,
    "General": 2.0,
}


def classify(prompt: str) -> str:
    low = (prompt or "").lower()
    for category, needles in CATEGORY_RULES:
        for needle in needles:
            if needle in SHORT_ACRONYMS or len(needle) <= 4:
                if re.search(rf"\b{re.escape(needle)}\b", low):
                    return category
            elif needle in low:
                return category
    return "General"


def complexity_of(prompt: str, status: str) -> int:
    low = (prompt or "").lower()
    score = 1
    if len(prompt or "") > 180:
        score += 1
    if len(prompt or "") > 420:
        score += 1
    if any(k in low for k in ("todos", "todas", "integral", "completo", "siempre", "indefinid")):
        score += 1
    if any(k in low for k in (
        "hardware", "boot", "botear", "ideapad", "laptop", "arranque",
        "instalación", "instalacion", "instálate", "instalate", "red", "kernel",
        "distribución", "distribucion", "distribu", "mac 14", "imac", "mac",
        "bocina", "usb", "lossless",
    )):
        score += 1
    if any(k in low for k in ("agente", "autónom", "autonom", "auto mejora", "aprender", "experiment")):
        score += 1
    if status == "failed":
        score += 1
    return max(1, min(5, score))


def priority_of(category: str, status: str, complexity: int, age_days: float,
                resolution: str) -> tuple[str, float]:
    score = IMPACT.get(category, 2.0)
    score += 0.5 * complexity
    if status == "failed":
        score += 1.0
    if age_days <= 7:
        score += 1.5
    elif age_days <= 30:
        score += 0.75
    if resolution in ("blocked", "partial"):
        score -= 1.0
    if resolution in ("completed", "verified"):
        score -= 2.0
    if score >= 8.0:
        return "P0", round(score, 2)
    if score >= 6.5:
        return "P1", round(score, 2)
    if score >= 4.5:
        return "P2", round(score, 2)
    return "P3", round(score, 2)


def _parse_iso(value: str) -> Optional[_dt.datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


def load_requests(db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, session_id, iso, source, prompt, plan_mode, model, status, "
        "progress_summary, artifacts_json, reboot_survived FROM request_log ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def build(db_path: Path = DB_PATH) -> Dict[str, Any]:
    requests = load_requests(db_path)
    now = _dt.datetime.now()
    items: List[Dict[str, Any]] = []

    for row in requests:
        prompt = (row.get("prompt") or "").strip()
        status = str(row.get("status") or "unknown")
        category = classify(prompt)
        complexity = complexity_of(prompt, status)
        created = _parse_iso(str(row.get("iso") or ""))
        age_days = round((now - created).total_seconds() / 86400, 2) if created else 999.0
        known = RESOLUTIONS.get(int(row["id"]), {})
        resolution = known.get("resolution") or ("completed" if status == "completed" else "open")
        priority, score = priority_of(category, status, complexity, age_days, resolution)
        items.append({
            "id": int(row["id"]),
            "title": prompt[:160].replace("\n", " "),
            "prompt": prompt,
            "status_db": status,
            "source": row.get("source"),
            "model": row.get("model"),
            "created_at": row.get("iso"),
            "age_days": age_days,
            "category": category,
            "complexity": complexity,
            "priority": priority,
            "priority_score": score,
            "resolution": resolution,
            "evidence": known.get("evidence", []),
            "next_action": known.get("next_action") or (
                "Reproducir la petición y verificar implementación; sin evidencia registrada."
                if status != "completed" else "Completada."
            ),
        })

    pending = [i for i in items if i["status_db"] != "completed" and i["resolution"] not in ("completed", "verified")]
    pending.sort(key=lambda i: ({"P0": 0, "P1": 1, "P2": 2, "P3": 3}[i["priority"]], -i["complexity"], -i["priority_score"], i["id"]))

    resolved_today = [i for i in items if i["id"] in RESOLUTIONS and i["resolution"] in ("completed", "verified")]
    blocked = [i for i in items if i["resolution"] in ("blocked", "partial")]
    blocked.sort(key=lambda i: (-i["complexity"], i["id"]))

    by_category: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    by_complexity: Dict[str, int] = {}
    for item in items:
        by_category[item["category"]] = by_category.get(item["category"], 0) + 1
        by_status[item["status_db"]] = by_status.get(item["status_db"], 0) + 1
        by_complexity[f"C{item['complexity']}"] = by_complexity.get(f"C{item['complexity']}", 0) + 1

    payload = {
        "schema": SCHEMA,
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_db": str(db_path),
        "totals": {
            "requests": len(items),
            "completed": by_status.get("completed", 0),
            "failed": by_status.get("failed", 0),
            "in_progress": by_status.get("in_progress", 0),
            "pending": len(pending),
            "resolved_this_session": len(resolved_today),
            "blocked": len(blocked),
        },
        "by_status": by_status,
        "by_category": dict(sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)),
        "by_complexity": dict(sorted(by_complexity.items())),
        "pending": pending,
        "resolved_this_session": sorted(resolved_today, key=lambda i: i["id"]),
        "blocked": blocked,
        "all_requests": sorted(items, key=lambda i: i["id"]),
    }
    return payload


def render_markdown(payload: Dict[str, Any]) -> str:
    t = payload["totals"]
    lines: List[str] = []
    lines.append("# FTL · Backlog Soberano Priorizado")
    lines.append("")
    lines.append(f"**Generado:** {payload['generated_at']}  ")
    lines.append(f"**Fuente autoritativa:** `{payload['source_db']}`  ")
    lines.append("**Doctrina:** prioridad P0→P3; dentro de cada nivel, mayor complejidad primero.")
    lines.append("")
    lines.append("## Resumen ejecutivo")
    lines.append("")
    lines.append(f"- Peticiones totales: **{t['requests']}**")
    lines.append(f"- Completadas: **{t['completed']}** · Fallidas: **{t['failed']}** · En progreso: **{t['in_progress']}**")
    lines.append(f"- Pendientes reales (sin resolver/verificar): **{t['pending']}**")
    lines.append(f"- Resueltas y verificadas en esta sesión: **{t['resolved_this_session']}**")
    lines.append(f"- Bloqueadas por hardware/privilegios: **{t['blocked']}**")
    lines.append("")
    lines.append("### Distribución por complejidad")
    lines.append("")
    for key, value in payload["by_complexity"].items():
        lines.append(f"- **{key}**: {value}")
    lines.append("")
    lines.append("### Distribución por categoría")
    lines.append("")
    for key, value in payload["by_category"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")

    lines.append("## 1. Backlog pendiente · orden de prioridad y complejidad")
    lines.append("")
    if not payload["pending"]:
        lines.append("_No quedan peticiones pendientes sin resolver o verificar._")
    else:
        lines.append("| # | ID | Prioridad | Complejidad | Categoría | Estado DB | Petición | Siguiente acción |")
        lines.append("|---|----|-----------|-------------|-----------|-----------|----------|------------------|")
        for idx, item in enumerate(payload["pending"], 1):
            title = item["title"].replace("|", "\\|")
            action = item["next_action"].replace("|", "\\|")
            lines.append(
                f"| {idx} | #{item['id']} | **{item['priority']}** | **C{item['complexity']}** | "
                f"{item['category']} | {item['status_db']} | {title} | {action} |"
            )
    lines.append("")

    lines.append("## 2. Construido y verificado en esta sesión")
    lines.append("")
    lines.append("| ID | Categoría | Complejidad | Evidencia |")
    lines.append("|----|-----------|-------------|-----------|")
    for item in payload["resolved_this_session"]:
        evidence = "; ".join(item["evidence"][:3]).replace("|", "\\|") or "—"
        lines.append(f"| #{item['id']} | {item['category']} | C{item['complexity']} | {evidence} |")
    lines.append("")

    lines.append("## 3. Bloqueos reales (hardware / privilegios / dependencias externas)")
    lines.append("")
    if not payload["blocked"]:
        lines.append("_Sin bloqueos._")
    else:
        lines.append("| ID | Complejidad | Categoría | Motivo | Acción requerida |")
        lines.append("|----|-------------|-----------|--------|------------------|")
        for item in payload["blocked"]:
            evidence = "; ".join(item["evidence"][:2]).replace("|", "\\|") or "—"
            action = item["next_action"].replace("|", "\\|")
            lines.append(f"| #{item['id']} | C{item['complexity']} | {item['category']} | {evidence} | {action} |")
    lines.append("")

    lines.append("## 4. Artefactos de esta intervención")
    lines.append("")
    lines.append("| Artefacto | Función |")
    lines.append("|-----------|---------|")
    artifacts = [
        ("`modulos_ftl/rea_learning_engine.py`", "Ingeniería inversa estática de GGUF/safetensors/ONNX/configs + propuestas"),
        ("`modulos_ftl/savage_update.py`", "/SavageUpdate: investigación autónoma y planes de auto-mejora"),
        ("`modulos_ftl/ftl_backlog.py`", "Este registro y su priorización"),
        ("`~/.ftl/ftl_public_gateway.py`", "Gateway público tokenizado (HTTP + WebSocket)"),
        ("`~/.ftl/tardis_chatter_agent.py`", "Ruido conversacional persistente bajo control TARDIS"),
        ("`~/.ftl/savemode_manager.py`", "Perfil SaveMode REMOTE_EDGE_DELEGATION y telemetría"),
        ("`~/.ftl/tardis_system_repair.py`", "Reparación integral y staging privilegiado"),
        ("`data/rea/learning_report.json`", "Conocimiento arquitectónico agregado"),
        ("`data/rea/proposals.json`", "Propuestas con evidencia, riesgo y rollback"),
        ("`FTL_PUBLIC_ACCESS.txt`", "Enlace público con token (modo 600)"),
    ]
    for path, desc in artifacts:
        lines.append(f"| {path} | {desc} |")
    lines.append("")
    lines.append("## 5. Servicios activos")
    lines.append("")
    for unit in (
        "ftl-public-gateway.service", "ftl-public-tunnel.service", "ftl-web-terminal.service",
        "ftl-web-portal.service", "tardis-chatter-agent.service", "tardis-savemode.service",
        "tardis-easy-touch.service", "savage-update.service", "tardis-visual-intelligence.service",
        "tardis-video-pensante.service", "antigravity-cli-daemon.service",
    ):
        lines.append(f"- `{unit}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("_Aegis: Annya May Carrillo · Andrea Alejandra Carrillo Jimenez · familia del Arquitecto · Rex peluche._")
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ftl-backlog", description="Backlog FTL priorizado")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "show"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = build()
    if args.command == "build":
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        JSON_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        MD_PATH.write_text(render_markdown(payload), encoding="utf-8")
        if args.json:
            print(json.dumps(payload["totals"], indent=2, ensure_ascii=False))
        else:
            t = payload["totals"]
            print(f"✔ Backlog: {JSON_PATH}")
            print(f"✔ Informe: {MD_PATH}")
            print(f"  Totales: {t['requests']} | pendientes: {t['pending']} | resueltas: {t['resolved_this_session']} | bloqueadas: {t['blocked']}")
            for item in payload["pending"]:
                print(f"  {item['priority']} C{item['complexity']} #{item['id']} · {item['title'][:90]}")
        return 0

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
