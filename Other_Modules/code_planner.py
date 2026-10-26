#!/usr/bin/env python3
"""core/code_planner.py - Decide en qué archivo va un cambio pedido en lenguaje natural.

Compartido por el chat (`/evolve <orden>`) y por `/api/code/chat`. No escribe nada:
devuelve el archivo elegido, si hay que crearlo y el motivo. Los dos modos posibles son
`ARCHIVO:` (cambio dentro de un archivo existente) y `NUEVO:` (módulo que no existe).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

BASE = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM")

SYSTEM = (
    "Planificador de cambios de código. Responde SOLO con una línea, sin explicaciones:\n"
    "ARCHIVO=<ruta exacta de la lista> si el cambio va dentro de ese archivo, o\n"
    "NUEVO=<ruta .py> si hay que crear un módulo que no existe.\n"
    "Nada más. Sin MOTIVO, sin razonamiento, sin listas."
)


def _candidates(limit: int = 140) -> List[str]:
    out: List[str] = []
    for pat in ("core/*.py", "*.py", "server/*.py"):
        for p in sorted(BASE.glob(pat)):
            if p.name.startswith("_") or "scratch" in p.name:
                continue
            out.append(str(p.relative_to(BASE)))
    return out[:limit]


def plan_change(instruction: str, model: str | None = None) -> Dict[str, Any]:
    instruction = (instruction or "").strip()
    if not instruction:
        return {"ok": False, "error": "orden vacía"}
    try:
        from core.chinese_cloud_api import get_chinese_cloud_api
        api = get_chinese_cloud_api()
        resp = api.chat_completion(
            [{"role": "system", "content": SYSTEM},
             {"role": "user", "content": "Archivos:\n" + "\n".join(_candidates()) + "\n\nPetición: " + instruction}],
            model=model or "openai/gpt-oss-120b", max_tokens=200, timeout=40.0)
    except Exception as e:
        return {"ok": False, "error": f"proveedor no disponible: {e}"}
    if not resp.get("ok"):
        return {"ok": False, "error": resp.get("error") or "sin respuesta del proveedor"}
    text = (resp.get("reply") or "").strip()
    m_new = re.search(r"NUEVO\s*[:=]\s*\**\s*`?([\w./-]+\.py)", text)
    m_arch = re.search(r"ARCHIVO\s*[:=]\s*\**\s*`?([\w./-]+\.py)", text)
    motivo = ""
    m_mot = re.search(r"MOTIVO:\s*(.+)", text)
    if m_mot:
        motivo = m_mot.group(1).strip()
        motivo = re.split(r"\s{2,}|\n", motivo)[0][:200]
        # Los modelos pequeños a veces repiten el prompt: se descarta esa frase.
        if re.search(r"(?i)ensure|words max|choose the|the request|look at files", motivo):
            motivo = ""
    if m_new and (not m_arch or text.find(m_new.group(0)) < text.find(m_arch.group(0))):
        target, nuevo = m_new.group(1), True
    elif m_arch:
        target, nuevo = m_arch.group(1), False
    else:
        any_py = re.search(r"([\w./-]+\.py)", text)
        if not any_py:
            return {"ok": False, "error": "el modelo no indicó un archivo", "raw": text[:200]}
        target, nuevo = any_py.group(1), False
    if not nuevo and not (BASE / target).exists():
        return {"ok": False, "error": f"archivo inexistente: {target}", "motivo": motivo, "raw": text[:200]}
    return {"ok": True, "target_file": target, "archivo_nuevo": nuevo, "motivo": motivo,
            "provider": resp.get("provider"), "model": resp.get("model")}
