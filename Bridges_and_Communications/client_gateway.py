"""
client_gateway.py - Gateway seguro de acceso para clientes externos de TARDIS
==============================================================================
Servicio independiente y aislado del bridge de control (omni_temporal_control.py).
Expone únicamente chat con el modelo para clientes autorizados por email
(login sin contraseña vía magic link), y proxya al endpoint interno
/api/client/chat del bridge por loopback. No expone ninguna otra
funcionalidad del sistema (cámaras, sensores, telemetría, administración).
"""

from __future__ import annotations

import hashlib
import json
import re
import smtplib
import time
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

BASE_DIR = Path(__file__).resolve().parent
SECRETS_PATH = BASE_DIR / "client_gateway_secrets.json"

with SECRETS_PATH.open("r", encoding="utf-8") as f:
    SECRETS = json.load(f)

SECRET_KEY: str = SECRETS["secret_key"]
SMTP_CFG: dict = SECRETS["smtp"]
ALLOWLIST = {e.strip().lower() for e in SECRETS.get("allowlist", [])}
GATEWAY_PORT: int = SECRETS.get("gateway_port", 8790)
BRIDGE_URL: str = SECRETS.get("bridge_url", "http://REDACTED_IP:8757").rstrip("/")

LOGIN_SALT = "client-gateway-login"
SESSION_SALT = "client-gateway-session"
LOGIN_MAX_AGE = 15 * 60          # 15 minutos para usar el link mágico
SESSION_MAX_AGE = 30 * 24 * 3600  # 30 días de sesión

login_serializer = URLSafeTimedSerializer(SECRET_KEY, salt=LOGIN_SALT)
session_serializer = URLSafeTimedSerializer(SECRET_KEY, salt=SESSION_SALT)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Tokens de login ya usados (evita reutilización); entradas se purgan por expiración natural
_used_tokens: set[str] = set()
# Rate limit simple por email
_last_login_request: dict[str, float] = {}
LOGIN_COOLDOWN_SECONDS = 60

app = FastAPI(title="TARDIS Client Gateway")


def _client_id_for(email: str) -> str:
    return "web_" + hashlib.sha256(email.encode("utf-8")).hexdigest()[:24]


def _public_base_url(request: Request) -> str:
    host = request.headers.get("host", f"REDACTED_IP:{GATEWAY_PORT}")
    proto = request.headers.get("x-forwarded-proto", "https")
    return f"{proto}://{host}"


def _send_magic_link(to_email: str, link: str) -> None:
    body = (
        "Hola,\n\n"
        "Este es tu link de acceso a TARDIS. Es válido por 15 minutos y solo se puede usar una vez:\n\n"
        f"{link}\n\n"
        "Si no pediste este acceso, podés ignorar este mensaje.\n"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "Tu acceso a TARDIS"
    from_name = SMTP_CFG.get("from_name", "TARDIS")
    msg["From"] = f"{from_name} <{SMTP_CFG['user']}>"
    msg["To"] = to_email

    password = SMTP_CFG["app_password"].replace(" ", "")
    with smtplib.SMTP_SSL(SMTP_CFG["host"], SMTP_CFG["port"], timeout=15) as server:
        server.login(SMTP_CFG["user"], password)
        server.sendmail(SMTP_CFG["user"], [to_email], msg.as_string())


def _get_session_email(request: Request) -> Optional[str]:
    token = request.cookies.get("tardis_session")
    if not token:
        return None
    try:
        data = session_serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("email")
    except (BadSignature, SignatureExpired):
        return None


LOGIN_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Acceso TARDIS</title>
<style>
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#06090e;color:#e6f7f5;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{background:#0d141c;padding:2rem;border-radius:12px;width:min(360px,90vw);box-shadow:0 0 0 1px #1c2836}
h1{font-size:1.2rem;color:#00d4c8;margin:0 0 1rem}
input{width:100%;padding:.7rem;border-radius:8px;border:1px solid #1c2836;background:#06090e;color:#e6f7f5;box-sizing:border-box;margin-bottom:.8rem}
button{width:100%;padding:.7rem;border-radius:8px;border:none;background:#00d4c8;color:#06090e;font-weight:600;cursor:pointer}
button:disabled{opacity:.6;cursor:default}
#msg{margin-top:1rem;font-size:.9rem;color:#8ea3ad;min-height:1.2em}
</style></head>
<body><div class="card">
<h1>Acceso a TARDIS</h1>
<form id="f">
<input type="email" id="email" placeholder="tu@email.com" required>
<button type="submit">Enviar link de acceso</button>
</form>
<div id="msg"></div>
</div>
<script>
document.getElementById('f').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector('button');
  const msg = document.getElementById('msg');
  btn.disabled = true;
  msg.textContent = 'Enviando...';
  try {
    const r = await fetch('/login', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email: document.getElementById('email').value})
    });
    const j = await r.json();
    msg.textContent = j.ok ? 'Si tu email está autorizado, te enviamos un link. Revisá tu correo.' : (j.error || 'Error');
  } catch (err) {
    msg.textContent = 'Error de red, probá de nuevo.';
  }
  btn.disabled = false;
});
</script></body></html>"""

CHAT_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TARDIS</title>
<style>
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#06090e;color:#e6f7f5;margin:0;
display:flex;flex-direction:column;height:100vh}
header{padding:.8rem 1rem;border-bottom:1px solid #1c2836;display:flex;justify-content:space-between;align-items:center}
header b{color:#00d4c8}
header a{color:#8ea3ad;font-size:.85rem;text-decoration:none}
#log{flex:1;overflow-y:auto;padding:1rem;display:flex;flex-direction:column;gap:.6rem}
.msg{max-width:80%;padding:.6rem .8rem;border-radius:10px;white-space:pre-wrap;line-height:1.35}
.user{align-self:flex-end;background:#00d4c8;color:#06090e}
.assistant{align-self:flex-start;background:#131c26}
form{display:flex;padding:.8rem;gap:.5rem;border-top:1px solid #1c2836}
input{flex:1;padding:.7rem;border-radius:8px;border:1px solid #1c2836;background:#0d141c;color:#e6f7f5}
button{padding:.7rem 1.1rem;border-radius:8px;border:none;background:#00d4c8;color:#06090e;font-weight:600;cursor:pointer}
button:disabled{opacity:.6}
</style></head>
<body>
<header><b>TARDIS</b><a href="/logout">Salir</a></header>
<div id="log"></div>
<form id="f">
<input id="inp" autocomplete="off" placeholder="Escribí tu mensaje..." required>
<button type="submit">Enviar</button>
</form>
<script>
const log = document.getElementById('log');
function add(role, text) {
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  d.textContent = text;
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
  return d;
}
document.getElementById('f').addEventListener('submit', async (e) => {
  e.preventDefault();
  const inp = document.getElementById('inp');
  const btn = e.target.querySelector('button');
  const text = inp.value.trim();
  if (!text) return;
  add('user', text);
  inp.value = '';
  btn.disabled = true;
  const thinking = add('assistant', 'Pensando...');
  try {
    const r = await fetch('/api/chat', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text})
    });
    if (r.status === 401) { window.location = '/'; return; }
    const j = await r.json();
    thinking.textContent = j.ok ? (j.reply || '(sin respuesta)') : ('Error: ' + (j.error || 'desconocido'));
  } catch (err) {
    thinking.textContent = 'Error de red.';
  }
  btn.disabled = false;
  inp.focus();
});
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if _get_session_email(request):
        return RedirectResponse("/chat", status_code=302)
    return HTMLResponse(LOGIN_PAGE)


@app.post("/login")
async def login(request: Request):
    body = await request.json()
    email = str(body.get("email", "")).strip().lower()

    if not EMAIL_RE.match(email):
        return JSONResponse({"ok": False, "error": "Email inválido"}, status_code=400)

    now = time.time()
    last = _last_login_request.get(email, 0.0)
    if now - last < LOGIN_COOLDOWN_SECONDS:
        return JSONResponse({"ok": True})  # respuesta genérica, no revela rate limit
    _last_login_request[email] = now

    if email in ALLOWLIST:
        token = login_serializer.dumps({"email": email})
        base = _public_base_url(request)
        link = f"{base}/verify?token={token}"
        try:
            _send_magic_link(email, link)
        except Exception as e:
            print(f"[client_gateway] Error enviando email a {email}: {e}", flush=True)

    # Respuesta idéntica exista o no el email en el allowlist (evita enumeración)
    return JSONResponse({"ok": True})


@app.get("/verify")
async def verify(request: Request, token: str = ""):
    try:
        data = login_serializer.loads(token, max_age=LOGIN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return HTMLResponse("<h1>Link inválido o expirado</h1><p><a href='/'>Volver</a></p>", status_code=400)

    if token in _used_tokens:
        return HTMLResponse("<h1>Este link ya fue usado</h1><p><a href='/'>Volver</a></p>", status_code=400)
    _used_tokens.add(token)

    email = data.get("email", "")
    if email not in ALLOWLIST:
        return HTMLResponse("<h1>Acceso no autorizado</h1>", status_code=403)

    session_token = session_serializer.dumps({"email": email})
    resp = RedirectResponse("/chat", status_code=302)
    resp.set_cookie(
        "tardis_session", session_token,
        max_age=SESSION_MAX_AGE, httponly=True, secure=True, samesite="lax",
    )
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie("tardis_session")
    return resp


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    if not _get_session_email(request):
        return RedirectResponse("/", status_code=302)
    return HTMLResponse(CHAT_PAGE)


@app.post("/api/chat")
async def api_chat(request: Request):
    email = _get_session_email(request)
    if not email:
        return JSONResponse({"ok": False, "error": "No autenticado"}, status_code=401)

    body = await request.json()
    message = str(body.get("message", "")).strip()
    if not message:
        return JSONResponse({"ok": False, "error": "Mensaje vacío"}, status_code=400)

    client_id = _client_id_for(email)
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{BRIDGE_URL}/api/client/chat",
                json={"message": message, "client_id": client_id, "client_mode": True},
            )
        data = r.json()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Bridge no disponible: {e}"}, status_code=502)

    return JSONResponse({"ok": data.get("ok", False), "reply": data.get("reply", ""), "error": data.get("error")})


@app.post("/api/chat/clear")
async def api_chat_clear(request: Request):
    email = _get_session_email(request)
    if not email:
        return JSONResponse({"ok": False, "error": "No autenticado"}, status_code=401)

    client_id = _client_id_for(email)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(f"{BRIDGE_URL}/api/client/clear", json={"client_id": client_id})
    except Exception:
        pass
    return JSONResponse({"ok": True})


@app.get("/health")
async def health():
    return JSONResponse({"ok": True, "service": "client_gateway"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="REDACTED_IP", port=GATEWAY_PORT)
