"""
core/aegis/report.py — Panel HTML autónomo del estado de blindaje.
==================================================================
Genera un artefacto autocontenido (sin CDN ni JavaScript externo) con la
postura de seguridad, hallazgos, custodia de claves, kernel y red.
"""
from __future__ import annotations

import html
import time
from typing import Any, Dict, List

_SEV_COLOR = {
    "crítico": "#f43f5e",
    "alto": "#fb923c",
    "medio": "#fbbf24",
    "bajo": "#38bdf8",
    "info": "#94a3b8",
}
_SEV_ORDER = ["crítico", "alto", "medio", "bajo", "info"]


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _score_color(score: int) -> str:
    if score >= 85:
        return "#4ade80"
    if score >= 65:
        return "#fbbf24"
    if score >= 40:
        return "#fb923c"
    return "#f43f5e"


def _findings_rows(findings: List[Dict[str, Any]], limit: int = 250) -> str:
    rows = []
    for f in findings[:limit]:
        color = _SEV_COLOR.get(str(f.get("severity")), "#94a3b8")
        fixed = f.get("fixed")
        badge = (
            '<span class="badge ok">CORREGIDO</span>'
            if fixed
            else f'<span class="badge" style="color:{color};border-color:{color}">{_e(f.get("severity", ""))}</span>'
        )
        rows.append(
            "<tr>"
            f"<td>{badge}</td>"
            f"<td class='code'>{_e(f.get('code', ''))}</td>"
            f"<td><strong>{_e(f.get('title', ''))}</strong>"
            f"<div class='muted'>{_e(f.get('detail', ''))}</div></td>"
            f"<td class='path'>{_e(f.get('path', ''))}</td>"
            f"<td class='muted'>{_e(f.get('remediation', ''))}</td>"
            "</tr>"
        )
    return "\n".join(rows) or "<tr><td colspan='5' class='muted'>Sin hallazgos.</td></tr>"


def _sysctl_rows(sysctl: Dict[str, Dict[str, str]]) -> str:
    rows = []
    for key, data in sorted(sysctl.items()):
        ok = data.get("ok")
        rows.append(
            "<tr>"
            f"<td class='code'>{_e(key)}</td>"
            f"<td class='code'>{_e(data.get('current'))}</td>"
            f"<td class='code'>{_e(data.get('desired'))}</td>"
            f"<td>{'<span class=\"dot ok\"></span>' if ok else '<span class=\"dot bad\"></span>'}</td>"
            f"<td class='muted'>{_e(data.get('profile'))}</td>"
            "</tr>"
        )
    return "\n".join(rows) or "<tr><td colspan='5' class='muted'>Sin datos.</td></tr>"


def _listener_rows(listeners: List[Dict[str, Any]]) -> str:
    rows = []
    for s in listeners:
        exposed = s.get("exposed")
        rows.append(
            "<tr>"
            f"<td class='code'>{_e(s.get('address'))}:{_e(s.get('port'))}</td>"
            f"<td class='code'>{_e(s.get('proto'))}</td>"
            f"<td>{'<span class=\"badge\" style=\"color:#f43f5e;border-color:#f43f5e\">EXPUESTO</span>' if exposed else '<span class=\"badge ok\">LOCAL</span>'}</td>"
            f"<td class='muted'>{_e(s.get('process', ''))}</td>"
            "</tr>"
        )
    return "\n".join(rows) or "<tr><td colspan='4' class='muted'>Sin sockets detectados.</td></tr>"


def render_html(payload: Dict[str, Any]) -> str:
    score = int(payload.get("score", 0))
    counts = payload.get("counts", {})
    policy = payload.get("policy", {})
    hard = payload.get("hardening", {})
    key = payload.get("key", {})
    ledger = payload.get("ledger", {})
    score_color = _score_color(score)
    generated = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(payload.get("generated", time.time())))
    findings = policy.get("findings", [])
    all_findings = findings + hard.get("findings", [])

    legend = "".join(
        f"<span class='chip' style='border-color:{c}'>{k.upper()}: {v}</span>"
        for k, v in counts.items()
        for c in [_SEV_COLOR.get(k, "#94a3b8")]
    )

    fw = hard.get("firewall", {})
    luks = hard.get("luks", {})
    stats = [
        ("Archivos auditados", f"{policy.get('scanned_files', 0):,}"),
        ("Hallazgos", f"{len(all_findings):,}"),
        ("Sellados", f"{payload.get('sealed_files', 0):,}"),
        ("Ledger", f"{ledger.get('entries', 0):,} eventos"),
        ("LUKS", "SÍ" if luks.get("root_encrypted") else "NO"),
        ("Firewall", "ACTIVO" if fw.get("active") else "INACTIVO"),
        ("Auditd", "ACTIVO" if hard.get("auditd_active") else "INACTIVO"),
        ("Secure Boot", {True: "SÍ", False: "NO", None: "N/D"}.get(hard.get("secure_boot"), "N/D")),
    ]
    stat_cards = "".join(
        f"<div class='stat'><div class='stat-label'>{_e(k)}</div><div class='stat-value'>{_e(v)}</div></div>"
        for k, v in stats
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>AEGIS-Ω · Panel de Blindaje</title>
<style>
  :root {{
    --bg:#05070d; --panel:#0a0f1a; --panel2:#0d1524; --line:#1e2a3d;
    --text:#e2e8f0; --muted:#7c8ba1; --gold:#d4af37; --cyan:#22d3ee;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:
      radial-gradient(1200px 600px at 85% -10%, #0e2a3a 0%, transparent 60%),
      radial-gradient(900px 500px at 5% 110%, #1a1406 0%, transparent 55%),
      var(--bg);
    color:var(--text); font-family:"Segoe UI",system-ui,-apple-system,sans-serif; }}
  .wrap {{ max-width:1280px; margin:0 auto; padding:36px 24px 80px; }}
  header {{ display:flex; flex-wrap:wrap; align-items:flex-end; justify-content:space-between; gap:20px;
    border-bottom:1px solid var(--line); padding-bottom:22px; margin-bottom:26px; }}
  .brand {{ display:flex; align-items:center; gap:16px; }}
  .sigil {{ width:58px; height:58px; border:1px solid var(--gold); border-radius:50%;
    display:grid; place-items:center; color:var(--gold); font-weight:700; letter-spacing:1px;
    box-shadow:0 0 28px rgba(212,175,55,.25), inset 0 0 18px rgba(212,175,55,.12); }}
  h1 {{ margin:0; font-size:27px; letter-spacing:3px; font-weight:600; }}
  h1 span {{ color:var(--gold); }}
  .sub {{ color:var(--muted); font-size:12px; letter-spacing:2px; text-transform:uppercase; margin-top:5px; }}
  .meta {{ text-align:right; font-size:12px; color:var(--muted); line-height:1.9; }}
  .meta b {{ color:var(--text); font-weight:500; }}
  .grid {{ display:grid; grid-template-columns:280px 1fr; gap:22px; align-items:start; }}
  @media (max-width:900px) {{ .grid {{ grid-template-columns:1fr; }} .meta {{ text-align:left; }} }}
  .panel {{ background:linear-gradient(180deg,var(--panel2),var(--panel)); border:1px solid var(--line);
    border-radius:14px; padding:20px; }}
  .gauge {{ width:200px; height:200px; margin:6px auto 16px; border-radius:50%;
    background:conic-gradient({score_color} {score * 3.6}deg, #131c2c 0deg);
    display:grid; place-items:center; position:relative; }}
  .gauge::after {{ content:""; position:absolute; inset:13px; border-radius:50%; background:#080d16; }}
  .gauge .val {{ position:relative; z-index:2; text-align:center; }}
  .gauge .num {{ font-size:52px; font-weight:700; color:{score_color}; line-height:1; }}
  .gauge .lbl {{ font-size:10px; letter-spacing:3px; color:var(--muted); margin-top:6px; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:7px; justify-content:center; margin-top:6px; }}
  .chip {{ font-size:10px; letter-spacing:1px; border:1px solid var(--line); border-radius:999px;
    padding:4px 9px; color:var(--text); text-transform:uppercase; }}
  .stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:22px; }}
  @media (max-width:900px) {{ .stats {{ grid-template-columns:repeat(2,1fr); }} }}
  .stat {{ background:var(--panel); border:1px solid var(--line); border-radius:11px; padding:14px 16px; }}
  .stat-label {{ font-size:10px; letter-spacing:1.6px; color:var(--muted); text-transform:uppercase; }}
  .stat-value {{ font-size:19px; margin-top:6px; font-weight:600; }}
  h2 {{ font-size:12px; letter-spacing:3px; text-transform:uppercase; color:var(--gold);
    margin:0 0 14px; font-weight:600; }}
  h2::after {{ content:""; display:block; width:34px; height:1px; background:var(--gold); margin-top:8px; opacity:.7; }}
  table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
  th {{ text-align:left; color:var(--muted); font-size:10px; letter-spacing:1.4px; text-transform:uppercase;
    font-weight:500; padding:8px 10px; border-bottom:1px solid var(--line); }}
  td {{ padding:10px; border-bottom:1px solid rgba(30,42,61,.55); vertical-align:top; }}
  tr:hover td {{ background:rgba(34,211,238,.03); }}
  .code {{ font-family:"JetBrains Mono","Fira Code",monospace; font-size:11.5px; color:var(--cyan); }}
  .path {{ font-family:monospace; font-size:11px; color:#cbd5e1; word-break:break-all; }}
  .muted {{ color:var(--muted); font-size:11.5px; }}
  .badge {{ display:inline-block; font-size:9.5px; letter-spacing:1.3px; text-transform:uppercase;
    border:1px solid var(--line); border-radius:5px; padding:3px 7px; white-space:nowrap; }}
  .badge.ok {{ color:#4ade80; border-color:#4ade80; }}
  .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; }}
  .dot.ok {{ background:#4ade80; box-shadow:0 0 8px #4ade80; }}
  .dot.bad {{ background:#f43f5e; box-shadow:0 0 8px #f43f5e; }}
  .two {{ display:grid; grid-template-columns:1fr 1fr; gap:22px; }}
  @media (max-width:900px) {{ .two {{ grid-template-columns:1fr; }} }}
  .kv {{ display:flex; justify-content:space-between; gap:14px; padding:7px 0; border-bottom:1px dashed rgba(30,42,61,.6); font-size:12px; }}
  .kv span:first-child {{ color:var(--muted); }}
  .kv span:last-child {{ font-family:monospace; color:var(--cyan); text-align:right; word-break:break-all; }}
  footer {{ margin-top:34px; padding-top:18px; border-top:1px solid var(--line); color:var(--muted);
    font-size:10.5px; letter-spacing:1.6px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:10px; }}
  .seal {{ color:var(--gold); }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <div class="sigil">Ω</div>
      <div>
        <h1>AEGIS<span>-Ω</span></h1>
        <div class="sub">Sistema de Blindaje Militar de Información · GODWORKS v26.4</div>
      </div>
    </div>
    <div class="meta">
      <div>GENERADO <b>{_e(generated)}</b></div>
      <div>RAÍZ <b>{_e(payload.get('root', ''))}</b></div>
      <div>HUELLA MAESTRA <b>{_e(key.get('fingerprint', '—'))}</b></div>
      <div>LEDGER <b>{'ÍNTEGRO' if ledger.get('ok') else 'COMPROMETIDO'}</b> · {ledger.get('entries', 0)} eventos</div>
    </div>
  </header>

  <div class="stats">{stat_cards}</div>

  <div class="grid">
    <div>
      <div class="panel">
        <div class="gauge"><div class="val"><div class="num">{score}</div><div class="lbl">POSTURA</div></div></div>
        <div class="chips">{legend}</div>
      </div>
      <div class="panel" style="margin-top:22px">
        <h2>Custodia</h2>
        <div class="kv"><span>Clave maestra</span><span>{_e(key.get('mode', '—'))}</span></div>
        <div class="kv"><span>Passphrase</span><span>{'SÍ' if key.get('passphrase_wrapped') else 'NO'}</span></div>
        <div class="kv"><span>Kit recuperación</span><span>{'SÍ' if key.get('recovery_kit') else 'NO'}</span></div>
        <div class="kv"><span>Archivos sellados</span><span>{payload.get('sealed_files', 0)}</span></div>
        <div class="kv"><span>Objetos en bóveda</span><span>{payload.get('vault_objects', 0)}</span></div>
        <div class="kv"><span>Ancla ledger</span><span>{'OK' if ledger.get('anchor_ok') else 'FALLA'}</span></div>
      </div>
    </div>

    <div class="panel">
      <h2>Hallazgos priorizados</h2>
      <table>
        <thead><tr><th>Severidad</th><th>Código</th><th>Hallazgo</th><th>Ruta</th><th>Remediación</th></tr></thead>
        <tbody>{_findings_rows(all_findings)}</tbody>
      </table>
    </div>
  </div>

  <div class="two" style="margin-top:22px">
    <div class="panel">
      <h2>Línea base del kernel</h2>
      <table>
        <thead><tr><th>Parámetro</th><th>Actual</th><th>Deseado</th><th>Estado</th><th>Perfil</th></tr></thead>
        <tbody>{_sysctl_rows(hard.get('sysctl_status', hard.get('sysctl', {})))}</tbody>
      </table>
    </div>
    <div class="panel">
      <h2>Superficie de red</h2>
      <div class="kv"><span>Firewall</span><span>{_e(fw.get('backend', '—'))} · {'ACTIVO' if fw.get('active') else 'INACTIVO'}</span></div>
      <div class="kv"><span>Raíz cifrada</span><span>{'SÍ' if luks.get('root_encrypted') else 'NO'}</span></div>
      <div class="kv"><span>Volúmenes LUKS</span><span>{_e(', '.join(luks.get('crypt_devices', [])) or '—')}</span></div>
      <div class="kv"><span>Swap</span><span>{_e(luks.get('swap') or '—')}</span></div>
      <table style="margin-top:14px">
        <thead><tr><th>Socket</th><th>Proto</th><th>Alcance</th><th>Proceso</th></tr></thead>
        <tbody>{_listener_rows(hard.get('listeners', []))}</tbody>
      </table>
    </div>
  </div>

  <footer>
    <span class="seal">AEGIS-Ω · LA CONSTANTE AEGIS</span>
    <span>Documento generado localmente · sin telemetría · clasificación C4</span>
  </footer>
</div>
</body>
</html>
"""
