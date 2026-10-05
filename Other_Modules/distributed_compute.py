"""
distributed_compute.py - Enrutado de inferencia a TUS maquinas (cluster propio).
================================================================================

Convierte "aprovechar mas computo cuando lo haya" en algo concreto y seguro:
un registro de nodos Ollama TUYOS (esta PC + cualquier otra maquina donde
corras Ollama). El sistema mide cada nodo y enruta la inferencia al mas
rapido/capaz disponible.

PRINCIPIO: los nodos se ENROLAN explicitamente (tu agregas la IP de tu otra
maquina). NO se escanea y toma equipos ajenos. `discover()` solo SUGIERE
candidatos que responden como Ollama en TU subred; no enrola nada solo.

Registro persistente: %LOCALAPPDATA%\\vw-control\\compute_nodes.json

API:
    register_node(url, name="")      -> agrega un nodo Ollama tuyo
    remove_node(url)
    list_nodes()                     -> nodos + salud
    best_node(model="")              -> URL del mejor nodo disponible
    benchmark(url)                   -> tokens/seg de un nodo
    discover(subnet="")              -> candidatos Ollama en la subred (sugerencia)
    get_endpoint(model="")           -> base URL a usar (el mejor, o local)
"""
from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

import httpx

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
NODES_FILE = CONFIG_DIR / "compute_nodes.json"

LOCAL = "http://REDACTED_IP:11434"


# =====================================================================
#  Registro
# =====================================================================

def _load() -> list:
    if NODES_FILE.exists():
        try:
            data = json.loads(NODES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    # Semilla: siempre el nodo local
    return [{"url": LOCAL, "name": "local", "added": time.time()}]


def _save(nodes: list):
    NODES_FILE.write_text(json.dumps(nodes, indent=2, ensure_ascii=False),
                          encoding="utf-8")


def _norm(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith("http"):
        url = "http://" + url
    # Si no trae puerto, asumir el de Ollama
    if url.count(":") < 2 and not url.endswith(":11434"):
        url = url + ":11434"
    return url


def register_node(url: str, name: str = "") -> dict:
    url = _norm(url)
    nodes = _load()
    if any(n["url"] == url for n in nodes):
        return {"ok": True, "note": "ya estaba registrado", "url": url}
    h = health(url)
    nodes.append({"url": url, "name": name or url, "added": time.time(),
                  "last_health": h})
    _save(nodes)
    return {"ok": True, "url": url, "health": h}


def remove_node(url: str) -> dict:
    url = _norm(url)
    nodes = _load()
    n2 = [n for n in nodes if n["url"] != url]
    _save(n2)
    return {"ok": True, "removed": len(nodes) - len(n2), "url": url}


# =====================================================================
#  Salud y benchmark
# =====================================================================

def health(url: str) -> dict:
    url = _norm(url)
    t0 = time.time()
    try:
        r = httpx.get(f"{url}/api/tags", timeout=5.0)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        latency = round((time.time() - t0) * 1000)
        # Modelos cargados ahora (indicador de "ocupado")
        loaded = []
        try:
            ps = httpx.get(f"{url}/api/ps", timeout=4.0).json()
            loaded = [m["name"] for m in ps.get("models", [])]
        except Exception:
            pass
        return {"ok": True, "latency_ms": latency, "models": models,
                "loaded": loaded}
    except Exception as e:   # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def benchmark(url: str, model: str = "") -> dict:
    """Mide tokens/seg de un nodo con una generacion corta."""
    url = _norm(url)
    h = health(url)
    if not h.get("ok"):
        return {"ok": False, "error": h.get("error"), "url": url}
    if not model:
        model = h["models"][0] if h.get("models") else "qwen2.5-coder:7b"
    try:
        t0 = time.time()
        r = httpx.post(f"{url}/api/generate", json={
            "model": model, "prompt": "Cuenta del 1 al 20.",
            "stream": False, "options": {"num_predict": 60},
            "keep_alive": "5m"}, timeout=120.0)
        r.raise_for_status()
        d = r.json()
        elapsed = time.time() - t0
        toks = d.get("eval_count", 0)
        tps = round(toks / elapsed, 1) if elapsed > 0 else 0
        return {"ok": True, "url": url, "model": model,
                "tokens_per_sec": tps, "eval_count": toks,
                "elapsed_s": round(elapsed, 1),
                "load_ms": round(d.get("load_duration", 0) / 1e6)}
    except Exception as e:   # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "url": url}


# =====================================================================
#  Seleccion del mejor nodo
# =====================================================================

def list_nodes() -> list:
    nodes = _load()
    for n in nodes:
        n["health"] = health(n["url"])
    return nodes


def best_node(model: str = "") -> dict:
    """Elige el mejor nodo: sano, con el modelo (o capaz de tenerlo),
    priorizando el que ya lo tiene cargado y menor latencia."""
    nodes = _load()
    scored = []
    for n in nodes:
        h = health(n["url"])
        if not h.get("ok"):
            continue
        has_model = (not model) or (model in h.get("models", []))
        loaded = model and model in h.get("loaded", [])
        # score: cargado (mejor) > tiene modelo > sano; desempata latencia
        score = 0
        if loaded: score += 1000
        if has_model: score += 100
        score -= h.get("latency_ms", 999) / 100.0
        # Un nodo remoto sano suele ser mas potente que el local (por eso
        # el usuario lo agrego); leve bonus a los no-locales sanos.
        if n["url"] != LOCAL:
            score += 50
        scored.append((score, n["url"], h))
    if not scored:
        return {"ok": False, "error": "ningun nodo sano", "url": LOCAL}
    scored.sort(reverse=True)
    best = scored[0]
    return {"ok": True, "url": best[1], "score": round(best[0], 1),
            "health": best[2], "candidates": len(scored)}


def get_endpoint(model: str = "") -> str:
    """Devuelve la base URL a usar. Si algo falla, cae a local."""
    try:
        b = best_node(model)
        return b["url"] if b.get("ok") else LOCAL
    except Exception:
        return LOCAL


# =====================================================================
#  Descubrimiento (SUGERENCIA, no enrola solo)
# =====================================================================

def discover(subnet: str = "", timeout: float = 0.4) -> dict:
    """Sondea la subred local buscando hosts que respondan como Ollama.
    SOLO sugiere; no agrega nada. El usuario decide con register_node."""
    if not subnet:
        # Derivar de la IP local
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("REDACTED_IP", 80))
            ip = s.getsockname()[0]
            s.close()
            subnet = ".".join(ip.split(".")[:3])
        except Exception:
            return {"ok": False, "error": "no pude derivar la subred"}
    found = []
    for i in range(1, 255):
        host = f"{subnet}.{i}"
        try:
            with socket.create_connection((host, 11434), timeout=timeout):
                pass
        except Exception:
            continue
        # Puerto abierto: confirmar que es Ollama
        try:
            r = httpx.get(f"http://{host}:11434/api/tags", timeout=2.0)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                found.append({"url": f"http://{host}:11434", "models": models})
        except Exception:
            pass
    return {"ok": True, "subnet": subnet, "candidates": found,
            "note": "Usa register_node(url) para enrolar los que sean TUYOS."}


# =====================================================================
#  CLI
# =====================================================================

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Cluster de computo GIA (nodos propios)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list")
    pr = sub.add_parser("add"); pr.add_argument("url"); pr.add_argument("--name", default="")
    prm = sub.add_parser("remove"); prm.add_argument("url")
    pb = sub.add_parser("bench"); pb.add_argument("url", nargs="?", default=LOCAL)
    pbest = sub.add_parser("best"); pbest.add_argument("--model", default="")
    pd = sub.add_parser("discover"); pd.add_argument("--subnet", default="")
    args = ap.parse_args()

    if args.cmd == "list" or not args.cmd:
        for n in list_nodes():
            h = n["health"]
            st = f"OK {h.get('latency_ms')}ms mods={len(h.get('models',[]))}" if h.get("ok") else f"DOWN ({h.get('error','')[:40]})"
            print(f"  {n['name']:16} {n['url']:28} {st}")
    elif args.cmd == "add":
        print(json.dumps(register_node(args.url, args.name), indent=2, ensure_ascii=False))
    elif args.cmd == "remove":
        print(json.dumps(remove_node(args.url), indent=2, ensure_ascii=False))
    elif args.cmd == "bench":
        print(json.dumps(benchmark(args.url), indent=2, ensure_ascii=False))
    elif args.cmd == "best":
        print(json.dumps(best_node(args.model), indent=2, ensure_ascii=False))
    elif args.cmd == "discover":
        print(json.dumps(discover(args.subnet), indent=2, ensure_ascii=False))
