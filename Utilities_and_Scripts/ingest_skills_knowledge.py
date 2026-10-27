#!/usr/bin/env python3
"""
scripts/ingest_skills_knowledge.py - Ingesta del Catálogo Soberano de Skills en el RAG Vault
============================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU

Directiva Soberana:
"Todas las herramientas y habilidades con las que tiene acceso AGY, TARDIS, así como FTL
deben tener control y saber de su conocimiento para poder emplearlas en sus sistemas
de forma individual."

Este script inyecta el contenido íntegro de cada SKILL.md sincronizado en
~/.agents/skills dentro de la Bóveda RAG y el Grafo de Conocimiento de TARDIS,
de modo que GIA / KAIJU / el Supervisor puedan recuperar y aplicar cada skill
en lenguaje natural mediante /api/ftl/rag_search o el chat central.

Uso:
    .venv-linux/bin/python3 scripts/ingest_skills_knowledge.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

CANONICAL_DIR = Path.home() / ".agents" / "skills"
CATALOG_FILE = Path.home() / ".tardis" / "skills" / "catalog.json"
MAX_CHARS = 14000


def parse_frontmatter(text: str) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return meta
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip("'\"")
    return meta


def collect_skills() -> List[Dict[str, Any]]:
    skills: List[Dict[str, Any]] = []
    if not CANONICAL_DIR.is_dir():
        return skills
    for entry in sorted(CANONICAL_DIR.iterdir()):
        skill_md = entry / "SKILL.md"
        if not entry.is_dir() or not skill_md.is_file():
            continue
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        meta = parse_frontmatter(text)
        references = [
            p.name for p in (entry / "references").glob("*") if p.is_file()
        ] if (entry / "references").is_dir() else []
        skills.append({
            "name": entry.name,
            "declared_name": meta.get("name", entry.name),
            "description": meta.get("description", ""),
            "version": meta.get("version", ""),
            "content": text,
            "references": references,
        })
    return skills


def build_document(skill: Dict[str, Any]) -> str:
    header = (
        f"Habilidad soberana '{skill['name']}' del ecosistema GODWORKS SYSTEM v26.4, "
        f"compartida por Antigravity (AGY), FTL y TARDIS. "
        f"Descripción oficial: {skill['description']} "
    )
    body = re.sub(r"\n{3,}", "\n\n", skill["content"])[:MAX_CHARS]
    refs = ""
    if skill["references"]:
        refs = " Documentos de referencia incluidos: " + ", ".join(skill["references"]) + "."
    return f"{header}{refs}\n\n{body}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingesta de skills en el RAG Vault de TARDIS")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar el catálogo a ingestar")
    args = parser.parse_args()

    skills = collect_skills()
    if not skills:
        print(f"✗ No se encontraron skills en {CANONICAL_DIR}")
        return 1

    print("=== INGESTA SOBERANA DE SKILLS EN RAG VAULT · TARDIS ===")
    print(f"Fuente canónica: {CANONICAL_DIR} · {len(skills)} habilidades")

    if args.dry_run:
        for skill in skills:
            print(f"  • {skill['name']} ({len(skill['content'])} bytes)")
        return 0

    try:
        from core.rag_vault import get_rag_vault
    except Exception as exc:
        print(f"✗ RAG Vault no disponible: {exc}")
        return 2

    vault = get_rag_vault()
    summary = []
    for skill in skills:
        doc = build_document(skill)
        try:
            res = vault.ingest(
                text=doc,
                source=f"skill_{skill['name']}",
                title=f"Skill Soberana: {skill['name']}",
                term=skill["name"],
            )
        except Exception as exc:
            print(f"  ✗ {skill['name']}: {exc}")
            summary.append({"name": skill["name"], "ok": False, "error": str(exc)})
            continue
        stored = res.get("stored", 0)
        terms = res.get("extracted_terms", 0)
        rels = res.get("extracted_relations", 0)
        print(f"  ✓ {skill['name']}: {stored} fragmentos, {terms} términos, {rels} relaciones")
        summary.append({
            "name": skill["name"],
            "ok": True,
            "stored": stored,
            "terms": terms,
            "relations": rels,
        })

    catalog_path = BASE_DIR / "data" / "skills_rag_ingest.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        json.dumps({"skills": summary, "source": str(CANONICAL_DIR)},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    ok = sum(1 for item in summary if item.get("ok"))
    print(f"\n[ÉXITO] {ok}/{len(skills)} skills ingestadas en la Bóveda RAG de TARDIS.")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
