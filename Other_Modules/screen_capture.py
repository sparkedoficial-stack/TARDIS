"""
core/screen_capture.py - Captura Soberana de Pantalla (Wayland / X11)
=====================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS / FTL
Arquitecto: El Arquitecto (₪)

Motivación técnica:
  El host opera Hyprland sobre Wayland. `mss` (X11) no está disponible en el
  venv del servicio y, aun estando presente, bajo XWayland suele devolver un
  framebuffer negro. `grim` es el capturador nativo de Wayland y sí funciona
  con el entorno real de la sesión.

Capacidades:
  1. Descubrimiento automático del entorno gráfico (XDG_RUNTIME_DIR,
     WAYLAND_DISPLAY, HYPRLAND_INSTANCE_SIGNATURE y DISPLAY) incluso cuando el
     proceso corre bajo systemd --user con un entorno mínimo.
  2. Captura de pantalla completa por `grim` (Wayland), con respaldo a `mss`,
     ImageMagick (`import`) y `scrot` para X11.
  3. Captura de una ventana concreta por título/clase usando la geometría
     publicada por `hyprctl clients`.
  4. Redimensionado y compresión JPEG/PNG con Pillow cuando está disponible.
  5. Detección de pantalla bloqueada para no filtrar el escritorio privado.

API principal:
    capture(fmt="jpeg", max_width=1600, quality=82, window="telegram")
        -> (bytes, meta)
    list_windows() -> list[dict]
    find_window("titulo o clase") -> dict | None
    is_locked() -> bool
"""

from __future__ import annotations

import io
import json
import os
import shutil
import stat
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

GRIM = "/usr/bin/grim"
HYPRCTL = "/usr/bin/hyprctl"
MAX_CAPTURE_TIMEOUT = 20.0


# ---------------------------------------------------------------------------
# Entorno de sesión
# ---------------------------------------------------------------------------

def _is_socket(path: Path) -> bool:
    try:
        return stat.S_ISSOCK(path.stat().st_mode)
    except OSError:
        return False


def _detect_wayland_display(runtime: Path) -> str:
    """Selecciona el socket Wayland vivo (wayland-1, wayland-0...)."""
    current = (os.environ.get("WAYLAND_DISPLAY") or "").strip()
    if current and _is_socket(runtime / current):
        return current
    for name in ("wayland-1", "wayland-0"):
        if _is_socket(runtime / name):
            return name
    try:
        sockets = [
            p for p in runtime.iterdir()
            if p.name.startswith("wayland-") and not p.name.endswith(".lock") and _is_socket(p)
        ]
        if sockets:
            sockets.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return sockets[0].name
    except OSError:
        pass
    return current


def _detect_hypr_signature(runtime: Path) -> str:
    """Localiza la firma de la instancia Hyprland activa."""
    current = (os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or "").strip()
    if current:
        return current
    hypr_dir = runtime / "hypr"
    try:
        instances = [d for d in hypr_dir.iterdir() if d.is_dir()]
        if instances:
            instances.sort(key=lambda d: d.stat().st_mtime, reverse=True)
            return instances[0].name
    except OSError:
        pass
    return ""


def session_env() -> Dict[str, str]:
    """Entorno reproducible para hablar con Wayland/Hyprland desde systemd."""
    env = os.environ.copy()
    uid = os.getuid()

    runtime = Path(env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}")
    if not runtime.is_dir():
        runtime = Path(f"/run/user/{uid}")
    env["XDG_RUNTIME_DIR"] = str(runtime)

    wayland = _detect_wayland_display(runtime)
    if wayland:
        env["WAYLAND_DISPLAY"] = wayland

    signature = _detect_hypr_signature(runtime)
    if signature:
        env["HYPRLAND_INSTANCE_SIGNATURE"] = signature

    if not env.get("DISPLAY"):
        for number in (0, 1):
            if _is_socket(Path(f"/tmp/.X11-unix/X{number}")):
                env["DISPLAY"] = f":{number}"
                break

    return env


# ---------------------------------------------------------------------------
# Ejecución de capturadores
# ---------------------------------------------------------------------------

def _run(cmd: List[str], env: Optional[Dict[str, str]] = None,
         timeout: float = MAX_CAPTURE_TIMEOUT) -> Tuple[int, bytes, str]:
    proc = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env or session_env(),
        timeout=timeout,
    )
    stderr = proc.stderr.decode("utf-8", "replace").strip()
    return proc.returncode, proc.stdout or b"", stderr


def _grim_available() -> bool:
    return bool(shutil.which("grim") or Path(GRIM).is_file())


def _hyprctl_available() -> bool:
    return bool(shutil.which("hyprctl") or Path(HYPRCTL).is_file())


def _grim_binary() -> str:
    return shutil.which("grim") or GRIM


def _hyprctl_binary() -> str:
    return shutil.which("hyprctl") or HYPRCTL


# ---------------------------------------------------------------------------
# Ventanas (Hyprland)
# ---------------------------------------------------------------------------

def _normalize_client(client: Dict[str, Any]) -> Dict[str, Any]:
    at = client.get("at") or [0, 0]
    size = client.get("size") or [0, 0]
    return {
        "address": client.get("address", ""),
        "title": (client.get("title") or "").strip(),
        "class": (client.get("class") or "").strip(),
        "initial_class": (client.get("initialClass") or "").strip(),
        "pid": client.get("pid"),
        "mapped": bool(client.get("mapped", True)),
        "hidden": bool(client.get("hidden", False)),
        "visible": bool(client.get("visible", True)),
        "at": [int(at[0]), int(at[1])],
        "size": [int(size[0]), int(size[1])],
        "workspace": (client.get("workspace") or {}).get("name", ""),
        "floating": bool(client.get("floating", False)),
        "fullscreen": int(client.get("fullscreen", 0) or 0),
    }


def _hypr_json(args: List[str]) -> Any:
    if not _hyprctl_available():
        return None
    try:
        rc, out, _err = _run([_hyprctl_binary(), *args], timeout=8.0)
        if rc != 0 or not out.strip():
            return None
        return json.loads(out.decode("utf-8", "replace"))
    except Exception:
        return None


def list_windows() -> List[Dict[str, Any]]:
    """Lista las ventanas visibles/mapeadas del escritorio Hyprland."""
    data = _hypr_json(["clients", "-j"])
    if not isinstance(data, list):
        return []
    windows: List[Dict[str, Any]] = []
    for client in data:
        if not isinstance(client, dict):
            continue
        item = _normalize_client(client)
        if not item["address"] or not item["mapped"] or item["hidden"]:
            continue
        if item["size"][0] <= 0 or item["size"][1] <= 0:
            continue
        windows.append(item)
    windows.sort(key=lambda w: (w["at"][1], w["at"][0]))
    return windows


def active_window() -> Optional[Dict[str, Any]]:
    data = _hypr_json(["activewindow", "-j"])
    if isinstance(data, dict) and data.get("address"):
        return _normalize_client(data)
    return None


def find_window(term: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Busca una ventana por título, clase o clase inicial (subcadena, sin
    distinción de mayúsculas). Sin término devuelve la ventana activa.
    """
    if not term:
        return active_window()
    needle = term.strip().casefold()
    if not needle:
        return active_window()

    windows = list_windows()
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for window in windows:
        title = window["title"].casefold()
        klass = window["class"].casefold()
        initial = window["initial_class"].casefold()
        score = 0
        if needle == title or needle == klass or needle == initial:
            score = 100
        elif needle in title:
            score = 80
        elif needle in klass or needle in initial:
            score = 60
        if score:
            scored.append((score, window))
    if not scored:
        return None
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[0][1]


def _geometry_for(window: Dict[str, Any]) -> str:
    x, y = window["at"]
    width, height = window["size"]
    return f"{x},{y} {width}x{height}"


# ---------------------------------------------------------------------------
# Bloqueo de pantalla
# ---------------------------------------------------------------------------

_LOCKERS = ("hyprlock", "swaylock", "gtklock", "i3lock", "waylock")


def is_locked() -> bool:
    """True si hay un bloqueador de pantalla activo (evita filtraciones)."""
    for locker in _LOCKERS:
        if not shutil.which(locker):
            continue
        try:
            rc, _out, _err = _run(["pgrep", "-x", locker], timeout=3.0)
            if rc == 0:
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Captura
# ---------------------------------------------------------------------------

def _capture_png(region: Optional[Tuple[int, int, int, int]] = None,
                 window: Optional[Dict[str, Any]] = None) -> Tuple[bytes, str]:
    """Captura PNG nativo por grim. Devuelve (bytes, método)."""
    if not _grim_available():
        raise RuntimeError("grim no está instalado")

    cmd = [_grim_binary(), "-t", "png", "-l", "4"]
    if window:
        cmd += ["-g", _geometry_for(window)]
    elif region and len(region) == 4:
        x, y, width, height = region
        cmd += ["-g", f"{int(x)},{int(y)} {int(width)}x{int(height)}"]
    cmd.append("-")

    rc, out, err = _run(cmd)
    if rc != 0 or not out.startswith(b"\x89PNG"):
        raise RuntimeError(f"grim falló (rc={rc}): {err[:300] or 'sin salida'}")
    return out, "grim"


def _capture_mss(region: Optional[Tuple[int, int, int, int]] = None) -> Tuple[bytes, str]:
    """Respaldo X11 con mss + Pillow."""
    import mss  # type: ignore
    from PIL import Image  # type: ignore

    with mss.mss() as sct:
        if region and len(region) == 4:
            x, y, width, height = region
            bbox = {"left": int(x), "top": int(y), "width": int(width), "height": int(height)}
        else:
            bbox = sct.monitors[0]
        shot = sct.grab(bbox)
        image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), "mss"


def _capture_imagemagick(region: Optional[Tuple[int, int, int, int]] = None) -> Tuple[bytes, str]:
    binary = shutil.which("import")
    if not binary:
        raise RuntimeError("ImageMagick import no está instalado")
    cmd = [binary, "-window", "root"]
    if region and len(region) == 4:
        x, y, width, height = region
        cmd = [binary, "-window", "root", "-crop", f"{int(width)}x{int(height)}+{int(x)}+{int(y)}", "+repage"]
    cmd.append("png:-")
    rc, out, err = _run(cmd)
    if rc != 0 or not out.startswith(b"\x89PNG"):
        raise RuntimeError(f"import falló: {err[:300]}")
    return out, "imagemagick"


def _capture_scrot(region: Optional[Tuple[int, int, int, int]] = None) -> Tuple[bytes, str]:
    binary = shutil.which("scrot")
    if not binary:
        raise RuntimeError("scrot no está instalado")
    cmd = [binary, "-o"]
    if region and len(region) == 4:
        x, y, width, height = region
        cmd += ["-a", f"{int(x)},{int(y)},{int(width)},{int(height)}"]
    cmd.append("-")
    rc, out, err = _run(cmd)
    if rc != 0 or not out.startswith(b"\x89PNG"):
        raise RuntimeError(f"scrot falló: {err[:300]}")
    return out, "scrot"


def capture(
    fmt: str = "jpeg",
    max_width: Optional[int] = 1600,
    quality: int = 82,
    region: Optional[Tuple[int, int, int, int]] = None,
    window: Optional[Any] = None,
    allow_locked: bool = False,
) -> Tuple[bytes, Dict[str, Any]]:
    """
    Captura la pantalla o una ventana y devuelve (bytes, metadatos).

    `window` puede ser un término de búsqueda (str) o un dict de `list_windows`.
    """
    if is_locked() and not allow_locked:
        raise RuntimeError("La pantalla está bloqueada; captura omitida por seguridad")

    target: Optional[Dict[str, Any]] = None
    if isinstance(window, dict):
        target = window
    elif isinstance(window, str) and window.strip():
        target = find_window(window)
        if target is None:
            raise RuntimeError(f"No se encontró ninguna ventana que coincida con «{window}»")

    errors: List[str] = []
    png_bytes = b""
    method = ""

    # Wayland primero: es la sesión real del Arquitecto.
    if _grim_available():
        try:
            png_bytes, method = _capture_png(region=region, window=target)
        except Exception as exc:
            errors.append(str(exc))
    if not png_bytes:
        for candidate in (_capture_mss, _capture_imagemagick, _capture_scrot):
            try:
                png_bytes, method = candidate(region=region)
                break
            except Exception as exc:
                errors.append(f"{candidate.__name__}: {exc}")
    if not png_bytes:
        raise RuntimeError("No fue posible capturar la pantalla: " + " | ".join(errors[-4:]))

    fmt = (fmt or "jpeg").lower()
    if fmt in ("jpg", "jpeg"):
        fmt = "jpeg"

    output = png_bytes
    width = height = 0
    try:
        from PIL import Image  # type: ignore

        with Image.open(io.BytesIO(png_bytes)) as image:
            image = image.convert("RGB")
            width, height = image.size
            if max_width and width > int(max_width):
                ratio = int(max_width) / float(width)
                new_size = (int(max_width), max(1, int(height * ratio)))
                image = image.resize(new_size, Image.Resampling.BILINEAR)
                width, height = image.size
            buffer = io.BytesIO()
            if fmt == "jpeg":
                image.save(buffer, format="JPEG", quality=int(quality), optimize=True)
            else:
                image.save(buffer, format="PNG", optimize=True)
            output = buffer.getvalue()
    except Exception:
        # Sin Pillow se entrega el PNG original (Telegram lo acepta igualmente).
        if fmt == "jpeg" and _grim_available() and not target and not region:
            try:
                cmd = [_grim_binary(), "-t", "jpeg", "-q", str(int(quality)), "-"]
                rc, out, err = _run(cmd)
                if rc == 0 and out[:2] == b"\xff\xd8":
                    output = out
                    fmt = "jpeg"
            except Exception:
                pass
        else:
            fmt = "png"

    meta: Dict[str, Any] = {
        "method": method,
        "format": fmt,
        "width": width,
        "height": height,
        "bytes": len(output),
        "window": target,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "wayland_display": session_env().get("WAYLAND_DISPLAY", ""),
        "hypr_signature": session_env().get("HYPRLAND_INSTANCE_SIGNATURE", ""),
    }
    return output, meta


def quick_self_test() -> Dict[str, Any]:
    """Diagnóstico de una línea para /status y pruebas de humo."""
    env = session_env()
    result: Dict[str, Any] = {
        "grim": _grim_available(),
        "hyprctl": _hyprctl_available(),
        "locked": is_locked(),
        "wayland_display": env.get("WAYLAND_DISPLAY", ""),
        "hypr_signature": bool(env.get("HYPRLAND_INSTANCE_SIGNATURE")),
        "display": env.get("DISPLAY", ""),
        "windows": len(list_windows()),
    }
    try:
        raw, meta = capture(fmt="jpeg", max_width=800, quality=70)
        result.update({"ok": True, "capture_bytes": len(raw), "method": meta.get("method")})
    except Exception as exc:
        result.update({"ok": False, "error": str(exc)})
    return result


if __name__ == "__main__":  # pragma: no cover - utilidad de consola
    started = time.time()
    info = quick_self_test()
    print(json.dumps(info, ensure_ascii=False, indent=2))
    print(f"duración: {time.time() - started:.2f}s")
