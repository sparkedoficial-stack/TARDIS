"""
core/video_pipeline_4k.py - Tuberia de Video 4K @ 60 FPS para TARDIS
=====================================================================
GODWORKS SYSTEM v26.4

Renderiza los videomensajes del personaje 3D en UHD (3840x2160) a 60 FPS:

  * Estado vocal (visemas -> mandibula, iris, barras) derivado de las marcas
    de tiempo por palabra de la sintesis neural.
  * HUD nativo 4K con cache: marco, titulo, subtitulos y barra de progreso.
  * Render paralelo por segmentos (un proceso por segmento, N nucleos).
  * Codificacion por GPU (NVENC) con respaldo a libx264, y control de tasa
    para respetar el limite de subida de la API de Telegram.
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("VideoPipeline4K")

BASE_DIR = Path(__file__).resolve().parent.parent
FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"

TELEGRAM_MAX_BYTES = 48 * 1024 * 1024     # margen bajo el limite de 50 MB del bot


# ---------------------------------------------------------------- estado vocal
def compute_vocal_state(t: float, word_timings: List[Dict[str, Any]], duration: float) -> Dict[str, float]:
    """Traduce las marcas fonéticas en parametros de animacion del personaje."""
    active = None
    for w in word_timings:
        if w.get("start", 0.0) <= t <= w.get("end", 0.0):
            active = w
            break

    if active:
        dur = max(0.01, float(active.get("duration", 0.3)))
        rel = (t - float(active.get("start", 0.0))) / dur
        syl = max(1, int(active.get("syllables", 1)))
        env = math.sin(max(0.0, min(1.0, rel)) * math.pi * syl)
        target = float(active.get("target_open", 0.7))
        mouth = max(0.10, target * (0.32 + 0.68 * max(0.0, env)))
        width = float(active.get("target_width", 1.0))
        pulse = 1.0 if active.get("emphasis") else 0.72
        energy = 0.55 + 0.45 * abs(env)
    else:
        mouth, width, pulse, energy = 0.05, 1.0, 0.0, 0.12

    blink_phase = t % 3.7
    blink = 0.0
    if blink_phase < 0.17:
        blink = math.sin(blink_phase / 0.17 * math.pi)

    return {
        "mouth_open": mouth,
        "mouth_width": width,
        "blink": blink,
        "vocal_pulse": pulse,
        "energy": energy,
        "progress": 0.0 if duration <= 0 else max(0.0, min(1.0, t / duration)),
    }


# ------------------------------------------------------------------------ HUD
class HudRenderer:
    """Capa de interfaz en resolucion nativa, con elementos estaticos cacheados."""

    def __init__(self, width: int, height: int, title: str = "TARDIS · MENSAJE SOBERANO"):
        self.w, self.h = width, height
        self.title = title
        self.k = height / 2160.0           # factor de escala respecto de UHD
        self._sub_cache: Dict[str, np.ndarray] = {}
        self._static_pm, self._static_inv = self._build_static()
        self.top_h = int(self.h * 0.135)
        self.bot_y = int(self.h * 0.70)

    def _font(self, path: str, size: int) -> ImageFont.ImageFont:
        try:
            return ImageFont.truetype(path, max(8, int(size)))
        except Exception:
            return ImageFont.load_default()

    def _build_static(self) -> Tuple[np.ndarray, np.ndarray]:
        k = self.k
        layer = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        teal = (0, 212, 200)
        gold = (232, 182, 74)

        # Esquinas tecnicas
        m = int(46 * k)
        ln = int(150 * k)
        tw = max(2, int(5 * k))
        for (px, py, dx, dy) in ((m, m, 1, 1), (self.w - m, m, -1, 1),
                                 (m, self.h - m, 1, -1), (self.w - m, self.h - m, -1, -1)):
            d.line([(px, py), (px + dx * ln, py)], fill=teal + (215,), width=tw)
            d.line([(px, py), (px, py + dy * ln)], fill=teal + (215,), width=tw)

        # Titulo
        f_title = self._font(FONT_BOLD, 78 * k)
        d.text((int(100 * k), int(84 * k)), self.title, font=f_title, fill=(235, 250, 250, 255))

        # Subrayado del titulo
        d.line([(int(100 * k), int(196 * k)), (int(1180 * k), int(196 * k))], fill=gold + (200,), width=max(2, int(5 * k)))

        # Insignia de formato
        f_badge = self._font(FONT_BOLD, 46 * k)
        badge = "● UHD 4K · 60 FPS · RENDER 3D SOBERANO"
        bb = d.textbbox((0, 0), badge, font=f_badge)
        d.text((self.w - int(100 * k) - (bb[2] - bb[0]), int(100 * k)), badge, font=f_badge, fill=gold + (235,))

        # Barra inferior de estado
        by = int(self.h - 170 * k)
        d.line([(int(100 * k), by), (self.w - int(100 * k), by)], fill=teal + (110,), width=max(1, int(3 * k)))
        f_small = self._font(FONT_REG, 40 * k)
        d.text((int(100 * k), by + int(28 * k)), "GODWORKS SYSTEM v26.4 · NODO SOBERANO TARDIS",
               font=f_small, fill=(150, 195, 200, 220))

        arr = np.asarray(layer)
        a = arr[:, :, 3].astype(np.float32) / 255.0
        rgb_pm = (arr[:, :, :3].astype(np.float32) * a[:, :, None]).astype(np.uint8)
        inv = np.repeat(((1.0 - a) * 255.0).astype(np.uint8)[:, :, None], 3, axis=2)
        return rgb_pm, inv

    def _subtitle_img(self, line: str) -> Tuple[np.ndarray, np.ndarray]:
        """Renderiza (y cachea) una linea de subtitulo como RGBA float."""
        cached = self._sub_cache.get(line)
        if cached is not None:
            return cached
        k = self.k
        sw, sh = self.w, int(300 * k)
        img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        f = self._font(FONT_BOLD, 74 * k)
        bb = d.textbbox((0, 0), line, font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        x = (sw - tw) // 2
        y = int(40 * k)
        pad = int(34 * k)
        d.rounded_rectangle([x - pad, y - pad // 2, x + tw + pad, y + th + pad],
                            radius=int(26 * k), fill=(4, 12, 20, 190), outline=(0, 212, 200, 150),
                            width=max(1, int(3 * k)))
        d.text((x, y), line, font=f, fill=(238, 252, 252, 255))
        arr = np.asarray(img)
        a = arr[:, :, 3].astype(np.float32) / 255.0
        pm = (arr[:, :, :3].astype(np.float32) * a[:, :, None]).astype(np.uint8)
        inv = np.repeat(((1.0 - a) * 255.0).astype(np.uint8)[:, :, None], 3, axis=2)
        if len(self._sub_cache) > 48:
            self._sub_cache.clear()
        self._sub_cache[line] = (pm, inv)
        return pm, inv

    @staticmethod
    def build_lines(word_timings: List[Dict[str, Any]], max_chars: int = 62) -> List[Dict[str, Any]]:
        """Agrupa palabras en lineas de subtitulo con su ventana temporal."""
        lines: List[Dict[str, Any]] = []
        cur: List[str] = []
        start = 0.0
        for w in word_timings:
            word = str(w.get("word", "")).strip()
            if not word:
                continue
            if not cur:
                start = float(w.get("start", 0.0))
            cand = " ".join(cur + [word])
            if len(cand) > max_chars and cur:
                lines.append({"text": " ".join(cur), "start": start, "end": float(w.get("start", 0.0))})
                cur = [word]
                start = float(w.get("start", 0.0))
            else:
                cur.append(word)
        if cur:
            lines.append({"text": " ".join(cur), "start": start,
                          "end": float(word_timings[-1].get("end", start + 2.0)) if word_timings else start + 2.0})
        return lines

    def composite(self, frame: np.ndarray, t: float, lines: List[Dict[str, Any]],
                  state: Dict[str, float]) -> np.ndarray:
        """
        Funde el HUD sobre el cuadro uint8 in situ.

        Solo se tocan las franjas superior e inferior (el resto no tiene HUD) y
        todo se resuelve con alfa premultiplicado, sin convertir el cuadro a float.
        """
        f = frame
        k = self.k

        # 1. Capa estatica: dst = dst*(1-a) + rgb*a  (ambos terminos ya en uint8)
        for y0, y1 in ((0, self.top_h), (self.bot_y, self.h)):
            reg = f[y0:y1]
            cv2.multiply(reg, self._static_inv[y0:y1], dst=reg, scale=1.0 / 255.0)
            cv2.add(reg, self._static_pm[y0:y1], dst=reg)

        # 2. Subtitulo activo
        line = None
        for L in lines:
            if L["start"] <= t <= L["end"]:
                line = L["text"]
                break
        if line:
            pm, inv = self._subtitle_img(line)
            y0 = int(self.h - 560 * k)
            y1 = min(self.h, y0 + pm.shape[0])
            reg = f[y0:y1]
            cv2.multiply(reg, inv[: y1 - y0], dst=reg, scale=1.0 / 255.0)
            cv2.add(reg, pm[: y1 - y0], dst=reg)

        # 3. Espectro vocal y barra de progreso (dibujo directo sobre uint8)
        energy = float(state.get("energy", 0.0))
        mouth = float(state.get("mouth_open", 0.0))
        bars, bw = 64, max(2, int(self.w * 0.010))
        x0 = int(self.w * 0.5 - (bars * bw * 1.55) / 2)
        base_y = int(self.h - 200 * k)
        for i in range(bars):
            ph = t * 9.0 + i * 0.41
            amp = (0.22 + 0.78 * abs(math.sin(ph))) * (0.18 + 0.82 * max(mouth, energy * 0.6))
            bh = int(amp * 88 * k)
            if bh < 2:
                continue
            x = x0 + int(i * bw * 1.55)
            sh = 0.45 + 0.55 * amp
            cv2.rectangle(f, (x, base_y - bh), (x + bw, base_y),
                          (0, int(212 * sh), int(200 * sh)), -1)

        prog = float(state.get("progress", 0.0))
        py = int(self.h - 46 * k)
        th = max(2, int(8 * k))
        cv2.rectangle(f, (int(100 * k), py), (self.w - int(100 * k), py + th), (14, 34, 44), -1)
        cv2.rectangle(f, (int(100 * k), py),
                      (int(100 * k) + int((self.w - 200 * k) * prog), py + th), (0, 212, 200), -1)

        return f


# --------------------------------------------------------------- codificacion
def _nvenc_available(width: int = 1920, height: int = 1080) -> bool:
    """
    Verifica que NVENC funcione A LA RESOLUCION OBJETIVO.

    El sondeo debe hacerse al tamano real: la GPU comparte VRAM con el modelo
    neural residente (llama-server), asi que NVENC puede funcionar en HD y
    quedarse sin memoria en UHD. En ese caso se degrada a libx264 por CPU.
    """
    if not shutil.which("ffmpeg"):
        return False
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", f"color=c=black:s={width}x{height}:d=0.2:r=30",
             "-c:v", "h264_nvenc", "-pix_fmt", "yuv420p", "-f", "null", "-"],
            capture_output=True, timeout=40
        )
        err = (r.stderr or b"").decode(errors="ignore").lower()
        if r.returncode != 0 or "cannot allocate memory" in err or "could not open encoder" in err:
            return False
        return True
    except Exception:
        return False


_VAAPI_CACHE: Dict[Tuple[int, int], Optional[str]] = {}


def _vaapi_device(width: int, height: int) -> Optional[str]:
    """
    Nodo DRI de una GPU AMD/Intel capaz de codificar H.264 por VAAPI a esta resolucion.

    En este equipo la Radeon integrada queda ociosa: codifica 4K60 a ~85 cuadros/s
    sin usar CPU ni la VRAM de la NVIDIA, que ocupa el modelo neural.
    """
    key = (width, height)
    if key in _VAAPI_CACHE:
        return _VAAPI_CACHE[key]
    found = None
    for node in sorted(Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").exists() else []:
        try:
            drv = Path(f"/sys/class/drm/{node.name}/device/driver").resolve().name
        except Exception:
            drv = ""
        if drv not in ("amdgpu", "i915", "xe", "radeon"):
            continue
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-vaapi_device", str(node),
                 "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:d=0.2:r=30",
                 "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-f", "null", "-"],
                capture_output=True, timeout=30)
            if r.returncode == 0:
                found = str(node)
                break
        except Exception:
            continue
    _VAAPI_CACHE[key] = found
    return found


def _video_encoder_args(bitrate_kbps: int, use_nvenc: bool, threads: int = 2,
                        vaapi_device: Optional[str] = None) -> List[str]:
    maxrate = int(bitrate_kbps * 1.35)
    if vaapi_device:
        return [
            "-vf", "format=nv12,hwupload",
            "-c:v", "h264_vaapi", "-profile:v", "high",
            "-b:v", f"{bitrate_kbps}k", "-maxrate", f"{maxrate}k",
            "-bufsize", f"{maxrate * 2}k", "-g", "120",
        ]
    if use_nvenc:
        return [
            "-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq",
            "-rc", "vbr", "-cq", "23",
            "-b:v", f"{bitrate_kbps}k", "-maxrate", f"{maxrate}k",
            "-bufsize", f"{maxrate * 2}k",
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-g", "120",
        ]
    return [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-maxrate", f"{maxrate}k", "-bufsize", f"{maxrate * 2}k",
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-g", "120",
        "-threads", str(threads),
    ]


# ----------------------------------------------------------- render segmentado
def _render_segment(args: Dict[str, Any]) -> Dict[str, Any]:
    """Renderiza y codifica un tramo de cuadros. Ejecutado en un proceso propio."""
    import sys
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from core.character_3d_renderer import get_character_3d_renderer

    w, h = args["width"], args["height"]
    fps = args["fps"]
    f0, n = args["frame_start"], args["frame_count"]
    out_path = args["out_path"]

    renderer = get_character_3d_renderer(args["quality"])
    hud = HudRenderer(w, h, args["title"]) if args["hud"] else None
    lines = args["lines"]
    wt = args["word_timings"]
    duration = args["duration"]

    cmd = (["ffmpeg", "-y", "-loglevel", "error"] + list(args.get("pre_input", [])) +
           ["-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{w}x{h}", "-pix_fmt", "rgb24", "-r", str(fps), "-i", "-"]
           + args["enc_args"] + ["-an", out_path])

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for i in range(n):
            idx = f0 + i
            t = idx / float(fps)
            st = compute_vocal_state(t, wt, duration)
            img = renderer.render_frame(t, w, h, st, char_scale=args["char_scale"],
                                        center=args["center"])
            frame = renderer.post_process(
                img, bloom=args["bloom"], vignette=0.0, grain=0.0, seed=idx
            )
            if hud is not None:
                frame = hud.composite(frame, t, lines, st)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        _, err = proc.communicate(timeout=300)
        if proc.returncode != 0:
            return {"ok": False, "error": (err or b"").decode(errors="ignore")[-300:], "seg": args["seg"]}
    except Exception as e:
        try:
            proc.kill()
        except Exception:
            pass
        return {"ok": False, "error": str(e), "seg": args["seg"]}

    return {"ok": True, "seg": args["seg"], "path": out_path, "frames": n}


def render_video_4k(
    audio_path: str | Path,
    word_timings: List[Dict[str, Any]],
    duration: float,
    output_path: str | Path,
    width: int = 3840,
    height: int = 2160,
    fps: int = 60,
    title: str = "TARDIS · MENSAJE SOBERANO",
    quality: str = "high",
    hud: bool = True,
    char_scale: float = 0.86,
    center: Tuple[float, float] = (0.5, 0.40),
    bloom: float = 0.55,
    workers: Optional[int] = None,
    max_bytes: int = TELEGRAM_MAX_BYTES,
) -> Dict[str, Any]:
    """
    Renderiza el videomensaje completo del personaje 3D y lo multiplexa con el audio.
    Reparte los cuadros entre procesos y codifica cada tramo en paralelo.
    """
    import time as _time
    t0 = _time.time()

    audio_path = str(audio_path)
    output_path = Path(output_path)
    total_frames = max(1, int(round(duration * fps)))

    if workers is None:
        workers = max(1, min(10, (os.cpu_count() or 4) - 2))
    workers = max(1, min(workers, total_frames))

    # Presupuesto de tasa de bits para respetar el limite de subida
    audio_kbps = 192
    budget_kbps = int((max_bytes * 8 / 1000.0) / max(1.0, duration)) - audio_kbps
    # ~0.075 bits por pixel: adecuado para H.264 en contenido oscuro y de poco movimiento
    px_kbps = min(32000, int(width * height * fps * 0.075 / 1000))
    bitrate_kbps = max(2500, min(px_kbps, budget_kbps if budget_kbps > 0 else px_kbps))

    # NVENC solo se usa cuando hay un unico segmento. La GPU comparte VRAM con el
    # modelo neural residente (llama-server ocupa ~3.3 GB de 4 GB), asi que varias
    # sesiones NVENC simultaneas fallan con "out of memory". Con varios segmentos se
    # codifica con libx264, que escala bien entre nucleos y no toca la VRAM.
    vaapi = _vaapi_device(width, height)
    use_nvenc = (vaapi is None) and (workers == 1) and _nvenc_available(width, height)
    enc_args = _video_encoder_args(bitrate_kbps, use_nvenc, threads=max(1, 16 // max(1, workers)),
                                   vaapi_device=vaapi)
    pre_input = ["-vaapi_device", vaapi] if vaapi else []
    if vaapi:
        # El codificador por hardware llena todo el bitrate pedido (x264 en modo calidad
        # no). Con este contenido oscuro y de poco movimiento, 16 Mbps bastan en 4K60.
        bitrate_kbps = min(bitrate_kbps, 16000)
        enc_args = _video_encoder_args(bitrate_kbps, False, vaapi_device=vaapi)
    encoder_name = "h264_vaapi" if vaapi else ("h264_nvenc" if use_nvenc else "libx264")

    lines = HudRenderer.build_lines(word_timings) if hud else []

    tmpdir = Path(tempfile.mkdtemp(prefix="tardis4k_"))
    try:
        per = math.ceil(total_frames / workers)
        jobs = []
        for s in range(workers):
            f0 = s * per
            if f0 >= total_frames:
                break
            n = min(per, total_frames - f0)
            jobs.append({
                "seg": s, "frame_start": f0, "frame_count": n,
                "width": width, "height": height, "fps": fps,
                "duration": duration, "word_timings": word_timings, "lines": lines,
                "title": title, "quality": quality, "hud": hud,
                "char_scale": char_scale, "center": center, "bloom": bloom,
                "enc_args": enc_args,
                "pre_input": pre_input,
                "out_path": str(tmpdir / f"seg_{s:03d}.mp4"),
            })

        # Cada segmento corre en un proceso Python limpio e independiente.
        # Se evita multiprocessing a proposito: el proceso anfitrion (TARDIS)
        # tiene decenas de hilos vivos y un fork/forkserver seria fragil.
        import json as _json
        py = sys.executable or "python3"
        procs = []
        for j in jobs:
            jf = tmpdir / f"job_{j['seg']:03d}.json"
            jf.write_text(_json.dumps(j), encoding="utf-8")
            procs.append((j, jf, subprocess.Popen(
                [py, str(Path(__file__).resolve()), "--job", str(jf)],
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )))

        results = []
        for j, jf, pr in procs:
            out, err = pr.communicate(timeout=1800)
            if pr.returncode != 0:
                results.append({"ok": False, "seg": j["seg"],
                                "error": (err or b"").decode(errors="ignore")[-300:]})
                continue
            try:
                results.append(_json.loads((out or b"{}").decode(errors="ignore").strip().splitlines()[-1]))
            except Exception as e:
                results.append({"ok": False, "seg": j["seg"], "error": f"respuesta ilegible: {e}"})

        failed = [r for r in results if not r.get("ok")]
        if failed:
            return {"ok": False, "error": f"Fallo en segmento {failed[0].get('seg')}: {failed[0].get('error')}"}

        results.sort(key=lambda r: r["seg"])

        # Concatenacion sin recodificar + multiplexado del audio
        listfile = tmpdir / "segments.txt"
        listfile.write_text("".join(f"file '{r['path']}'\n" for r in results), encoding="utf-8")

        mux = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(listfile),
            "-i", audio_path,
            "-c:v", "copy", "-c:a", "aac", "-b:a", f"{audio_kbps}k",
            "-shortest", "-movflags", "+faststart",
            str(output_path),
        ]
        r = subprocess.run(mux, capture_output=True, timeout=300)
        if r.returncode != 0 or not output_path.exists():
            return {"ok": False, "error": f"Multiplexado fallido: {r.stderr.decode(errors='ignore')[-300:]}"}

        size = output_path.stat().st_size
        return {
            "ok": True,
            "path": str(output_path),
            "size": size,
            "width": width, "height": height, "fps": fps,
            "duration": duration,
            "frames": total_frames,
            "workers": len(jobs),
            "encoder": encoder_name,
            "bitrate_kbps": bitrate_kbps,
            "elapsed_s": round(_time.time() - t0, 2),
            "over_limit": size > max_bytes,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ------------------------------------------------------- entrada de subproceso
if __name__ == "__main__":
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(description="Renderizador de segmento de video 4K de TARDIS")
    ap.add_argument("--job", required=True, help="Ruta al archivo JSON con la descripcion del tramo")
    a = ap.parse_args()

    job = _json.loads(Path(a.job).read_text(encoding="utf-8"))
    job["center"] = tuple(job.get("center", (0.5, 0.47)))
    print(_json.dumps(_render_segment(job)))
