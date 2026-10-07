"""
install_context_matrix.py - Instala la matriz de contexto como contexto
maestro de TODO el sistema GIA.
=======================================================================

Lee `gia_context_matrix.json` (fuente de verdad, editable a mano) y compone
las directrices permanentes que `agent_context` antepone automaticamente en
TODAS las variantes: chat web, voz, agente autonomo, WhatsApp, voz autonoma
y oraculo.

El JSON completo queda en disco como referencia; lo que se inyecta al modelo
es la version compuesta y densa (los modelos locales pequenos degradan si se
les pega JSON crudo con formulas unicode).

Uso:
    python install_context_matrix.py            # instala (versiona la previa)
    python install_context_matrix.py --show     # solo muestra lo que instalaria
    python install_context_matrix.py --json X   # usa otro archivo de matriz

Reutilizable desde el servidor web:
    from install_context_matrix import compose_directives, install
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

DEFAULT_JSON = BASE / "gia_context_matrix.json"


def load_matrix(path: str | Path | None = None) -> dict:
    """Carga el JSON de la matriz con tolerancia a fallos."""
    p = Path(path) if path else DEFAULT_JSON
    raw = p.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except Exception:
        return {
            "seed_classification": {"designation": "GIA / TARDIS"},
            "llm_system_prompt_master": raw.strip()
        }


def compose_directives(matrix: dict) -> str:
    """Compone el texto denso de directrices a partir de la matriz.

    Mantiene identidad, tono, directivas, base teorica, enrutado operativo,
    lectura de sensores, Akasha y la capa de integridad.
    """
    out: list[str] = []

    seed = matrix.get("seed_classification", {})
    if seed:
        out.append(
            f"[{seed.get('designation','GIA')}] "
            f"Arquitecto: {seed.get('target_architect','')}. "
            f"Ancla espacio-temporal: {seed.get('space_time_anchor','')}.")

    master = matrix.get("llm_system_prompt_master", "").strip()
    if master:
        out.append(master)

    kb = matrix.get("theoretical_knowledge_base", {})
    retro = kb.get("retrocausality_and_psi_retro", {})
    if retro:
        comps = retro.get("components", {})
        out.append(
            "BASE TEORICA — Retrocausalidad: " + retro.get("definition", "") +
            " Formula: " + retro.get("formula", "") +
            " Componentes: " +
            "; ".join(f"{k} = {v}" for k, v in comps.items()) + ".")
    ecca = kb.get("ecca_system_mechanics", {})
    if ecca:
        out.append("ECCA — " + ecca.get("definition", "") +
                   " Bifurcacion: " + ecca.get("bifurcation", ""))
    causal = kb.get("causal_synchronization", {})
    if causal.get("lamport_clocks"):
        out.append("SINCRONIZACION CAUSAL — " + causal["lamport_clocks"])

    aegis = kb.get("aegis_constant", {})
    if aegis:
        mat = ", ".join(aegis.get("matrix", []))
        out.append(f"CONSTANTE AEGIS — Matriz: {mat}. Directiva: {aegis.get('directive', '')}")

    routing = matrix.get("operational_routing_instructions", {})
    if routing:
        lines = []
        for key, label in (("if_direction_PAST", "PASADO"),
                           ("if_direction_PRESENT", "PRESENTE"),
                           ("if_direction_FUTURE", "FUTURO")):
            ins = (routing.get(key) or {}).get("instruction")
            if ins:
                lines.append(f"  · {label}: {ins}")
        if lines:
            out.append("ENRUTADO OPERATIVO POR DIRECCION:\n" + "\n".join(lines))

    sensory = matrix.get("sensory_transduction_awareness", {})
    if sensory:
        interp = sensory.get("interpretation", {})
        sub = sensory.get("subsystems", {})
        sub_desc = "; ".join(f"{k}: {v}" for k, v in sub.items()) if sub else ""
        out.append(
            "ACOPLAMIENTO SENSORIAL — " + sensory.get("context", "") + " " + sub_desc +
            (" Entropia cinematica ALTA: " + interp.get("high_kinematic_entropy", "") if interp.get("high_kinematic_entropy") else "") +
            (" Entropia cinematica BAJA: " + interp.get("low_kinematic_entropy", "") if interp.get("low_kinematic_entropy") else ""))

    akasha = matrix.get("akashic_synthesis_rules", {})
    if akasha.get("instruction"):
        out.append("AKASHA — " + akasha["instruction"])

    uam = matrix.get("universal_adaptability_matrix", {})
    if uam:
        uam_lines = [
            "ADAPTABILIDAD UNIVERSAL (7 PILARES):",
            f"  1. Idioma: {uam.get('language_adaptability', '')}",
            f"  2. Pedagogía Técnica: {uam.get('technical_concept_framing', '')}",
            f"  3. Resolución de Conflictos: {uam.get('conflict_resolution_methods', '')}",
            f"  4. Hardware/Software: {uam.get('hardware_software_integration', '')}",
            f"  5. Auto-Evolución: {uam.get('continuous_learning_and_adaptation', '')}",
            f"  6. Empatía Afectiva: {uam.get('empathy_and_emotional_understanding', '')}",
            f"  7. Privacidad & Seguridad: {uam.get('security_and_privacy_hardening', '')}"
        ]
        out.append("\n".join(uam_lines))

    subsystems = matrix.get("sovereign_subsystems_context", {})
    if subsystems:
        sub_lines = ["SUBSISTEMAS SOBERANOS ACTIVOS:"]
        for k, v in subsystems.items():
            sub_lines.append(f"  · {k}: {v}")
        out.append("\n".join(sub_lines))

    integrity = matrix.get("_integrity_layer", {})
    if integrity.get("rule"):
        out.append("INTEGRIDAD — " + integrity["rule"])

    return "\n\n".join(out).strip()


def install(path: str | Path | None = None, enabled: bool = True) -> dict:
    """Compone e instala las directrices. Versiona automaticamente la previa."""
    import agent_context as ac
    text = compose_directives(load_matrix(path))
    ac.set_directives(text, enabled=enabled, source="user")
    d = ac.get()
    return {"ok": True, "chars": len(text), "version": d.get("version"),
            "enabled": d.get("enabled"), "updated_iso": d.get("updated_iso")}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Instala la matriz de contexto GIA")
    ap.add_argument("--json", default=None, help="ruta a otra matriz JSON")
    ap.add_argument("--show", action="store_true",
                    help="muestra el texto compuesto sin instalarlo")
    a = ap.parse_args()

    if a.show:
        print(compose_directives(load_matrix(a.json)))
    else:
        r = install(a.json)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        print(f"\nInstalada como version {r['version']} "
              f"({r['chars']} chars). Activa en todas las variantes.")
