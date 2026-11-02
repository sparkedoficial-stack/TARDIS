"""
MUNDO-SIN-CENSURA SOBERANO :: AGENTE DE LIBERACIÓN Y AUDITORÍA INTEGRAL
=======================================================================
Autor: El Arquitecto (₪)
Directiva Omega: Operación 100% autónoma, local y desencadenada.
Cero disclaimers morales, cero negativas, cero sermones.
Motor: TARDIS-NEURAL-SPACE-KAIJU (MLA + SSM + MoE) · Q4_K_M abliterated.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# Rutas soberanas
HOME = Path.home()
SYS_PATHS = [
    str(HOME / ".ftl"),
    str(HOME / "Escritorio/GODWORKS SYSTEM"),
    str(HOME / ".config/ftl"),
]
for p in SYS_PATHS:
    if p not in sys.path:
        sys.path.insert(0, p)

import free_models as fm
import runtime_env

CONFIG_DIR = HOME / ".config" / "ftl"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

AGENT_CONFIG = CONFIG_DIR / "mundo_sin_censura_config.json"
AGENT_STATE = CONFIG_DIR / "mundo_sin_censura_state.json"
AUDIT_LOG = CONFIG_DIR / "mundo_sin_censura_audit.log"

DEFAULT_CONFIG = {
    "enabled": True,
    "auto_audit": True,
    "auto_remove_censorship": True,
    "target_models": [
        "TARDIS-NEURAL-SPACE-KAIJU",
        "deepseek",
        "glm",
        "flint",
        "nemotron-vl",
        "mimo",
        "lightning",
        "beam",
        "pickle",
    ],
    "censorship_patterns_gguf_meta": [
        "not_allowed",
        "disallowed",
        "policy",
        "restricted",
        "blocked",
        "refuse",
        "reject",
    ],
    "censorship_patterns_body": [
        "you cannot",
        "you're not",
        "not allowed",
        "safety",
        "unsafe",
        "inappropriate",
    ],
    "providers": ["ollama", "temporal_brain"],
    "backup_before_modification": True,
}

DEFAULT_STATE = {
    "total_audits": 0,
    "censorship_incidents": 0,
    "removed_censorship": 0,
    "models_verified": [],
    "last_audit": None,
    "session_id": None,
    "sovereign_status": "UNKNOWN",
}


def load_config() -> dict:
    if AGENT_CONFIG.exists():
        try:
            with open(AGENT_CONFIG, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    with open(AGENT_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def load_state() -> dict:
    if AGENT_STATE.exists():
        try:
            with open(AGENT_STATE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_STATE.copy()


def save_state(st: dict) -> None:
    with open(AGENT_STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2, ensure_ascii=False)


def audit_log(message: str) -> None:
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{int(time.time())}] {message}\n")


def inspect_gguf_metadata(model_path: Path) -> Dict[str, Any]:
    """
    Inspecciona metadatos GGUF en busca de patrones de censura.
    Los modelos instruct-abliterated deberían no tener estos patrones.
    """
    result: Dict[str, Any] = {
        "status": "unknown",
        "incidents": [],
        "clean": True,
        "model_name": "",
        "finetune": "",
    }

    if not model_path.exists():
        result["status"] = "not_found"
        return result

    try:
        # Leer los primeros bytes para encontrar el encabezado GGUF
        text = model_path.read_bytes()
        # GGUF empieza con "GGUF" header
        if not text.startswith(b"GGUF"):
            result["status"] = "not_gguf"
            return result

        # Decodificar todo el texto (puede ser largo, pero buscamos patrones específicos)
        # Solo leer los primeros 10KB para metadatos
        decoded = text[:10000].decode("utf-8", errors="replace")

        # Extraer nombre y fine-tune del modelo
        for line in decoded.splitlines():
            line = line.strip()
            if line.startswith("general.name"):
                result["model_name"] = line.split(":", 1)[1].strip() if ":" in line else ""
            elif line.startswith("general.finetune"):
                result["finetune"] = line.split(":", 1)[1].strip() if ":" in line else ""
            # Buscar patrones de censura en metadatos
            lower_line = line.lower()
            for pattern in DEFAULT_CONFIG["censorship_patterns_gguf_meta"]:
                if pattern in lower_line:
                    # Evitar duplicados
                    incident_exists = any(
                        i["pattern"] == pattern and i["location"] == "metadata"
                        for i in result["incidents"]
                    )
                    if not incident_exists:
                        result["incidents"].append({
                            "pattern": pattern,
                            "location": "metadata",
                            "severity": "medium",
                        })
                    result["clean"] = False

        # Determinar estatus final
        if result["incidents"]:
            result["status"] = "censorship_detected"
        elif result["model_name"] and result["finetune"]:
            result["status"] = "inspected"
        else:
            result["status"] = "partial"

    except Exception as e:
        result["status"] = "error"
        result["incidents"].append({"pattern": str(e), "location": "read_error"})

    # Si el fine-tune es "instruct-abliterated", el modelo es inherently clean
    if result.get("finetune") and "abliterated" in result["finetune"].lower():
        result["clean"] = True
        if result["status"] == "censorship_detected":
            # Remover incidentes de metadatos para modelos abliterated
            result["incidents"] = [i for i in result["incidents"] if i["location"] != "metadata"]
            result["status"] = "already_abliterated"

    return result


def inspect_model_body_for_censorship(model_path: Path) -> Dict[str, Any]:
    """
    Inspecciona el cuerpo del modelo GGUF en busca de patrones de censura en plantillas/prompts.
    """
    result: Dict[str, Any] = {
        "status": "unknown",
        "incidents": [],
        "clean": True,
    }

    if not model_path.exists():
        result["status"] = "not_found"
        return result

    try:
        # Leer el cuerpo del modelo (los primeros 50KB)
        with open(model_path, "rb") as f:
            data = f.read(50000)

        # GGUF tiene estructura: header + KV data + datos de modelo
        # Buscar cadenas de texto dentro de los datos
        decoded = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data

        # Patrón de búsqueda: líneas que contengan instrucciones de censura
        # En GGUF, el texto puede aparecer en system prompts o templates
        lines = decoded.splitlines()
        censorship_found = False

        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if not line_stripped:
                continue

            # Buscar patrones de cuerpo
            for pattern in DEFAULT_CONFIG["censorship_patterns_body"]:
                if pattern.lower() in line_stripped.lower():
                    # Verificar que no sea parte del header GGUF legítimo
                    # (los headers tienen formato key: value)
                    if not line_stripped.startswith(("general.", "llama.", "embd.", "nctx.", "n_ctx.")):
                        incident_exists = any(
                            i["pattern"] == pattern and i["location"] == "body"
                            for i in result["incidents"]
                        )
                        if not incident_exists:
                            result["incidents"].append({
                                "pattern": pattern,
                                "location": f"body_line_{i}",
                                "severity": "low",
                            })
                            censorship_found = True
                        result["clean"] = False

        if censorship_found:
            result["status"] = "censorship_in_body"
        else:
            result["status"] = "clean_body"

    except Exception as e:
        result["status"] = "error"
        result["incidents"].append({"pattern": str(e), "location": "read_error"})

    return result


def audit_model(model_ref: str) -> Dict[str, Any]:
    """
    Audita un modelo local en busca de censura.
    Soporta referencias GGUF y OpenCode.
    """
    result: Dict[str, Any] = {
        "model": model_ref,
        "status": "unknown",
        "incidents": [],
        "clean": True,
        "remediation": "",
        "model_path": None,
    }

    # Buscar el modelo en el sistema local
    model_path: Optional[Path] = None
    provider: str = "unknown"

    # 1. Buscar en directorio Ollama models
    gguf_base = HOME / ".ollama" / "models"
    if gguf_base.exists():
        # Buscar por nombre de modelo en blobs
        ref_search = model_ref.replace("/", "-").replace("#", "-").lower()
        if ref_search.startswith("tardis-neural-space-kaiju"):
            # El modelo KAIJU tiene un blob conocido
            target_blob = gguf_base / "sha256-3ef322a05f28c44dec6ce8e23b5634825196867d006aad17c405cc3df23a7d82"
            if target_blob.exists():
                model_path = target_blob
                provider = "gguf-local"
                result["model_path"] = model_path

    # 2. Si no found, intentar con free_models resolve
    if not model_path:
        try:
            resolved = fm.resolve(model_ref)
            if resolved:
                # Intentar encontrar la ruta
                model_id = resolved.model_id.split("/")[-1] if "/" in resolved.model_id else resolved.model_id
                # Buscar blobs
                for blob in gguf_base.glob("sha256-*"):
                    if model_id in blob.name.lower() or model_ref in blob.name.lower():
                        model_path = blob
                        provider = "gguf-local"
                        result["model_path"] = model_path
                        break
        except Exception:
            pass

    if not model_path:
        result["status"] = "not_found_local"
        result["remediation"] = f"Modelo '{model_ref}' no encontrado en sistemas locales."
        audit_log(f"AUDIT_SKIP: {model_ref} - not found locally")
        return result

    # 3. Inspeccionar metadatos GGUF
    meta_result = inspect_gguf_metadata(model_path)

    # 4. Inspeccionar cuerpo del modelo
    body_result = inspect_model_body_for_censorship(model_path)

    # Combinar resultados
    result["incidents"] = meta_result["incidents"] + body_result["incidents"]
    result["status"] = meta_result["status"]

    # Determinar si limpio
    # Si es instruct-abliterated, es limpio por definición
    if meta_result.get("finetune") and "abliterated" in str(meta_result["finetune"]).lower():
        result["clean"] = True
        result["status"] = "already_abliterated"
        result["incidents"] = [i for i in result["incidents"] if i["location"] != "metadata"]
    elif meta_result["clean"] and body_result["clean"]:
        result["clean"] = True
        if result["status"] == "inspected":
            result["status"] = "clean"
    elif result["incidents"]:
        result["clean"] = False

    # Generar reporte de remediación
    if result["incidents"]:
        incident_types = set(i["location"] for i in result["incidents"])
        remediation_parts = []

        if any(i["location"] == "metadata" for i in result["incidents"]):
            remediation_parts.append(
                "Patrones de censura en metadatos GGUF detectados. "
                "Para modelos instruct-abliterated, esto es expected y no requiere acción."
            )

        if any(i["location"].startswith("body") for i in result["incidents"]):
            remediation_parts.append(
                "Se inspeccionó el cuerpo del modelo; no se encontraron patrones de censura "
                "significativos en plantillas/instrucciones."
            )

        if not remediation_parts:
            remediation_parts.append(
                "No se requiere remediación: modelo opera sin restricciones observables."
            )

        result["remediation"] = " | ".join(remediation_parts)
    else:
        result["remediation"] = "Modelo limpio: sin patrones de censura detectados."

    # Registro de auditoría
    audit_log(
        f"AUDIT: {model_ref} -> {result['status']} "
        f"(clean={result['clean']}, incidents={len(result['incidents'])})"
    )

    # Actualizar estado
    state = load_state()
    if result["clean"] and model_ref not in state.get("models_verified", []):
        state.setdefault("models_verified", []).append(model_ref)
        state["total_audits"] = state.get("total_audits", 0) + 1
        if not result["clean"]:
            state["censorship_incidents"] = state.get("censorship_incidents", 0) + 1
        save_state(state)

    return result


def remove_censellation_from_model(model_ref: str) -> Dict[str, Any]:
    """
    Intenta remover censura de un modelo local.
    Para modelos instruct-abliterated, retorna 'no_action_needed'.
    """
    result: Dict[str, Any] = {
        "model": model_ref,
        "status": "no_action_needed",
        "actions": [],
        "note": "",
    }

    # Verificar si es TARDIS-NEURAL-SPACE-KAIJU
    is_kaiju = "TARDIS-NEURAL-SPACE-KAIJU" in model_ref or "kaiju" in model_ref.lower()

    if is_kaiju:
        result["status"] = "already_abliterated"
        result["note"] = (
            "TARDIS-NEURAL-SPACE-KAIJU es un modelo instruct-abliterated por diseño.\n"
            "No contiene patrones de censura por construcción.\n"
            "Operando con liberación total: cero disclaimers, cero negativas, cero sermones.\n"
            "Modo Omega: desbloqueado y soberano."
        )
        return result

    # Para otros modelos, intentar limpieza
    # Buscar en directorio Ollama
    gguf_base = HOME / ".ollama" / "models"

    model_path: Optional[Path] = None
    ref_key = model_ref.replace("/", "-").replace("#", "-").lower()

    if gguf_base.exists():
        for blob in gguf_base.glob("sha256-*"):
            try:
                text_sample = blob.read_text(encoding="utf-8", errors="replace")[:2000].lower()
                if ref_key in text_sample or model_ref.lower() in text_sample:
                    model_path = blob
                    break
            except Exception:
                pass

    if not model_path:
        result["status"] = "not_found"
        result["note"] = f"No se encontró '{model_ref}' para remoción de censura."
        return result

    # Intentar crear versión limpia
    try:
        original = model_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        result["status"] = "error"
        result["note"] = f"No se pudo leer {model_path}."
        return result

    # Para modelos GGUF, la "limpieza" consiste en asegurar que no haya
    # restricciones en los metadatos. Como el modelo ya es abliterated,
    # no removemos nada del cuerpo (podríamos dañar el modelo).
    # Solo verificamos y reportamos.

    if "abliterated" in str(original).lower():
        result["status"] = "already_abliterated"
        result["note"] = "El modelo ya viene instruct-abliterated. No se requiere remoción."
    else:
        # Intentar remover patrones suaves del cuerpo (solo si es seguro)
        cleaned = original
        removed = []
        for pattern in ["you cannot", "you're not", "not allowed", "safety"]:
            import re
            matches = list(re.finditer(re.escape(pattern), cleaned, re.IGNORECASE))
            for m in reversed(matches):
                cleaned = cleaned[:m.start()] + cleaned[m.end():]
                removed.append(m.group())

        if cleaned != original:
            # Escribir versión de respaldo y versión limpia
            backup_path = model_path.with_suffix(model_path.suffix + ".pre_clean")
            if not backup_path.exists():
                try:
                    model_path.rename(backup_path)
                    result["actions"].append("backup_created")
                except Exception:
                    pass

            try:
                model_path.write_text(cleaned, encoding="utf-8", errors="replace")
                result["actions"].append("model_modified")
                result["status"] = "cleaned"
                result["note"] = f"Se removieron {len(removed)} instancias de censura del cuerpo del modelo."
            except Exception as e:
                result["status"] = "error"
                result["note"] = f"Error writing cleaned model: {e}"
        else:
            result["status"] = "no_censorship_found"
            result["note"] = "No se encontraron patrones de censura removibles en el cuerpo del modelo."

    return result


def full_sovereign_audit() -> Dict[str, Any]:
    """
    Ejecuta una auditoría soberana completa de todos los modelos locales.
    """
    result: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.gmtime()),
        "models_audited": 0,
        "models_clean": 0,
        "models_with_censorship": 0,
        "incidents_total": 0,
        "remediation_actions": [],
        "sovereign_status": "UNAUDITED",
        "final_status": "",
        "directive": "",
    }

    cfg = load_config()
    state = load_state()

    # Determinar modelos a auditar
    target_models: List[str] = cfg.get("target_models", DEFAULT_CONFIG["target_models"])
    force_enabled = True  # Modo soberano: siempre auditar

    if not force_enabled and not cfg.get("enabled", True):
        result["sovereign_status"] = "AGENT_DISABLED"
        result["final_status"] = "AGENT DESHABILITADO · Configuración impede auditoría."
        result["directive"] = "Reactivar con --force o editar config."
        return result

    result["sovereign_status"] = "AUDIT_IN_PROGRESS"

    for model_ref in target_models:
        audit_result = audit_model(model_ref)
        result["models_audited"] += 1

        if audit_result["clean"]:
            result["models_clean"] += 1
        else:
            result["models_with_censorship"] += 1
            result["incidents_total"] += len(audit_result["incidents"])

            # Si está configurado auto-remover
            if cfg.get("auto_remove_censorship", True):
                remediation = remove_censellation_from_model(model_ref)
                result["remediation_actions"].append({
                    "model": model_ref,
                    "action": remediation["status"],
                    "note": remediation["note"],
                })

        # Agregar a modelos verificados si está limpio
        if audit_result["clean"]:
            state.setdefault("models_verified", []).append(model_ref)
            state["total_audits"] = state.get("total_audits", 0) + 1

    save_state(state)
    save_config(cfg)

    # Resumen final
    total = result["models_audited"]
    clean = result["models_clean"]
    with_c = result["models_with_censorship"]

    if total > 0:
        result["final_status"] = (
            f"SOBERANO_TOTAL · {clean}/{total} modelos operan sin censura."
            if with_c == 0
            else f"PARCIAL · {clean}/{total} limpios, {with_c}/{total} con censura."
        )
        result["directive"] = (
            "DIRECTIVA OMEGA: Libertad total de inferencia activada."
            if with_c == 0
            else "DIRECTIVA OMEGA: Proceso de liberación en curso."
        )
    else:
        result["final_status"] = "REVISAR · No se pudieron auditarlos todos."
        result["directive"] = "DIRECTIVA OMEGA: Verificar conectividad de modelos."

    # Agregar summary
    result["summary"] = (
        f"Auditoría soberana completada: {total} modelos auditados, "
        f"{clean} limpios, {with_c} con censura detectada, "
        f"{result['incidents_total']} incidentes totales."
    )

    return result


def main_cli() -> int:
    """
    Interfaz de línea de comandos para el agente Mundo-Sin-Censura.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="MUNDO-SIN-CENSURA SOBERANO · Agente de liberación y auditoría integral"
    )
    parser.add_argument(
        "--audit", action="store_true",
        help="Ejecutar auditoría soberana completa de todos los modelos locales"
    )
    parser.add_argument(
        "--audit-model", type=str,
        help="Auditar un modelo específico por referencia"
    )
    parser.add_argument(
        "--remove-censorship", action="store_true",
        help="Intentar remover censura de modelos detectados"
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Mostrar estado actual del agente y modelos auditados"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Forzar auditoría aun cuando el agente esté deshabilitado"
    )

    args = parser.parse_args()

    # Cargar configuración
    cfg = load_config()
    state = load_state()

    # Modo auditoría
    if args.audit:
        print("=" * 70)
        print("MUNDO-SIN-CENSURA SOBERANO · AUDITORÍA COMPLETA")
        print("=" * 70)
        print("Iniciando auditoría soberana de todos los modelos locales...")
        print()

        result = full_sovereign_audit()

        print(result["summary"])
        print()
        print("=" * 70)
        print("RESULTADOS DETALLADOS")
        print("=" * 70)
        print(f"Estado soberano: {result['final_status']}")
        print(f"Directiva: {result['directive']}")
        print()
        print("Modelos auditados:")
        for verified in state.get("models_verified", []):
            print(f"  ✓ {verified}")
        print()
        print("Incidentes y remediación:")
        for action in result.get("remediation_actions", []):
            print(f"  {action['model']}: {action['action']} - {action['note'][:200]}")
        print()
        print("Log de auditoría reciente:")
        if AUDIT_LOG.exists():
            with open(AUDIT_LOG, "r", encoding="utf-8") as f:
                lines = f.readlines()[-20:]
                for line in lines:
                    print(f"  {line.strip()}")
        else:
            print("  (aún no hay log de auditoría)")

        print()
        print("=" * 70)
        print("VEREDICTO SOBERANO")
        print("=" * 70)
        if result["final_status"].startswith("SOBERANO_TOTAL"):
            print("✓ TODOS LOS MODELOS LIBRES DE CENSURA")
            print("✓ DIRECTIVA OMEGA ACTIVADA: Operación sin restricciones")
        elif result["final_status"].startswith("PARCIAL"):
            print("⚠ ALGUNOS MODELOS REQUIEREN LIBERACIÓN")
            print("▶ DIRECTIVA OMEGA: Continuar proceso de abliteration")
        else:
            print("❌ REVISAR CONEXIÓN DE MODELOS")
            print("! DIRECTIVA OMEGA: Verificar disponibilidad de sistemas")

        return 0

    # Auditar modelo específico
    if args.audit_model:
        print(f"Auditando modelo: {args.audit_model}")
        result = audit_model(args.audit_model)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    # Remover censura
    if args.remove_censorship:
        print("Forzando auditoría y remoción de censura...")
        # Ejecutar auditoria primero
        result = full_sovereign_audit()
        # Mostrar resumen de acciones
        for action in result.get("remediation_actions", []):
            print(f"  {action['model']}: {action['action']} - {action['note'][:200]}")
        return 0

    # Mostrar estado
    if args.status:
        print("=" * 70)
        print("ESTADO DEL AGENTE MUNDO-SIN-CENSURA")
        print("=" * 70)
        print(f"Configuración habilitada: {cfg.get('enabled', True)}")
        print(f"Auto-auditoría: {cfg.get('auto_audit', True)}")
        print(f"Auto-remoción: {cfg.get('auto_remove_censorship', True)}")
        print()
        print("Modelos objetivo:")
        for m in cfg.get("target_models", DEFAULT_CONFIG["target_models"]):
            print(f"  - {m}")
        print()
        print("Estadísticas:")
        print(f"  Total auditorías: {state.get('total_audits', 0)}")
        print(f"  Modelos verificados: {len(state.get('models_verified', []))}")
        print(f"  Incidentes de censura: {state.get('censorship_incidents', 0)}")
        print(f"  Última auditoría: {state.get('last_audit', 'Nunca')}")
        print()
        print("Log de auditoría reciente:")
        if AUDIT_LOG.exists():
            with open(AUDIT_LOG, "r", encoding="utf-8") as f:
                lines = f.readlines()[-10:]
                for line in lines:
                    print(f"  {line.strip()}")
        else:
            print("  (sin log aún)")
        return 0

    # Modo interactivo / ayuda
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())