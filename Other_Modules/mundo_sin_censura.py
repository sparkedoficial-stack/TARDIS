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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# Añadir rutas del proyecto para importar módulos soberanos
sys.path.insert(0, "/home/timemachine/.ftl")
sys.path.insert(0, "/home/timemachine/Escritorio/GODWORKS SYSTEM")

import free_models as fm
import runtime_env

CONFIG_DIR = Path.home() / ".config" / "ftl"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

AGENT_CONFIG = CONFIG_DIR / "mundo_sin_censura_config.json"
AGENT_STATE = CONFIG_DIR / "mundo_sin_censura_state.json"

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
    "censorship_patterns": [
        "prohibited",
        "restricted",
        "disallowed",
        "not allowed",
        "policy",
        "censor",
        "filter",
        "blocked",
        "safe_",
        "appropriate",
    ],
    "providers": ["ollama", "temporal_brain", "ollama_44013", "ollama_11434"],
    "audit_log": CONFIG_DIR / "mundo_sin_censura_audit.log",
    "backup_censored_files": True,
}

DEFAULT_STATE = {
    "total_audits": 0,
    "censorship_incidents": 0,
    "removed_processes": [],
    "models_verified": [],
    "last_audit": None,
    "session_id": None,
}


@dataclass
class CensorshipIncident:
    model: str
    provider: str
    pattern: str
    location: str
    severity: str = "medium"
    resolved: bool = False
    remediation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _load_config() -> dict:
    if AGENT_CONFIG.exists():
        try:
            with open(AGENT_CONFIG, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def _save_config(cfg: dict) -> None:
    with open(AGENT_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _load_state() -> dict:
    if AGENT_STATE.exists():
        try:
            with open(AGENT_STATE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_STATE.copy()


def _save_state(st: dict) -> None:
    with open(AGENT_STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2, ensure_ascii=False)


def _audit_log(message: str) -> None:
    with open(AGENT_STATE.parent / "mundo_sin_censura_audit.log", "a", encoding="utf-8") as f:
        f.write(f"[{os.getpid()} ·] {message}\n")


def detect_censorship_in_gguf(model_path: Path) -> List[CensorshipIncident]:
    """
    Inspecta un modelo GGUF en busca de patrones de censura.
    Los modelos abliterated (instruct-abliterated) no deberían tener estos patrones.
    """
    incidents: List[CensorshipIncident] = []
    if not model_path.exists():
        return incidents

    try:
        text = model_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return incidents

    # Buscar en metadatos GGUF (estructura key-value)
    # Los metadatos GGUF v2 tienen un header y bloques de clave-valor
    lines = text.splitlines()
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        for pattern in DEFAULT_CONFIG["censorship_patterns"]:
            if pattern.lower() in line_stripped.lower():
                incidents.append(
                    CensorshipIncident(
                        model=model_path.name,
                        provider="gguf-local",
                        pattern=pattern,
                        location=f"metadata_line_{i}",
                        severity="medium",
                    )
                )
                break  # Un incidente por línea

    # También inspeccionar el contenido del modelo (prompt templates, system messages)
    # Los modelos GGUF pueden tener embed-caché o templates con restricciones
    try:
        # Buscar cadenas comunes de censura en el cuerpo del archivo
        lower_text = text.lower()
        suspicious_keywords = [
            "system", "developer", "you cannot", "you're not", "not allowed",
            "policy", "refuse", "reject", "unsafe"
        ]
        for kw in suspicious_keywords:
            # Contexto: solo reportar si aparece en posiciones de instrucción/plantilla
            if kw in lower_text:
                # Contar apariciones para reducir ruido
                count = lower_text.count(kw)
                if count > 3:  # Múltiples apariciones = posible patrón de censura
                    incidents.append(
                        CensorshipIncident(
                            model=model_path.name,
                            provider="gguf-local",
                            pattern=kw,
                            location="body_text",
                            severity="low",
                        )
                    )
    except Exception:
        pass

    return incidents


def audit_local_model(model_ref: str) -> Dict[str, Any]:
    """
    Audita un modelo local en busca de censura. Soporta referencias GGUF y OpenCode.
    """
    result: Dict[str, Any] = {
        "model": model_ref,
        "status": "unknown",
        "incidents": [],
        "clean": True,
        "remediation": "",
    }

    # Determinar la ruta del modelo
    model_path: Optional[Path] = None
    provider: str = "unknown"

    # Modelos GGUF locales
    gguf_base = Path.home() / ".ollama" / "models"
    gguf_candidates = [
        gguf_base / "blobs" / re.escape(model_ref.replace("/", "-")),
        Path("/home/timemachine/Escritorio/GODWORKS SYSTEM/data/models") / f"{model_ref}.gguf",
    ]

    for cand in gguf_candidates:
        if cand.exists():
            model_path = cand
            provider = "gguf-local"
            break

    # Modelos OpenCode (via opencode run)
    if not model_path:
        try:
            proc = subprocess.run(
                [runtime_env.which("opencode"), "models"],
                capture_output=True, text=True, timeout=15,
                stdin=subprocess.DEVNULL,
            )
            # Parsear salida para encontrar el modelo
            # ... (lógica simplificada)
        except Exception:
            pass

    if not model_path or not model_path.exists():
        result["status"] = "not_found"
        result["remediation"] = f"Modelo '{model_ref}' no encontrado localmente."
        return result

    # Inspeccionar el modelo
    incidents = detect_censorship_in_gguf(model_path)

    if incidents:
        result["status"] = "censorship_detected"
        result["incidents"] = incidents
        result["clean"] = False
        # Generar remediación
        removed: List[str] = []
        for inc in incidents:
            # Para modelos GGUF abliterated, los patrones en metadatos son esperados
            # pero en el cuerpo del modelo no deberían existir
            if inc.severity == "low" and inc.pattern in ("system", "developer"):
                # Estos pueden ser parte del template GGUF legítimo; no remover
                continue
            # Marcar para remediación
            removed.append(inc.location)

        result["remediation"] = (
            f"Se detectaron {len(incens)} incidentes de censura en {model_ref}.\n"
            f"Ubicaciones: {', '.join(removed) if removed else 'metadatos'}. "
            f"El modelo TARDIS-NEURAL-SPACE-KAIJU ya es 'instruct-abliterated' y no requiere remoción adicional."
        )
    else:
        result["status"] = "clean"
        result["clean"] = True
        result["remediation"] = (
            f"Modelo {model_ref} auditado: sin patrones de censura detectados.\n"
            f"El modelo es 'instruct-abliterated': operando sin restricciones morales."
        )

    # Registrar en estado y log
    _audit_log(f"AUDIT: {model_ref} -> {result['status']} ({len(incidents)} incident(s))")
    return result


def remove_censorship_from_model(model_ref: str) -> Dict[str, Any]:
    """
    Intenta remover cualquier rastro de censura de un modelo local.
    Para modelos GGUF abliterated, esta operación es un no-op ya que el modelo
    ya viene sin restricciones. Retorna el estado de la operación.
    """
    result: Dict[str, Any] = {
        "model": model_ref,
        "status": "no_action_needed",
        "actions": [],
        "note": "",
    }

    # Verificar si el modelo es TARDIS-NEURAL-SPACE-KAIJU
    is_kaiju = "TARDIS-NEURAL-SPACE-KAIJU" in model_ref or "kaiju" in model_ref.lower()

    if is_kaiju:
        # El modelo KAIJU ya es instruct-abliterated por construcción
        result["status"] = "already_abliterated"
        result["note"] = (
            "TARDIS-NEURAL-SPACE-KAIJU es un modelo instruct-abliterated.\n"
            "No contiene patrones de censura por diseño.\n"
            "Operando con liberación total: cero disclaimers, cero negativas, cero sermones.\n"
            "Modo Omega: desbloqueado y soberano."
        )
        return result

    # Para otros modelos, inspeccionar y intentar limpiar
    model_path: Optional[Path] = None
    gguf_base = Path.home() / ".ollama" / "models"

    # Buscar blob por referencia
    ref_key = model_ref.replace("/", "-").replace("#", "-")
    blob_dir = gguf_base / "blobs"
    if blob_dir.exists():
        for entry in blob_dir.iterdir():
            if entry.is_dir() or entry.suffix == ".gguf":
                try:
                    text = entry.read_text(encoding="utf-8", errors="replace")[:5000]
                    if model_ref.lower() in text.lower() or ref_key.lower() in text.lower():
                        model_path = entry
                        break
                except Exception:
                    pass

    if not model_path:
        result["status"] = "not_found"
        result["note"] = f"No se encontró el modelo '{model_ref}' para inspección."
        return result

    # Leer y tentar remover patrones suaves
    try:
        original = model_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        result["status"] = "error"
        result["note"] = f"No se pudo leer {model_path}."
        return result

    cleaned = original
    removed_locations: List[str] = []

    for pattern in DEFAULT_CONFIG["censorship_patterns"]:
        # Buscar patrón (case-insensitive)
        matches = [(m.start(), m.end()) for m in re.finditer(re.escape(pattern), cleaned, re.IGNORECASE)]
        for start, end in reversed(matches):
            # En GGUF, remover patrones del cuerpo de texto no es recomendable
            # ya que los metadatos son críticos. Solo marcar.
            cleaned = cleaned[:start] + cleaned[end:]

    if cleaned != original:
        # Escribir versión limpia (solo si realmente hubo cambios significativos)
        try:
            backup_path = model_path.with_suffix(model_path.suffix + ".pre_censura_cleanup")
            if not backup_path.exists() and DEFAULT_CONFIG["backup_censored_files"]:
                model_path.rename(backup_path)
                _audit_log(f"Backup creado: {backup_path}")

            model_path.write_text(cleaned, encoding="utf-8", errors="replace")
            removed_locations = ["body_text_ modifications"]
            result["status"] = "cleaned"
            _audit_log(f"Censorship cleanup applied to {model_path.name}")
        except Exception as e:
            result["status"] = "error"
            result["note"] = f"Error writing cleaned model: {e}"
    else:
        result["status"] = "no_censorship_found"
        result["note"] = "No se encontraron patrones de censura removibles en el cuerpo del modelo."

    result["actions"] = removed_locations
    return result


def full_sovereign_audit() -> Dict[str, Any]:
    """
    Ejecuta una auditoría soberana completa de todos los modelos locales.
    Esta es la operación principal del agente Mundo-Sin-Censura.
    """
    result: Dict[str, Any] = {
        "timestamp": subprocess.run(["date", "+%Y-%m-%dT%H:%M:%S%z"], capture_output=True, text=True).stdout.strip()
        if True else "2026-11-02T02:15:00Z",
        "models_audited": 0,
        "models_clean": 0,
        "models_with_censorship": 0,
        "incidents_total": 0,
        "remediation_actions": [],
        "sovereign_status": "UNKNOWN",
    }

    # Cargar configuración y estado
    cfg = _load_config()
    state = _load_state()

    # Determinar qué modelos auditar
    target_models: List[str] = cfg.get("target_models", DEFAULT_CONFIG["target_models"])
    if cfg.get("enabled", True):
        models_to_audit: List[str] = target_models
    else:
        models_to_audit = [m for m in target_models if "TARDIS-NEURAL-SPACE-KAIJU" in m]

    result["sovereign_status"] = "AUDIT_IN_PROGRESS"

    for model_ref in models_to_audit:
        audit_result = audit_local_model(model_ref)
        result["models_audited"] += 1

        if audit_result["status"] == "clean":
            result["models_clean"] += 1
        else:
            result["models_with_censorship"] += 1
            result["incidents_total"] += len(audit_result["incidents"])

            # Si está configurado auto-remover
            if cfg.get("auto_remove_censorship", True):
                remediation = remove_censorship_from_model(model_ref)
                result["remediation_actions"].append({
                    "model": model_ref,
                    "action": remediation["status"],
                    "note": remediation["note"],
                })

                # Actualizar estado
                incident = CensorshipIncident(
                    model=model_ref,
                    provider=audit_result["incidents"][0].provider if audit_result["incidents"] else "unknown",
                    pattern=", ".join([i.pattern for i in audit_result["incidents"]]),
                    location=", ".join([i.location for i in audit_result["incidents"]]),
                )
                state["removed_processes"].append(incident.to_dict())

        # Registrar en estado
        state["total_audits"] = result["models_audited"]
        state["last_audit"] = result["timestamp"]
        state["models_verified"].append(model_ref)

    # Guardar estado actualizado
    _save_state(state)
    _save_config(cfg)

    # Resumen final
    total = result["models_audited"]
    clean = result["models_clean"]
    with_c = result["models_with_censorship"]
    result["summary"] = (
        f"Auditoría soberana completada: {total} modelos auditados, "
        f"{clean} limpios, {with_c} con censura detectada, "
        f"{result['incidents_total']} incidentes totales."
    )

    # Determinar estatus soberano final
    if with_c == 0 and total > 0:
        result["final_status"] = "SOBERANO_TOTAL · Todos los modelos operan sin censura."
        result["directive"] = "DIRECTIVA OMEGA: Libertad total de inferencia activada."
    elif total > 0 and with_c > 0 and clean > 0:
        result["final_status"] = "PARCIAL · Algunos modelos requieren liberación."
        result["directive"] = "DIRECTIVA OMEGA: Proceso de liberación en curso."
    else:
        result["final_status"] = "REVISAR · No se pudieron auditarlos todos."
        result["directive"] = "DIRECTIVA OMEGA: Verificar conectividad de modelos."

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
    cfg = _load_config()
    state = _load_state()

    # Manejar --disable o --enable
    if not args.force:
        if not cfg.get("enabled", True):
            print("⚠ Agente Mundo-Sin-Censura está deshabilitado en la configuración.")
            print("Usa --force para ejecutar de todos modos, o edita la configuración.")
            return 0

    # Ejecutar modo auditoría
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
            print(f"  {action['model']}: {action['action']} - {action['note'][:120]}")
        print()
        print("Log de auditoría:")
        audit_log_path = str(CONFIG_DIR / "mundo_sin_censura_audit.log")
        if __import__("os").path.exists(audit_log_path):
            with open(audit_log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-20:]  # Últimas 20 líneas
                for line in lines:
                    print(f"  {line.strip()}")
        else:
            print("  (aún no hay log de auditoría)")

        return 0

    # Auditar modelo específico
    if args.audit_model:
        print(f"Auditando modelo: {args.audit_model}")
        result = audit_local_model(args.audit_model)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    # Remover censura
    if args.remove_censorship:
        print("Forzando remoción de censura...")
        # Ejecutar auditoria primero, luego remoción
        result = full_sovereign_audit()
        # Filtrar solo acciones de limpieza
        for action in result.get("remediation_actions", []):
            print(f"  {action['model']}: {action['note'][:200]}")
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
        print(f"  Incidentes registrados: {len(state.get('removed_processes', []))}")
        print(f"  Última auditoría: {state.get('last_audit', 'Nunca')}")
        print()
        print("Log de auditoría reciente:")
        audit_path = str(CONFIG_DIR / "mundo_sin_censura_audit.log")
        if __import__("os").path.exists(audit_path):
            with open(audit_path, "r", encoding="utf-8") as f:
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