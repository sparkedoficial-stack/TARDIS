"""
self_modify.py - Auto-reescritura de codigo con red de seguridad.
==================================================================

Permite al agente reescribir su PROPIO codigo para mejorar. Cada reescritura:
  1. Respalda el archivo original a  _selfmod_backups/<archivo>.<timestamp>.bak
  2. Escribe el contenido nuevo.
  3. VALIDA sintaxis (ast.parse para .py). Si el nuevo codigo esta roto,
     REVIERTE automaticamente al respaldo y reporta el error.
  4. Registra todo en el audit log.

Esto hace la auto-modificacion REAL pero sin que un error del modelo deje
el sistema inservible: un rewrite malo se descarta solo.

API:
    rewrite_file(path, new_content, reason) -> dict
    propose_and_apply(path, instruction, model) -> dict   (usa el LLM)
    list_backups(path) -> [..]
    restore_backup(backup_path) -> dict
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

import httpx

BASE = Path(__file__).resolve().parent
BACKUP_DIR = BASE / "_selfmod_backups"
BACKUP_DIR.mkdir(exist_ok=True)
OLLAMA = "http://REDACTED_IP:11434"

try:
    import agent_safety as _safety
    def _audit(a, d, v="ALLOW"):
        _safety.audit(a, d, verdict=v)
except Exception:
    def _audit(a, d, v="ALLOW"):
        pass


def _validate(path: Path, content: str) -> tuple[bool, str]:
    """Valida sintaxis segun extension. Solo .py se parsea; otros pasan."""
    if path.suffix == ".py":
        try:
            ast.parse(content)
            return True, ""
        except SyntaxError as e:
            return False, f"SyntaxError linea {e.lineno}: {e.msg}"
    if path.suffix == ".json":
        try:
            json.loads(content)
            return True, ""
        except Exception as e:
            return False, f"JSON invalido: {e}"
    return True, ""


def _backup(path: Path) -> Path | None:
    if not path.is_file():
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = BACKUP_DIR / f"{path.name}.{ts}.bak"
    shutil.copy2(path, dst)
    return dst


def rewrite_file(path: str, new_content: str, reason: str = "") -> dict:
    """Reescribe un archivo con respaldo + validacion + rollback automatico."""
    p = Path(path)
    if not p.is_absolute():
        p = BASE / p
    # Solo permitir reescribir dentro del proyecto (no tocar SO por accidente)
    try:
        p.resolve().relative_to(BASE.resolve())
    except ValueError:
        return {"ok": False, "error": f"fuera del proyecto: {p} "
                "(self_modify solo reescribe su propio codigo)"}

    ok, err = _validate(p, new_content)
    if not ok:
        _audit("self_rewrite", f"{p.name}: RECHAZADO ({err})", v="BLOCK")
        return {"ok": False, "error": f"codigo nuevo invalido, no se aplico: {err}"}

    backup = _backup(p)
    try:
        p.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"no se pudo escribir: {e}"}

    # Re-validar lo escrito en disco
    ok2, err2 = _validate(p, p.read_text(encoding="utf-8"))
    if not ok2:
        if backup:
            shutil.copy2(backup, p)   # rollback
        _audit("self_rewrite", f"{p.name}: ROLLBACK ({err2})", v="BLOCK")
        return {"ok": False, "error": f"validacion post-escritura fallo, revertido: {err2}"}

    _audit("self_rewrite", f"{p.name}: {reason[:80]}")
    return {"ok": True, "file": str(p), "backup": str(backup) if backup else None,
            "bytes": len(new_content), "reason": reason,
            "note": "aplicado y validado; respaldo disponible para revertir."}


def propose_and_apply(path: str, instruction: str,
                      model: str | None = None,
                      verify_tests: bool = True) -> dict:
    """Pide al LLM (con API offload prioritario o local) el archivo COMPLETO reescrito y lo aplica de forma segura."""
    if not model:
        model = os.environ.get("GIA_MODEL", "huihui_ai/llama3.1-8b-instruct-abliterated")
    p = Path(path)
    if not p.is_absolute():
        p = BASE / p
    if not p.is_file():
        return {"ok": False, "error": f"no existe: {p}"}

    # Intentar orquestador autónomo con API offload (Groq / Cloud) y verificación con tests
    try:
        from core.autonomous_coder import get_autonomous_coder
        coder = get_autonomous_coder()
        evo_res = coder.evolve_code(
            str(p),
            instruction,
            verify_tests=verify_tests,
            model_override=model if model != "qwen2.5-coder:7b" else None,
        )
        if evo_res.status == "APPLIED":
            _audit("self_rewrite", f"{p.name}: {instruction[:80]} (via {evo_res.model_used})")
            return {
                "ok": True,
                "file": str(p),
                "backup": evo_res.backup_path,
                "model": evo_res.model_used,
                "elapsed_s": evo_res.elapsed_seconds,
                "reason": instruction,
                "tests_passed": evo_res.tests_passed,
                "note": "aplicado, validado sintacticamente y verificado con tests.",
            }
        elif evo_res.status in ("ROLLED_BACK_TESTS", "ROLLED_BACK_SYNTAX"):
            return {
                "ok": False,
                "error": f"Evolucion cancelada ({evo_res.status}): {evo_res.error}",
                "backup": evo_res.backup_path,
                "test_output": evo_res.test_output,
            }
    except Exception as e_coder:
        _audit("self_rewrite_warn", f"AutonomousCoder fallo ({e_coder}), intentando fallback directo", v="WARN")

    # Fallback legacy si AutonomousCoder no pudo ejecutarse
    original = p.read_text(encoding="utf-8")

    prompt = (
        f"Eres un ingeniero. Reescribe el archivo COMPLETO aplicando este cambio:\n"
        f"CAMBIO: {instruction}\n\n"
        f"REGLAS: devuelve SOLO el codigo completo del archivo, sin explicacion, "
        f"sin ```. Manten todo lo que funciona; cambia solo lo necesario.\n\n"
        f"ARCHIVO ACTUAL ({p.name}):\n{original}"
    )
    try:
        r = httpx.post(f"{OLLAMA}/api/generate", json={
            "model": model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.2, "num_ctx": 16384},
            "keep_alive": "30m",
        }, timeout=900.0)
        r.raise_for_status()
        new_code = r.json().get("response", "")
    except Exception as e:
        return {"ok": False, "error": f"LLM fallo: {e}"}

    # Limpiar fences si el modelo los puso pese a la instruccion
    new_code = new_code.strip()
    if new_code.startswith("```"):
        new_code = new_code.split("\n", 1)[-1]
        if new_code.rstrip().endswith("```"):
            new_code = new_code.rsplit("```", 1)[0]
    new_code = new_code.strip() + "\n"

    if len(new_code) < 0.35 * len(original):
        return {"ok": False, "error": "el modelo devolvio demasiado poco "
                f"({len(new_code)} vs {len(original)} chars); no se aplico"}

    return rewrite_file(str(p), new_code, reason=instruction[:100])


def list_backups(path: str = "") -> dict:
    pat = f"{Path(path).name}.*.bak" if path else "*.bak"
    items = sorted(BACKUP_DIR.glob(pat), reverse=True)
    return {"ok": True, "backups": [str(b) for b in items[:30]]}


def restore_backup(backup_path: str) -> dict:
    b = Path(backup_path)
    if not b.is_file():
        return {"ok": False, "error": "backup no existe"}
    # nombre original: <archivo>.<ts>.bak -> <archivo>
    orig_name = b.name.rsplit(".", 2)[0]
    dst = BASE / orig_name
    shutil.copy2(b, dst)
    _audit("self_restore", f"{orig_name} <- {b.name}")
    return {"ok": True, "restored": str(dst), "from": str(b)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["backups", "restore", "test"])
    ap.add_argument("--path", default="")
    a = ap.parse_args()
    if a.cmd == "backups":
        print(json.dumps(list_backups(a.path), indent=2))
    elif a.cmd == "restore":
        print(json.dumps(restore_backup(a.path), indent=2))
    elif a.cmd == "test":
        # Prueba: reescribir un archivo temporal con codigo roto -> debe revertir
        t = BASE / "_selfmod_test.py"
        t.write_text("x = 1\n", encoding="utf-8")
        print("valido:", rewrite_file(str(t), "x = 2\n", "test ok"))
        print("roto  :", rewrite_file(str(t), "def (:\n", "test roto"))
        print("final :", t.read_text())
        t.unlink()
