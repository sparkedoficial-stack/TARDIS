#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genera la animación de arranque Plymouth desde el bucle de la cabina (index.html)."""
from __future__ import annotations
import argparse, json, math, random, re, shutil, subprocess
from pathlib import Path
from typing import Any

BASE = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM")
INDEX = BASE / "index.html"
W, H = 1920, 1080
FPS, FRAMES = 25, 75
CHAR_CX, CHAR_CY, CHAR_SIZE = 960, 453, 560
LABEL, LABEL_SIZE = "Cargando máquina del tiempo", 44
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BG_TOP, BG_BOTTOM = (27, 40, 56), (14, 22, 33)
PSI, SINTROPY, S_GEOM, O_QCO, PHI_ADV = 0.892, 0.965, 1.57, 0.840, 0.780

def _extract(src, name):
    i = src.find(f"function {name}(")
    if i < 0: raise SystemExit(f"no {name}")
    j = src.find("\n        function ", i + 10)
    return src[i:j].rstrip()

def extract_scene_js():
    s = INDEX.read_text(encoding="utf-8")
    return "\n\n".join([_extract(s, "renderVectorTriangularCharacter"), _extract(s, "renderRetrocausalCone")])

HARNESS = r"""
class Grad { constructor(k,g){this.kind=k;this.geom=g;this.stops=[];} addColorStop(o,c){this.stops.push([o,c]);} }
class Ctx {
 constructor(){this.ops=[];this.state={fillStyle:'#000',strokeStyle:'#000',lineWidth:1,globalAlpha:1,shadowBlur:0,shadowColor:'#000',lineJoin:'miter',dash:[]};this._path=[];this._m=[1,0,0,1,0,0];this._stack=[];}
 save(){this._stack.push({...this.state});} restore(){if(this._stack.length)this.state=this._stack.pop();}
 beginPath(){this._path=[];} closePath(){this._path.push({t:'close'});}
 moveTo(x,y){this._path.push({t:'move',x,y});} lineTo(x,y){this._path.push({t:'line',x,y});}
 quadraticCurveTo(cx,cy,x,y){this._path.push({t:'quad',cx,cy,x,y});}
 arc(x,y,r,a0,a1){this._path.push({t:'arc',x,y,r,a0:a0||0,a1:(a1===undefined?a0:a1)});}
 ellipse(x,y,rx,ry,rot,a0,a1){const n=28,a0v=a0||0,a1v=(a1===undefined?a0v+Math.PI*2:a1),r=rot||0;
  for(let i=0;i<=n;i++){const a=a0v+(a1v-a0v)*i/n,px=Math.cos(a)*rx,py=Math.sin(a)*ry;
   this._path.push({t:(i===0?'move':'line'),x:x+px*Math.cos(r)-py*Math.sin(r),y:y+px*Math.sin(r)+py*Math.cos(r)});}}
 setLineDash(a){this.state.dash=a||[];}
 translate(x,y){const m=this._m;m[4]+=m[0]*x+m[2]*y;m[5]+=m[1]*x+m[3]*y;}
 rotate(a){const m=this._m,c=Math.cos(a),s=Math.sin(a);const [a0,b0,c0,d0]=m;m[0]=a0*c+c0*s;m[1]=b0*c+d0*s;m[2]=-a0*s+c0*c;m[3]=-b0*s+d0*c;}
 scale(sx,sy){const m=this._m;sy=(sy===undefined)?sx:sy;m[0]*=sx;m[1]*=sx;m[2]*=sy;m[3]*=sy;}
 createLinearGradient(x0,y0,x1,y1){return new Grad('linear',[x0,y0,x1,y1]);}
 createRadialGradient(x0,y0,r0,x1,y1,r1){return new Grad('radial',[x0,y0,r0,x1,y1,r1]);}
 _emit(k){this.ops.push({kind:k,path:this._path.map(s=>({...s})),state:{...this.state},transform:[...this._m]});}
 stroke(){this._emit('stroke');} fill(){this._emit('fill');} clip(){this._emit('clip');}
}
for (const k of ['fillStyle','strokeStyle','lineWidth','globalAlpha','shadowBlur','shadowColor','lineJoin'])
  Object.defineProperty(Ctx.prototype,k,{get(){return this.state[k];},set(v){this.state[k]=v;}});
const window={};
const W=__W__,H=__H__,ctx=new Ctx();
const GIA_STATE={psi:__PSI__,sintropy:__SINTROPY__,s_geom:__S_GEOM__,o_qco:__O_QCO__,phi_adv:__PHI_ADV__,coneActive:true,tachyons:__TACHYONS__};
const GIA_FACE={eyeLookX:__LOOKX__,eyeLookY:__LOOKY__,blinkProgress:__BLINK__,audioLevel:0,isListening:false,isThinking:false,isSpeaking:false};
__BODY__
renderRetrocausalCone(__NOW_MS__,__DT__);
renderVectorTriangularCharacter(ctx,__CX__,__CY__,__SIZE__,{time:__T__,dt:__DT__,state:'idle',eyeLookX:GIA_FACE.eyeLookX,eyeLookY:GIA_FACE.eyeLookY,blinkVal:GIA_FACE.blinkProgress,glow:Math.max(0.35,GIA_STATE.psi*1.4),audioLevel:0,isBackground:true});
console.log(JSON.stringify({ops:ctx.ops,tachyons:GIA_STATE.tachyons}));
"""

def capture(t, look, blink, tachyons, body):
    s = (HARNESS.replace("__W__", str(W)).replace("__H__", str(H)).replace("__PSI__", str(PSI))
         .replace("__SINTROPY__", str(SINTROPY)).replace("__S_GEOM__", str(S_GEOM))
         .replace("__O_QCO__", str(O_QCO)).replace("__PHI_ADV__", str(PHI_ADV))
         .replace("__TACHYONS__", json.dumps(tachyons)).replace("__LOOKX__", repr(look[0]))
         .replace("__LOOKY__", repr(look[1])).replace("__BLINK__", repr(blink)).replace("__BODY__", body)
         .replace("__NOW_MS__", repr(t*1000.0)).replace("__DT__", repr(1.0/FPS)).replace("__T__", repr(t))
         .replace("__CX__", str(CHAR_CX)).replace("__CY__", str(CHAR_CY)).replace("__SIZE__", str(CHAR_SIZE)))
    p = Path("/tmp/_tardis_boot_scene.js"); p.write_text(s, encoding="utf-8")
    r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=60)
    if r.returncode != 0: raise RuntimeError(r.stderr[-900:])
    return json.loads(r.stdout)

def _col(c, mul):
    if isinstance(c, str):
        if c.startswith("#") and len(c) == 7: return (int(c[1:3],16), int(c[3:5],16), int(c[5:7],16), int(255*mul))
        m = re.match(r"rgba\(([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)\)", c)
        if m:
            r,g,b,a = (float(v) for v in m.groups()); return (int(r), int(g), int(b), int(255*a*mul))
    if isinstance(c, dict) and c.get("stops"):
        for _, st in c["stops"]:
            v = _col(st, mul)
            if v: return v
    return None

def render_scene(cap, out):
    from PIL import Image, ImageDraw, ImageFilter
    base = Image.new("RGB", (W, H)); d = ImageDraw.Draw(base)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i]-BG_TOP[i])*k) for i in range(3)))
    canvas = base.convert("RGBA")
    fg = Image.new("RGBA", (W, H), (0,0,0,0)); fd = ImageDraw.Draw(fg)
    for op in cap["ops"]:
        a,b,c,dd,e,f2 = op["transform"]; pts = []
        for seg in op["path"]:
            if seg["t"] in ("move","line"):
                pts.append((seg["x"]*a+seg["y"]*c+e, seg["x"]*b+seg["y"]*dd+f2))
            elif seg["t"] == "quad":
                cx,cy = seg["cx"]*a+seg["cy"]*c+e, seg["cx"]*b+seg["cy"]*dd+f2
                x1,y1 = seg["x"]*a+seg["y"]*c+e, seg["x"]*b+seg["y"]*dd+f2
                p0 = pts[-1] if pts else (x1,y1)
                for i in range(1,9):
                    u=i/8; pts.append(((1-u)**2*p0[0]+2*(1-u)*u*cx+u*u*x1, (1-u)**2*p0[1]+2*(1-u)*u*cy+u*u*y1))
            elif seg["t"] == "arc":
                for i in range(21):
                    ang = seg["a0"]+(seg["a1"]-seg["a0"])*i/20
                    px,py = seg["x"]+math.cos(ang)*seg["r"], seg["y"]+math.sin(ang)*seg["r"]
                    pts.append((px*a+py*c+e, px*b+py*dd+f2))
        if not pts: continue
        style = op["state"]["strokeStyle" if op["kind"]=="stroke" else "fillStyle"]
        ga = float(op["state"].get("globalAlpha", 1) or 1)
        if op["kind"] == "stroke":
            col = _col(style, ga)
            if not col: continue
            wmax = max(1, int(round(float(op["state"].get("lineWidth",1))*max(0.5, math.hypot(a,b)))))
            fd.line(pts, fill=col, width=wmax, joint="curve")
        elif len(pts) >= 3:
            if isinstance(style, dict) and style.get("stops"):
                ys=[p[1] for p in pts]; xs=[p[0] for p in pts]
                y0,y1 = int(min(ys)), int(max(ys)); stops = sorted(style["stops"], key=lambda s:s[0])
                for yy in range(y0, max(y0+1,y1)):
                    frac = 1-(yy-y0)/max(1,y1-y0)
                    lo = max([s for s in stops if s[0]<=frac], default=stops[0])
                    col = _col(lo[1], ga)
                    if col: fd.line([(min(xs), yy),(max(xs), yy)], fill=col)
            else:
                col = _col(style, ga)
                if col: fd.polygon(pts, fill=col)
    canvas.alpha_composite(fg.filter(ImageFilter.GaussianBlur(4)))
    canvas.alpha_composite(fg)
    canvas.convert("RGB").save(out)

def render_label(out):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(FONT_PATH, LABEL_SIZE) if Path(FONT_PATH).exists() else ImageFont.load_default()
    box = ImageDraw.Draw(Image.new("RGBA",(8,8))).textbbox((0,0), LABEL, font=font)
    w,h = box[2]+80, box[3]+50
    img = Image.new("RGBA",(w,h),(0,0,0,0)); d = ImageDraw.Draw(img)
    for dx in (-2,-1,0,1,2):
        for dy in (-2,-1,0,1,2):
            if dx or dy: d.text((40+dx,25+dy), LABEL, font=font, fill=(0,212,200,70))
    d.text((40,25), LABEL, font=font, fill=(215,248,250,255))
    img.save(out); return img.size

fit_js = """
fun fit_scale() {
    sx = Window.GetWidth() / BASE_W;
    sy = Window.GetHeight() / BASE_H;
    if (sy < sx) { return sy; }
    return sx;
}
"""

def build(theme_dir, preview_dir=None):
    theme_dir.mkdir(parents=True, exist_ok=True)
    assets = theme_dir/"assets"
    if assets.exists(): shutil.rmtree(assets)
    assets.mkdir(parents=True)
    body = extract_scene_js(); rng = random.Random(20261026)
    tach = [{"u":rng.random()*2-1,"t":rng.random(),"w":0.5+rng.random()*0.9,"j":rng.random()*math.pi*2,
             "spd":0.7+rng.random()*0.6,"type":"teal" if rng.random()>0.35 else "gold"} for _ in range(80)]
    look=(0.0,0.0); blink=0.0; dt=1.0/FPS
    for i in range(FRAMES):
        t=i*dt; cap=capture(t, look, blink, tach, body); tach=cap["tachyons"]
        render_scene(cap, assets/f"f{i:03d}.png")
        blink = max(0.0, 1-abs(((t%3.2)-3.0))/0.18) if (t%3.2) > 2.85 else 0.0
        look = (math.sin(t*0.35)*0.18, math.sin(t*0.5)*0.10)
    lw, lh = render_label(assets/"label.png")
    script = fit_js + f"""# tardis.script - Arranque TARDIS animado (generado desde index.html)
BASE_W = {W};
BASE_H = {H};
frames_total = {FRAMES};

Window.SetBackgroundTopColor({BG_TOP[0]/255:.3f}, {BG_TOP[1]/255:.3f}, {BG_TOP[2]/255:.3f});
Window.SetBackgroundBottomColor({BG_BOTTOM[0]/255:.3f}, {BG_BOTTOM[1]/255:.3f}, {BG_BOTTOM[2]/255:.3f});

scene = Sprite(Image("assets/f000.png"));
scene.SetPosition(0, 0);
label = Sprite(Image("assets/label.png"));
label.SetZ(1000);

t = 0.0;
frame = 0;
fun pad3(n) {{
    if (n < 10) return "00" + n;
    if (n < 100) return "0" + n;
    return "" + n;
}}
fun refresh_callback() {{
    frame = (frame + 1) % frames_total;
    img = Image("assets/f" + pad3(frame) + ".png");
    s = fit_scale();
    img.Scale(BASE_W * s, BASE_H * s);
    scene.SetImage(img);
    scene.SetPosition((Window.GetWidth() - BASE_W * s) / 2, (Window.GetHeight() - BASE_H * s) / 2);
    label.SetPosition((Window.GetWidth() - label.GetImage().GetWidth()) / 2,
                      Window.GetHeight() - {lh} - 36);
    label.SetOpacity(0.72 + 0.28 * Math.Sin(t * 1.4));
    t += 0.04;
}}
Plymouth.SetRefreshFunction(refresh_callback);

fun display_message(text, sprite) {{ }}
fun display_normal(text) {{ }}
Plymouth.SetDisplayMessageFunction(display_message);
Plymouth.SetDisplayPasswordFunction(display_message);
Plymouth.SetDisplayQuestionFunction(display_message);
Plymouth.SetBootProgressFunction(fun (a, b) {{ }});
"""
    (theme_dir/"tardis.script").write_text(script, encoding="utf-8")
    (theme_dir/"tardis.plymouth").write_text(
        "[Plymouth Theme]\nName=TARDIS\nDescription=Arranque TARDIS animado (cabina de mando)\n"
        "ModuleName=script\n\n[script]\nImageDir=/usr/share/plymouth/themes/tardis\n"
        "ScriptFile=/usr/share/plymouth/themes/tardis/tardis.script\n", encoding="utf-8")
    if preview_dir:
        preview_dir.mkdir(parents=True, exist_ok=True)
        ff = shutil.which("ffmpeg")
        if ff:
            subprocess.run([ff,"-y","-loglevel","error","-framerate",str(FPS),"-i",str(assets/"f%03d.png"),
                            "-c:v","libx264","-pix_fmt","yuv420p","-vf","scale=960:-1",
                            str(preview_dir/"tardis-boot-animation.mp4")], timeout=300)
    total = sum(f.stat().st_size for f in assets.iterdir())
    return {"mode":"animated","frames":FRAMES,"assets_bytes":total,"theme":str(theme_dir),"label":f"{lw}x{lh}"}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BASE/"plymouth-tardis"))
    ap.add_argument("--preview", default="/tmp/tardis-boot-preview")
    a = ap.parse_args()
    print(json.dumps(build(Path(a.out), Path(a.preview)), ensure_ascii=False, indent=2))
