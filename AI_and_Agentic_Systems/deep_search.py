"""
deep_search.py - Busqueda total: disco completo + datos de navegadores.
========================================================================

Capacidades para el agente GIA:
  - search_files(query, root, ...)  : busca archivos por nombre/extension
    en todo el disco (o una raiz), con filtros y limite.
  - grep_files(pattern, root, ...)  : busca TEXTO dentro de archivos.
  - search_browsers(query)          : historial + marcadores de todos los
    navegadores Chromium (Chrome, Edge, Brave, Opera, Vivaldi) y Firefox.

Los navegadores guardan historial/marcadores en SQLite. Para evitar el
lock del archivo cuando el navegador esta abierto, se copia el .sqlite a
temp antes de leerlo (solo lectura).
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
APPDATA = os.environ.get("APPDATA", "")
USERPROFILE = os.environ.get("USERPROFILE", os.path.expanduser("~"))

try:
    import agent_safety as _safety
    def _audit(a, d, v="ALLOW"):
        _safety.audit(a, d, verdict=v)
except Exception:
    def _audit(a, d, v="ALLOW"):
        pass

# Carpetas a saltar en el barrido de disco (ruido / lentitud)
_SKIP_DIRS = {
    "$recycle.bin", "system volume information", "windows", "$windows.~ws",
    "$windows.~bt", "node_modules", ".git", "__pycache__", "appdata",
    "programdata", "$sysreset", "recovery",
}


# =====================================================================
#  BUSQUEDA DE ARCHIVOS POR NOMBRE
# =====================================================================

def search_files(args: dict) -> dict:
    """Busca archivos por substring/extension.

    args: {query, root?, extensions?(list), limit?, skip_system?}
    """
    query = (args.get("query") or "").lower()
    root = os.path.expandvars(args.get("root") or USERPROFILE)
    exts = [e.lower().lstrip(".") for e in (args.get("extensions") or [])]
    limit = int(args.get("limit", 200))
    skip_system = bool(args.get("skip_system", True))

    if not query and not exts:
        return {"ok": False, "error": "da al menos query o extensions"}

    hits = []
    t0 = time.time()
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # Podar directorios ruidosos
        if skip_system:
            dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_DIRS]
        for fn in filenames:
            scanned += 1
            fn_l = fn.lower()
            if exts and fn_l.rsplit(".", 1)[-1] not in exts:
                continue
            if query and query not in fn_l:
                continue
            full = os.path.join(dirpath, fn)
            try:
                st = os.stat(full)
                hits.append({"path": full, "size": st.st_size,
                             "modified": time.strftime("%Y-%m-%d %H:%M",
                                                       time.localtime(st.st_mtime))})
            except Exception:
                hits.append({"path": full})
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
        # No dejar que se cuelgue eternamente en un disco enorme
        if time.time() - t0 > 60:
            break
    _audit("search_files", f"q='{query}' root={root} hits={len(hits)}")
    return {"ok": True, "query": query, "root": root, "scanned": scanned,
            "count": len(hits), "elapsed_s": round(time.time() - t0, 1),
            "hits": hits}


# =====================================================================
#  BUSQUEDA DE TEXTO DENTRO DE ARCHIVOS
# =====================================================================

_TEXT_EXTS = {"txt", "md", "py", "js", "ts", "json", "csv", "log", "ini",
              "cfg", "xml", "html", "htm", "yaml", "yml", "ps1", "bat",
              "c", "cpp", "h", "java", "cs", "go", "rs", "sql", "vs"}


def grep_files(args: dict) -> dict:
    """Busca un patron (regex) dentro de archivos de texto.

    args: {pattern, root?, extensions?, limit?, ignore_case?}
    """
    pattern = args.get("pattern", "")
    if not pattern:
        return {"ok": False, "error": "pattern requerido"}
    root = os.path.expandvars(args.get("root") or USERPROFILE)
    exts = set(e.lower().lstrip(".") for e in
               (args.get("extensions") or _TEXT_EXTS))
    limit = int(args.get("limit", 100))
    flags = re.IGNORECASE if args.get("ignore_case", True) else 0
    try:
        rx = re.compile(pattern, flags)
    except re.error as e:
        return {"ok": False, "error": f"regex invalida: {e}"}

    matches = []
    t0 = time.time()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_DIRS]
        for fn in filenames:
            ext = fn.lower().rsplit(".", 1)[-1] if "." in fn else ""
            if ext not in exts:
                continue
            full = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(full) > 5_000_000:   # saltar >5MB
                    continue
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    for lineno, line in enumerate(f, 1):
                        if rx.search(line):
                            matches.append({"path": full, "line": lineno,
                                            "text": line.strip()[:200]})
                            if len(matches) >= limit:
                                break
            except Exception:
                continue
            if len(matches) >= limit:
                break
        if len(matches) >= limit or time.time() - t0 > 60:
            break
    _audit("grep_files", f"pat='{pattern[:40]}' hits={len(matches)}")
    return {"ok": True, "pattern": pattern, "count": len(matches),
            "elapsed_s": round(time.time() - t0, 1), "matches": matches}


# =====================================================================
#  DATOS DE NAVEGADORES
# =====================================================================

def _chromium_profiles() -> list:
    """Rutas de perfiles Chromium (Chrome, Edge, Brave, Opera, Vivaldi)."""
    bases = {
        "Chrome": os.path.join(LOCALAPPDATA, "Google", "Chrome", "User Data"),
        "Edge": os.path.join(LOCALAPPDATA, "Microsoft", "Edge", "User Data"),
        "Brave": os.path.join(LOCALAPPDATA, "BraveSoftware",
                              "Brave-Browser", "User Data"),
        "Vivaldi": os.path.join(LOCALAPPDATA, "Vivaldi", "User Data"),
        "Opera": os.path.join(APPDATA, "Opera Software", "Opera Stable"),
    }
    profiles = []
    for browser, base in bases.items():
        if not base or not os.path.isdir(base):
            continue
        # Opera guarda directo; Chromium usa Default / Profile N
        candidates = [base] + [os.path.join(base, d) for d in
                               ("Default", "Profile 1", "Profile 2", "Profile 3")]
        for prof in candidates:
            if os.path.isfile(os.path.join(prof, "History")):
                profiles.append((browser, prof))
    return profiles


def _read_sqlite_copy(src: str, query: str, params=()) -> list:
    """Copia el sqlite (evita lock) y ejecuta una query de lectura."""
    if not os.path.isfile(src):
        return []
    tmp = os.path.join(tempfile.gettempdir(),
                       f"gia_brweb_{int(time.time()*1000)}.sqlite")
    try:
        shutil.copy2(src, tmp)
        con = sqlite3.connect(tmp)
        con.text_factory = lambda b: b.decode("utf-8", "ignore")
        cur = con.execute(query, params)
        rows = cur.fetchall()
        con.close()
        return rows
    except Exception:
        return []
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def search_browsers(args: dict) -> dict:
    """Busca en historial y marcadores de todos los navegadores.

    args: {query, limit?}
    """
    query = (args.get("query") or "").lower()
    limit = int(args.get("limit", 50))
    results = {"history": [], "bookmarks": []}

    # --- Chromium: History (SQLite) ---
    for browser, prof in _chromium_profiles():
        hist_db = os.path.join(prof, "History")
        rows = _read_sqlite_copy(
            hist_db,
            "SELECT url, title, visit_count, last_visit_time "
            "FROM urls ORDER BY last_visit_time DESC LIMIT 3000")
        for url, title, vc, _ in rows:
            hay = f"{url} {title}".lower()
            if not query or query in hay:
                results["history"].append(
                    {"browser": browser, "title": (title or "")[:80],
                     "url": (url or "")[:150], "visits": vc})
                if len(results["history"]) >= limit:
                    break
        # Bookmarks (JSON)
        bm = os.path.join(prof, "Bookmarks")
        if os.path.isfile(bm):
            try:
                import json as _json
                data = _json.loads(open(bm, encoding="utf-8").read())

                def _walk(node):
                    if isinstance(node, dict):
                        if node.get("type") == "url":
                            hay = f"{node.get('url','')} {node.get('name','')}".lower()
                            if not query or query in hay:
                                results["bookmarks"].append(
                                    {"browser": browser,
                                     "name": node.get("name", "")[:80],
                                     "url": node.get("url", "")[:150]})
                        for ch in node.get("children", []):
                            _walk(ch)
                    elif isinstance(node, list):
                        for ch in node:
                            _walk(ch)
                for root_node in data.get("roots", {}).values():
                    _walk(root_node)
            except Exception:
                pass

    # --- Firefox: places.sqlite ---
    ff_base = os.path.join(APPDATA, "Mozilla", "Firefox", "Profiles")
    if os.path.isdir(ff_base):
        for prof in os.listdir(ff_base):
            places = os.path.join(ff_base, prof, "places.sqlite")
            rows = _read_sqlite_copy(
                places,
                "SELECT url, title, visit_count FROM moz_places "
                "ORDER BY last_visit_date DESC LIMIT 3000")
            for url, title, vc in rows:
                hay = f"{url} {title}".lower()
                if not query or query in hay:
                    results["history"].append(
                        {"browser": "Firefox", "title": (title or "")[:80],
                         "url": (url or "")[:150], "visits": vc or 0})
                    if len(results["history"]) >= limit * 2:
                        break

    _audit("search_browsers", f"q='{query}' hist={len(results['history'])} "
                              f"bm={len(results['bookmarks'])}")
    return {"ok": True, "query": query,
            "history_count": len(results["history"]),
            "bookmark_count": len(results["bookmarks"]),
            "history": results["history"][:limit],
            "bookmarks": results["bookmarks"][:limit]}


# =====================================================================
#  Self-test
# =====================================================================
if __name__ == "__main__":
    import json
    print("=== profiles detectados ===")
    for b, p in _chromium_profiles():
        print(f"  {b}: {p}")
    print("\n=== search_browsers (query='github') ===")
    r = search_browsers({"query": "github", "limit": 5})
    print(json.dumps(r, indent=2, ensure_ascii=False)[:1500])
