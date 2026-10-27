"""
core/tardis_skill_registry.py - Registro Soberano de Habilidades de TARDIS
==========================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU

Expone el catálogo canónico de skills sincronizadas por `sovereign-sync`
(~/.agents/skills) al cerebro de TARDIS, para que GIA, KAIJU y el Supervisor
puedan consultarlas, leerlas y despacharlas igual que AGY o FTL.

Fuente primaria:  ~/.tardis/skills/catalog.json  (generado por sovereign-sync)
Fallback:         escaneo directo de ~/.tardis/skills y ~/.agents/skills

Uso:
    from core.tardis_skill_registry import get_skill_registry
    reg = get_skill_registry()
    reg.catalog()            # dict listo para /api/skills
    reg.get_skill("rea")     # contenido completo + metadata
    reg.sync()               # fuerza sovereign-sync y recarga
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("TARDIS.SkillRegistry")

HOME_DIR = Path.home()
CANONICAL_DIR = HOME_DIR / ".agents" / "skills"
MIRROR_DIR = HOME_DIR / ".tardis" / "skills"
CATALOG_FILE = MIRROR_DIR / "catalog.json"
SYNC_BIN = HOME_DIR / ".local" / "bin" / "sovereign-sync"
MAX_INLINE_CHARS = 60000


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _read_frontmatter(text: str) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return meta
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("'\"")
    return meta


class TardisSkillRegistry:
    """Catálogo de habilidades compartido por AGY, FTL y TARDIS."""

    _instance: Optional["TardisSkillRegistry"] = None

    def __init__(self) -> None:
        self._catalog: Optional[Dict[str, Any]] = None
        self._catalog_mtime: float = 0.0

    # ------------------------------------------------------------------
    # Descubrimiento
    # ------------------------------------------------------------------
    def _scan(self, root: Path) -> List[Dict[str, Any]]:
        skills: List[Dict[str, Any]] = []
        if not root.is_dir():
            return skills
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file():
                continue
            try:
                text = skill_md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta = _read_frontmatter(text)
            files = [str(p.relative_to(entry)) for p in entry.rglob("*") if p.is_file()]
            skills.append({
                "name": entry.name,
                "declared_name": meta.get("name", entry.name),
                "description": meta.get("description", ""),
                "version": meta.get("version", ""),
                "digest": _sha256(skill_md),
                "files": files,
                "path": str(skill_md),
            })
        return skills

    def _load_catalog(self) -> Dict[str, Any]:
        try:
            mtime = CATALOG_FILE.stat().st_mtime
        except OSError:
            mtime = 0.0
        if self._catalog is not None and mtime == self._catalog_mtime:
            return self._catalog
        if CATALOG_FILE.is_file():
            try:
                data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("skills"):
                    self._catalog = data
                    self._catalog_mtime = mtime
                    return data
            except (OSError, ValueError):
                pass
        skills = self._scan(MIRROR_DIR) or self._scan(CANONICAL_DIR)
        self._catalog = {
            "ok": True,
            "generated_at": None,
            "profile": "UNRESTRICTED_APEX",
            "canonical_dir": str(CANONICAL_DIR),
            "total": len(skills),
            "skills": skills,
            "degraded": True,
        }
        return self._catalog

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def catalog(self) -> Dict[str, Any]:
        data = dict(self._load_catalog())
        skills = data.get("skills", [])
        mirrors: Dict[str, Dict[str, Any]] = {}
        for name in ("antigravity-cli", "antigravity", "claude", "codex", "orca", "tardis", "ftl"):
            mirrors[name] = {"resolved": 0, "expected": len(skills)}
        targets = {
            "antigravity_cli": HOME_DIR / ".gemini" / "antigravity-cli" / "skills",
            "antigravity_desktop": HOME_DIR / ".antigravity" / "skills",
            "claude": HOME_DIR / ".claude" / "skills",
            "codex": HOME_DIR / ".codex" / "skills",
            "orca": HOME_DIR / ".config" / "orca" / "skills",
            "tardis": MIRROR_DIR,
            "ftl": HOME_DIR / ".ftl" / "skills",
        }
        mirror_status = {}
        for key, root in targets.items():
            present = sum(1 for s in skills if (root / s["name"] / "SKILL.md").is_file())
            mirror_status[key] = {
                "path": str(root),
                "present": present,
                "expected": len(skills),
                "ok": present == len(skills) and len(skills) > 0,
            }
        data["ok"] = True
        data["mirrors"] = mirror_status
        data["all_mirrors_ok"] = all(m["ok"] for m in mirror_status.values())
        data["canonical_available"] = CANONICAL_DIR.is_dir()
        data["sync_bin"] = str(SYNC_BIN) if SYNC_BIN.is_file() else None
        return data

    def get_skill(self, name: str) -> Dict[str, Any]:
        name = (name or "").strip().strip("/")
        if not name or "/" in name or name.startswith("."):
            return {"ok": False, "error": "nombre de skill inválido"}
        for root in (MIRROR_DIR, CANONICAL_DIR):
            skill_md = root / name / "SKILL.md"
            if skill_md.is_file():
                try:
                    content = skill_md.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    return {"ok": False, "error": str(exc)}
                meta = _read_frontmatter(content)
                truncated = len(content) > MAX_INLINE_CHARS
                return {
                    "ok": True,
                    "name": name,
                    "declared_name": meta.get("name", name),
                    "description": meta.get("description", ""),
                    "version": meta.get("version", ""),
                    "path": str(skill_md),
                    "bytes": len(content.encode("utf-8")),
                    "truncated": truncated,
                    "content": content[:MAX_INLINE_CHARS],
                    "files": [
                        str(p.relative_to(skill_md.parent))
                        for p in skill_md.parent.rglob("*")
                        if p.is_file()
                    ],
                }
        return {"ok": False, "error": f"skill '{name}' no encontrada"}

    def sync(self) -> Dict[str, Any]:
        if not SYNC_BIN.is_file():
            return {"ok": False, "error": "sovereign-sync no instalado"}
        try:
            proc = subprocess.run(
                [str(SYNC_BIN), "sync", "--quiet"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": str(exc)}
        self._catalog = None
        self._catalog_mtime = 0.0
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stderr": proc.stderr.strip()[-500:],
            "catalog": self.catalog(),
        }


_registry: Optional[TardisSkillRegistry] = None


def get_skill_registry() -> TardisSkillRegistry:
    global _registry
    if _registry is None:
        _registry = TardisSkillRegistry()
    return _registry


if __name__ == "__main__":
    reg = get_skill_registry()
    print(json.dumps(reg.catalog(), indent=2, ensure_ascii=False))
