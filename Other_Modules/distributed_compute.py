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

import concurrent.futures
import ipaddress
import json
import os
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

import httpx

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
NODES_FILE = CONFIG_DIR / "compute_nodes.json"

LOCAL = "http://127.0.0.1:11434"

# Solo se enrolan automáticamente equipos del Arquitecto. Nunca se toma un
# vecino de red ajeno: el nombre reverso o la IP deben coincidir con esta lista.
TRUSTED_HOST_PATTERNS = (
    "imac", "mac-14", "mac14", "macbook", "ideapad", "tardis", "timemachine",
)
TRUSTED_IPS = {
    "REDACTED_IP",   # iMac 14,1 (IP fija histórica)
    "REDACTED_IP",   # iMac 14,1 (IP de rescate)
    "REDACTED_IP",   # iMac 14,1 (enlace directo Ethernet)
}
MESH_LOG = Path(__file__).resolve().parent / "data" / "compute_mesh.jsonl"


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
#  Descubrimiento multi-subred (SUGERENCIA / AUTO-ENROLAMIENTO CONFIANZA)
# =====================================================================

def local_subnets() -> list[str]:
    """Devuelve todas las subredes IPv4 locales, excluyendo loopback y docker."""
    out: list[str] = []
    try:
        r = subprocess.run(
            ["ip", "-4", "-o", "addr", "show"],
            capture_output=True, text=True, timeout=3,
        )
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[2] == "inet":
                cidr = parts[3]
                net = ipaddress.ip_network(cidr, strict=False)
                if net.version != 4 or net.is_loopback:
                    continue
                if str(net.network_address).startswith(("10.240.", "172.17.", "172.18.")):
                    continue
                out.append(str(net))
    except Exception:
        pass

    if not out:
        # Fallback clásico: IP de salida + /24
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("REDACTED_IP", 80))
            ip = s.getsockname()[0]
            s.close()
            out.append(".".join(ip.split(".")[:3]) + ".0/24")
        except Exception:
            pass
    return sorted(set(out))


def _probe_ollama(host: str, port: int = 11434, timeout: float = 0.35) -> dict | None:
    """Comprueba un host:puerto y confirma que la API sea Ollama."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        return None
    try:
        req = urllib.request.Request(
            f"http://{host}:{port}/api/tags",
            headers={"User-Agent": "TARDIS-Compute-Mesh/1.0"},
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        models = [m.get("name", "") for m in data.get("models", [])]
        return {"url": f"http://{host}:{port}", "models": models}
    except Exception:
        return None


def discover_network(
    subnets: list[str] | None = None,
    port: int = 11434,
    timeout: float = 0.35,
    workers: int = 128,
    max_hosts: int = 4096,
) -> list[dict]:
    """Escanea en paralelo todas las subredes locales buscando Ollama.

    No modifica el registro; devuelve candidatos para inspección o para
    ``autoenroll_trusted``. El escaneo es de solo lectura (GET /api/tags).
    """
    subnets = subnets or local_subnets()
    hosts: list[str] = []
    for cidr in subnets:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            continue
        if net.version != 4:
            continue
        # Nunca escanear más de /22 por subred (evita redes corporativas enormes)
        if net.num_addresses > 1024:
            net = ipaddress.ip_network(f"{net.network_address}/22", strict=False)
        for ip in net.hosts():
            hosts.append(str(ip))
            if len(hosts) >= max_hosts:
                break
        if len(hosts) >= max_hosts:
            break

    found: list[dict] = []
    if not hosts:
        return found
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(8, workers)) as ex:
        futures = {ex.submit(_probe_ollama, h, port, timeout): h for h in hosts}
        for fut in concurrent.futures.as_completed(futures):
            try:
                item = fut.result()
            except Exception:
                item = None
            if item:
                item["host"] = futures[fut]
                found.append(item)
    found.sort(key=lambda c: c["url"])
    return found


def discover(subnet: str = "", timeout: float = 0.4) -> dict:
    """Compatibilidad: sondea una subred (o todas) buscando Ollama.

    ``subnet`` puede ser "192.168.1" o "REDACTED_IP/24". Sin argumento escanea
    todas las interfaces locales. Solo sugiere; no enrola nada.
    """
    if subnet:
        cidr = subnet if "/" in subnet else subnet.rstrip(".") + ".0/24"
        subnets = [cidr]
    else:
        subnets = local_subnets()
    found = discover_network(subnets, timeout=timeout)
    return {
        "ok": True,
        "subnets": subnets,
        "candidates": found,
        "note": "Usa register_node(url) o autoenroll_trusted() para enrolar equipos TUYOS.",
    }


def _reverse_name(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0].split(".")[0]
    except Exception:
        return ""


def autoenroll_trusted(candidates: list[dict] | None = None, dry_run: bool = False) -> dict:
    """Enrola únicamente nodos que pertenezcan al Arquitecto.

    Criterio: IP histórica del iMac/IdeaPad o nombre reverso que contenga
    ``imac``, ``mac14``, ``ideapad``, ``tardis`` o ``timemachine``.
    """
    if candidates is None:
        candidates = discover_network()
    enrolled: list[dict] = []
    skipped: list[dict] = []
    for cand in candidates:
        url = cand.get("url", "")
        host = urllib.parse.urlparse(url).hostname or ""
        name = _reverse_name(host)
        trusted = host in TRUSTED_IPS or any(
            pat in name.lower() for pat in TRUSTED_HOST_PATTERNS
        )
        if not trusted:
            skipped.append({"url": url, "hostname": name, "reason": "no confiable"})
            continue
        if dry_run:
            enrolled.append({"url": url, "name": name or host, "dry_run": True})
            continue
        result = register_node(url, name or f"trusted-{host}")
        enrolled.append({"url": url, "name": name or host, "result": result})
    return {"ok": True, "enrolled": enrolled, "skipped": skipped}


def watch(interval: int = 300, once: bool = False) -> dict:
    """Bucle de descubrimiento + auto-enrolamiento con bitácora JSONL."""
    MESH_LOG.parent.mkdir(parents=True, exist_ok=True)
    record: dict = {}
    while True:
        started = time.time()
        found = discover_network()
        auto = autoenroll_trusted(found)
        record = {
            "ts": started,
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
            "subnets": local_subnets(),
            "candidates": found,
            "enrolled": auto.get("enrolled", []),
            "skipped": auto.get("skipped", []),
            "elapsed_s": round(time.time() - started, 2),
        }
        try:
            with MESH_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass
        if once:
            return record
        time.sleep(max(30, int(interval)))


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
    pd.add_argument("--all", action="store_true"); pd.add_argument("--autoenroll", action="store_true")
    pae = sub.add_parser("autoenroll"); pae.add_argument("--dry-run", action="store_true")
    pae.add_argument("--subnet", default="")
    pw = sub.add_parser("watch"); pw.add_argument("--interval", type=int, default=300)
    pw.add_argument("--once", action="store_true")
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
        if args.all or not args.subnet:
            result = discover()
        else:
            result = discover(args.subnet)
        if args.autoenroll:
            result["autoenroll"] = autoenroll_trusted(result.get("candidates", []))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.cmd == "autoenroll":
        if args.subnet:
            cands = discover(args.subnet).get("candidates", [])
        else:
            cands = discover_network()
        print(json.dumps(autoenroll_trusted(cands, dry_run=args.dry_run),
                         indent=2, ensure_ascii=False))
    elif args.cmd == "watch":
        print(json.dumps(watch(interval=args.interval, once=args.once),
                         indent=2, ensure_ascii=False))
