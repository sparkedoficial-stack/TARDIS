#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_tardis_boot_animation.py - Genera la animación de arranque Plymouth de TARDIS
==================================================================================
Reutiliza EXACTAMENTE el dibujo del chat (`renderVectorTriangularCharacter` de index.html)
capturando sus operaciones de canvas con un contexto falso, y las convierte en los
primitivos de Plymouth Script (draw_image, path, arc, stroke, fill, clip).

Salida (por defecto ./plymouth-tardis):
  tardis.script, tardis.plymouth, *.png (personaje por fase + texto), assets,
  tardis-boot-animation.mp4 (previsualización en vídeo, si hay ffmpeg).

El escenario reproduce el bucle del chat (levitación, respiración, ondas, parpadeo,
mirada con sacadas), con una única diferencia: no hay entrada de usuario que mirar,
así que la mirada se genera con una semilla fija para que el arranque sea reproducible.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

BASE = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM")
INDEX = BASE / "index.html"

SCREEN_W, SCREEN_H = 1920, 1080
FPS = 25
FRAMES = 75                      # 3 s de bucle
CHAR_SIZE = 560
CHAR_CX = SCREEN_W // 2
CHAR_CY = int(SCREEN_H * 0.42)
LABEL = "Cargando máquina del tiempo"


# ----------------------------------------------------------------------------
# 1. Extracción del dibujo real desde el chat
# ----------------------------------------------------------------------------
def extract_character_js() -> str:
    src = INDEX.read_text(encoding="utf-8")
    start = src.find("function renderVectorTriangularCharacter")
    if start < 0:
        raise SystemExit("No se encontró renderVectorTriangularCharacter en index.html")
    end = src.find("\n        function ", start + 10)
    body = src[start:end]
    # El cuerpo asigna window.renderVectorTriangularCharacter al final del archivo: no aplica aquí.
    return body.strip()


def _add_stop(self, offset, color):
    self["stops"].append([float(offset), color])


class FakeCtx:
    """Contexto 2D falso que graba las operaciones del personaje."""

    def __init__(self):
        self.ops: list[dict[str, Any]] = []
        self.stack: list[dict[str, Any]] = []
        self.state = {"fillStyle": "#000", "strokeStyle": "#000", "lineWidth": 1,
                      "globalAlpha": 1.0, "shadowBlur": 0, "shadowColor": "#000",
                      "lineJoin": "miter"}
        self._path: list[dict[str, Any]] = []
        self._transform = [1, 0, 0, 1, 0, 0]   # a b c d e f

    # --- primitivas ---
    def save(self): self.stack.append(dict(self.state))
    def restore(self):
        if self.stack: self.state = self.stack.pop()
    def beginPath(self): self._path = []
    def closePath(self): self._path.append({"t": "close"})
    def moveTo(self, x, y): self._path.append({"t": "move", "x": x, "y": y})
    def lineTo(self, x, y): self._path.append({"t": "line", "x": x, "y": y})
    def quadraticCurveTo(self, cx, cy, x, y): self._path.append({"t": "quad", "cx": cx, "cy": cy, "x": x, "y": y})
    def arc(self, x, y, r, a0=0, a1=0, ccw=False): self._path.append({"t": "arc", "x": x, "y": y, "r": r, "a0": a0, "a1": a1})
    def setLineDash(self, arr): self.state["dash"] = [float(v) for v in (arr or [])]
    def translate(self, x, y):
        a, b, c, d, e, f = self._transform
        self._transform = [a, b, c, d, e + a * x + c * y, f + b * x + d * y]
    def rotate(self, ang):
        a, b, c, d, e, f = self._transform
        ca, sa = math.cos(ang), math.sin(ang)
        self._transform = [a * ca + c * sa, b * ca + d * sa, -a * sa + c * ca, -b * sa + d * ca, e, f]
    def scale(self, sx, sy=None):
        sy = sx if sy is None else sy
        a, b, c, d, e, f = self._transform
        self._transform = [a * sx, b * sx, c * sy, d * sy, e, f]
    def createRadialGradient(self, x0, y0, r0, x1, y1, r1):
        return {"stops": [], "geom": [x0, y0, r0, x1, y1, r1],
                "addColorStop": _add_stop}
    def _emit(self, kind):
        self.ops.append({"kind": kind, "path": list(self._path), "state": dict(self.state),
                         "transform": list(self._transform)})
    def stroke(self): self._emit("stroke")
    def fill(self): self._emit("fill")
    def clip(self): self._emit("clip")

    # --- estilos (asignaciones) ---
    def __setattr__(self, name, value):
        if name in ("fillStyle", "strokeStyle", "lineWidth", "globalAlpha", "shadowBlur",
                    "shadowColor", "lineJoin"):
            if name in self.__dict__.get("state", {}):
                self.state[name] = value
                return
        object.__setattr__(self, name, value)


_JS_PROLOGUE = r"""
const window = { renderVectorTriangularCharacter: null };
const performance = { now: () => __T__ * 1000 };
function rgba(r, g, b, a) { return `rgba(${r}, ${g}, ${b}, ${a})`; }
"""

_JS_EPILOGUE = r"""
renderVectorTriangularCharacter(ctx, __CX__, __CY__, __SIZE__, {
    time: __T__, dt: 1/__FPS__, state: 'idle',
    eyeLookX: __LOOKX__, eyeLookY: __LOOKY__, blinkVal: __BLINK__,
    glow: 1.0, audioLevel: 0, isBackground: true
});
"""


def capture_frame(js_body: str, t: float, look_x: float, look_y: float, blink: float) -> list[dict]:
    script = (
        _JS_PROLOGUE
        + "\nconst ctx = new FakeCtxProxy();\n"
        + js_body
        + _JS_EPILOGUE.replace("__T__", repr(t)).replace("__CX__", str(CHAR_CX)).replace("__CY__", str(CHAR_CY))
        .replace("__SIZE__", str(CHAR_SIZE)).replace("__FPS__", str(FPS))
        .replace("__LOOKX__", repr(look_x)).replace("__LOOKY__", repr(look_y)).replace("__BLINK__", repr(blink))
        + "\nconsole.log(JSON.stringify(ctx.ops));\n"
    )
    node = shutil.which("node")
    if not node:
        raise SystemExit("Se necesita node para ejecutar el dibujo real del personaje")
    harness = r"""
const fs = require('fs');
class Grad { constructor(g){ this.stops=[]; this.geom=g||null; } addColorStop(o,c){ this.stops.push([o,c]); } }
class FakeCtxProxy {
  constructor(){ this.ops=[]; this.stack=[]; this.state={fillStyle:'#000',strokeStyle:'#000',lineWidth:1,globalAlpha:1,shadowBlur:0,shadowColor:'#000',lineJoin:'miter',dash:[]}; this._path=[]; this._m=[1,0,0,1,0,0]; }
  save(){ this.stack.push({...this.state}); }
  restore(){ if(this.stack.length) this.state=this.stack.pop(); }
  beginPath(){ this._path=[]; }
  closePath(){ this._path.push({t:'close'}); }
  moveTo(x,y){ this._path.push({t:'move',x,y}); }
  lineTo(x,y){ this._path.push({t:'line',x,y}); }
  quadraticCurveTo(cx,cy,x,y){ this._path.push({t:'quad',cx,cy,x,y}); }
  arc(x,y,r,a0,a1){ this._path.push({t:'arc',x,y,r,a0,a1}); }
  setLineDash(a){ this.state.dash=a||[]; }
  translate(x,y){ const m=this._m; m[4]+=m[0]*x+m[2]*y; m[5]+=m[1]*x+m[3]*y; }
  rotate(a){ const m=this._m, c=Math.cos(a), s=Math.sin(a); const [a0,b0,c0,d0]=m; m[0]=a0*c+c0*s; m[1]=b0*c+d0*s; m[2]=-a0*s+c0*c; m[3]=-b0*s+d0*c; }
  scale(sx,sy){ const m=this._m; sy=(sy===undefined)?sx:sy; m[0]*=sx; m[1]*=sx; m[2]*=sy; m[3]*=sy; }
  createRadialGradient(x0,y0,r0,x1,y1,r1){ return new Grad([x0,y0,r0,x1,y1,r1]); }
  _emit(kind){ this.ops.push({kind,path:this._path,state:{...this.state},transform:[...this._m]}); }
  stroke(){ this._emit('stroke'); } fill(){ this._emit('fill'); } clip(){ this._emit('clip'); }
}
for (const k of ['fillStyle','strokeStyle','lineWidth','globalAlpha','shadowBlur','shadowColor','lineJoin']) {
  Object.defineProperty(FakeCtxProxy.prototype, k, {
    get(){ return this.state[k]; }, set(v){ this.state[k]=v; }
  });
}
"""
    path = Path("/tmp/_tardis_boot_capture.js")
    path.write_text(harness + script, encoding="utf-8")
    out = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-800:])
    return json.loads(out.stdout)


# ----------------------------------------------------------------------------
# 2. Conversión a primitivos de Plymouth Script
# ----------------------------------------------------------------------------
def fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def emit_plymouth(ops: list[dict], frame_idx: int, assets: dict[str, dict]) -> list[str]:
    """Traduce las operaciones del personaje a primitivas de Plymouth Script."""
    lines: list[str] = []
    for op in ops:
        st, tr = op["state"], op["transform"]
        a, b, c, d, e, f = tr
        if op["path"]:
            lines.append("    path();")
            for seg in op["path"]:
                if seg["t"] == "move":
                    lines.append(f"    move_to({fmt(seg['x'] * a + seg['y'] * c + e)}, {fmt(seg['x'] * b + seg['y'] * d + f)});")
                elif seg["t"] == "line":
                    lines.append(f"    line_to({fmt(seg['x'] * a + seg['y'] * c + e)}, {fmt(seg['x'] * b + seg['y'] * d + f)});")
                elif seg["t"] == "quad":
                    cx, cy = seg["cx"] * a + seg["cy"] * c + e, seg["cx"] * b + seg["cy"] * d + f
                    x, y = seg["x"] * a + seg["y"] * c + e, seg["x"] * b + seg["y"] * d + f
                    lines.append(f"    curve_to({fmt(cx)}, {fmt(cy)}, {fmt(cx)}, {fmt(cy)}, {fmt(x)}, {fmt(y)});")
                elif seg["t"] == "arc":
                    n = 18
                    for i in range(n + 1):
                        ang = seg["a0"] + (seg["a1"] - seg["a0"]) * i / n
                        px = seg["x"] + math.cos(ang) * seg["r"]
                        py = seg["y"] + math.sin(ang) * seg["r"]
                        x, y = px * a + py * c + e, px * b + py * d + f
                        lines.append(f"    {'move_to' if i == 0 else 'line_to'}({fmt(x)}, {fmt(y)});")
                elif seg["t"] == "close":
                    lines.append("    close();")
        if op["kind"] == "clip":
            lines.append("    clip();")
            continue
        raw = op["kind"] == "stroke"
        style = st.get("strokeStyle" if raw else "fillStyle")
        alpha = float(st.get("globalAlpha", 1.0) or 1.0)
        width = float(st.get("lineWidth", 1) or 1) * max(0.2, math.hypot(a, b))
        width = float(min(4, max(1, int(round(width)))))
        key = None
        if isinstance(style, dict) and "stops" in style:
            key = _register(assets, {"kind": "grad", "stops": style["stops"],
                                     "geom": style.get("geom"), "width": width, "raw": raw})
        elif isinstance(style, str) and style.startswith("rgba"):
            m = re.match(r"rgba\(([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)\)", style)
            if m:
                r, g, bl, al = (float(v) for v in m.groups())
                key = _register(assets, {"kind": "solid", "rgb": (r, g, bl), "alpha": round(min(1.0, al * alpha) * 100) / 100,
                                         "width": width, "raw": raw})
        elif isinstance(style, str) and style.startswith("#") and len(style) == 7:
            rgb = tuple(int(style[i:i + 2], 16) for i in (1, 3, 5))
            key = _register(assets, {"kind": "solid", "rgb": rgb, "alpha": round(min(1.0, alpha) * 100) / 100,
                                     "width": width, "raw": raw})
        if key:
            lines.append(f"    {'draw_image' if raw else 'fill_image'}({key});" if raw
                         else f"    fill_image({key});")
    return lines


_ASSETS: dict[str, dict] = {}


def _register(assets: dict[str, dict], spec: dict) -> str:
    import hashlib
    geom = spec.get("geom") or ()
    q = dict(spec)
    if spec["kind"] == "solid":
        q["alpha"] = round(spec["alpha"], 2)
        q["width"] = int(round(spec["width"]))
    q["geom"] = [round(float(v), 1) for v in geom] if geom else None
    q["stops"] = [[round(float(o), 2), c] for o, c in spec.get("stops", [])]
    sig = json.dumps(q, sort_keys=True, default=str)
    key = "a" + hashlib.sha1(sig.encode()).hexdigest()[:10]
    assets[key] = spec
    return key


def _solid_asset(assets: dict, rgb, alpha: float, kind: str):
    key = f"solid_{rgb[0]}_{rgb[1]}_{rgb[2]}_{round(alpha,2)}_{kind}"
    if key in assets:
        return key, assets[key]
    assets[key] = key
    return key, key


def _gradient_asset(assets, rgb, level: str, kind: str, st):
    key = f"rgba_{rgb[0]}_{rgb[1]}_{rgb[2]}_{level}_{kind}"
    assets[key] = {"rgb": rgb, "alpha": float(level), "kind": kind, "lineWidth": st.get("lineWidth", 1)}
    return key, key


def _build_text_frames(assets_dir: Path, text: str, font) -> list[str]:
    """Un PNG por letra, en orden, con la posición acumulada codificada en el nombre."""
    from PIL import Image, ImageDraw
    assets_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    asc, desc = font.getmetrics()
    x = 0
    for ch in text:
        if ch == " ":
            x += int(font.getlength(" ") + 1) if hasattr(font, "getlength") else 14
            continue
        w = int(font.getlength(ch)) + 8 if hasattr(font, "getlength") else 20
        img = Image.new("RGBA", (w, asc + desc), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((2, 0), ch, font=font, fill=(205, 245, 245, 255))
        x = int(x)
        name = f"txt_{x:04d}.png"
        img.save(assets_dir / name)
        names.append(name)
        w = int(w)
        x += w
    return names


def _render_gradient_asset(path: Path, spec: dict) -> Path:
    from PIL import Image
    geom = spec.get("geom") or (0, 0, 0, 1, 1, 120)
    x0, y0, r0, x1, y1, r1 = geom
    size = max(8, min(96, int(r1 * 2)))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    cx, cy = size / 2, size / 2
    stops = sorted(spec["stops"], key=lambda s: s[0]) or [(0, "rgba(0,0,0,0)"), (1, "rgba(0,0,0,0)")]
    def parse(c):
        m = re.match(r"rgba\(([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)\)", c)
        if m:
            return tuple(float(v) for v in m.groups())
        if c.startswith("#") and len(c) == 7:
            return (*[int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)], 1.0)
        return (0.0, 0.0, 0.0, 0.0)
    for yy in range(size):
        for xx in range(size):
            k = min(1.0, math.hypot(xx - cx, yy - cy) / max(1.0, cx))
            lo = max([s for s in stops if s[0] <= k], default=stops[0])
            hi = min([s for s in stops if s[0] >= k], default=stops[-1])
            span = max(1e-6, hi[0] - lo[0])
            f = (k - lo[0]) / span
            a, b = parse(lo[1]), parse(hi[1])
            col = tuple(int(255 * (a[i] + (b[i] - a[i]) * f)) for i in range(3))
            px[xx, yy] = (*col, int(255 * (a[3] + (b[3] - a[3]) * f)))
    img.save(path)
    return path


def build(theme_dir: Path, preview_dir: Path | None = None) -> dict:
    theme_dir.mkdir(parents=True, exist_ok=True)
    (theme_dir / "assets").mkdir(exist_ok=True)
    js_body = extract_character_js()

    # Secuencia de estados: mirada con sacadas y parpadeo (semilla fija => reproducible).
    rng = random.Random(20261026)
    look_x, look_y, blink = 0.0, 0.0, 0.0
    tgt_x, tgt_y = 0.0, 0.0
    blink_timer, next_blink = 2.6, 2.6
    seq = []
    dt = 1.0 / FPS
    for i in range(FRAMES):
        t = i * dt
        if t >= next_blink:
            blink = min(1.0, (t - next_blink) / 0.18)
        else:
            blink = 0.0
        if i and i % 18 == 0:
            tgt_x, tgt_y = (rng.random() - 0.5) * 0.45, (rng.random() - 0.5) * 0.3
            next_blink = t + 2.5 + rng.random() * 2.0
        look_x += (tgt_x - look_x) * min(1, dt * 9)
        look_y += (tgt_y - look_y) * min(1, dt * 9)
        seq.append((t, look_x, look_y, blink))

    frames_script: list[str] = []
    assets: dict[str, Any] = {}
    total_ops = 0
    for idx, (t, lx, ly, bl) in enumerate(seq):
        ops = capture_frame(js_body, t, lx, ly, bl)
        total_ops += len(ops)
        lines = emit_plymouth(ops, idx, assets)
        frames_script.append(f"fun frame_{idx}() {{\n" + "\n".join(lines) + "\n}\n")

    # Texto: Plymouth no rasteriza fuentes, así que se generan PNG por letra y se animan como Morph.
    from PIL import ImageFont
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font = ImageFont.truetype(font_path, 46) if Path(font_path).exists() else ImageFont.load_default()
    label_assets = _build_text_frames(theme_dir / "assets", LABEL, font)

    header = f"""# tardis.plymouth - Arranque TARDIS generado desde index.html
# No editar a mano: regenerar con tools/build_tardis_boot_animation.py
screen_width = {SCREEN_W};
screen_height = {SCREEN_H};
screen_fps = {FPS};
frames_total = {FRAMES};

Window.SetBackgroundTopColor(0.012, 0.028, 0.055);
Window.SetBackgroundBottomColor(0.004, 0.008, 0.016);


# Bitmaps de color plano (relleno / trazo) usados por los caminos del personaje.
"""
    body = []
    for key, spec in assets.items():
        if spec["kind"] == "solid":
            r, g, b = (int(round(x)) for x in spec["rgb"])
            w = max(1, int(round(spec["width"])))
            png = theme_dir / "assets" / f"{key}.png"
            from PIL import Image as _I
            _I.new("RGBA", (w, 1), (r, g, b, int(round(255 * spec["alpha"])))).save(png)
            body.append(f'{key} = Image("assets/{key}.png");')
        else:
            png = _render_gradient_asset(theme_dir / "assets" / f"{key}.png", spec)
            body.append(f'{key} = Image("assets/{key}.png");')
    body.append("")
    morph_frames = ",\n    ".join(f"frame_{i}" for i in range(FRAMES))
    label_frames = ",\n    ".join(f"label_{i}" for i in range(len(label_assets)))
    script = header + "\n".join(body) + "\n" + "\n".join(frames_script) + f"""
character = Morph(
    {morph_frames}
);
character.SetPosition(0, 0);

label = Morph(
    {label_frames}
);
label.SetPosition({SCREEN_W // 2 - 700}, {int(SCREEN_H * 0.80)});

# Bucle: 3 s a 25 fps. La etiqueta late al mismo ritmo que el personaje respira.
loop_count = 0;
fun refresh_callback() {{
    tick = Math.Int(loop_count * screen_fps);
    character.SetFrame(tick % frames_total);
    label.SetFrame(Math.Int(tick / 3) % {len(label_assets)});
    loop_count += 0.04;
}}
Plymouth.SetRefreshFunction(refresh_callback);

# Plymouth puede pedir mensajes (fsck, cifrado): se muestran encima y sin tapar la animación.
fun display_message(text, sprite) {{ }}
fun display_normal(text) {{ }}
Plymouth.SetDisplayMessageFunction(display_message);
Plymouth.SetDisplayPasswordFunction(display_message);
Plymouth.SetDisplayQuestionFunction(display_message);
Plymouth.SetBootProgressFunction(fun (a, b) {{ }});
"""
    (theme_dir / "tardis.script").write_text(script, encoding="utf-8")
    (theme_dir / "tardis.plymouth").write_text(
        "[Plymouth Theme]\nName=TARDIS\nDescription=Arranque TARDIS con el personaje del chat\n"
        "ModuleName=script\n\n[script]\nImageDir=/usr/share/plymouth/themes/tardis\n"
        "ScriptFile=/usr/share/plymouth/themes/tardis/tardis.script\n", encoding="utf-8")

    # Previsualización en vídeo del mismo bucle.
    if preview_dir:
        preview_dir.mkdir(parents=True, exist_ok=True)
        _render_preview(preview_dir / "tardis-boot-animation.mp4", seq, js_body, label_assets)
    return {"frames": FRAMES, "ops_total": total_ops, "assets": len(assets), "theme": str(theme_dir)}


def _hex(c: str):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def _render_preview(out: Path, seq, js_body: str, label_assets) -> None:
    from PIL import Image, ImageDraw, ImageFilter
    ffmpeg = shutil.which("ffmpeg")
    tmp = Path("/tmp/_tardis_boot_frames")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    label = None
    _label_dir = Path(out).parent.parent / "plymouth-tardis" / "assets"
    for idx, (t, lx, ly, bl) in enumerate(seq):
        ops = capture_frame(js_body, t, lx, ly, bl)
        canvas = Image.new("RGBA", (SCREEN_W, SCREEN_H), (5, 9, 20, 255))
        d = ImageDraw.Draw(canvas)
        for y in range(SCREEN_H):  # degradado vertical
            k = y / SCREEN_H
            d.line([(0, y), (SCREEN_W, y)], fill=(int(8 - 6 * k), int(20 - 14 * k), int(40 - 28 * k), 255))
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        for op in ops:
            pts = []
            for seg in op["path"]:
                if seg["t"] in ("move", "line"):
                    pts.append((seg["x"], seg["y"]))
                elif seg["t"] == "quad":
                    pts.append((seg["x"], seg["y"]))
            if not pts:
                continue
            col = op["state"]["strokeStyle" if op["kind"] == "stroke" else "fillStyle"]
            if not isinstance(col, str) or not col.startswith("#"):
                continue
            rgb = _hex(col)
            alpha = int(255 * float(op["state"].get("globalAlpha", 1) or 1))
            if op["kind"] == "stroke":
                ld.line(pts, fill=rgb + (alpha,), width=max(1, int(float(op["state"].get("lineWidth", 1)))))
            elif len(pts) >= 3:
                ld.polygon(pts, fill=rgb + (alpha,))
        glow = layer.filter(ImageFilter.GaussianBlur(6))
        canvas.alpha_composite(glow)
        canvas.alpha_composite(layer)
        lab_frame = label_assets[(idx // 3) % len(label_assets)]
        lp = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM/plymouth-tardis/assets") / lab_frame
        lab = Image.open(lp).convert("RGBA") if lp.exists() else None
        start_x = int(re.search(r"txt_(\d+)", lab_frame).group(1))
        if lab is not None:
            a = int(255 * (0.72 + 0.28 * math.sin(idx * 0.04 * 1.6)))
            lab.putalpha(lab.getchannel("A").point(lambda v: v * a // 255))
            canvas.alpha_composite(lab, (SCREEN_W // 2 - 700 + start_x, int(SCREEN_H * 0.80)))
        canvas.convert("RGB").save(tmp / f"f{idx:04d}.png")
    if ffmpeg:
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(tmp / "f%04d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "scale=960:-1", str(out)], check=False)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BASE / "plymouth-tardis"))
    ap.add_argument("--preview", default="/tmp/tardis-boot-preview")
    a = ap.parse_args()
    print(json.dumps(build(Path(a.out), Path(a.preview)), ensure_ascii=False, indent=2))
