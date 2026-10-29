#!/usr/bin/env python3
"""
FTL PUBLIC GATEWAY · TARDIS SOBERANO
====================================
Puerta de entrada única, autenticada y cifrada (Cloudflare Tunnel) hacia:

  /            -> Portal FTL (:8765)
  /terminal    -> Terminal web ttyd (:7681, base-path /terminal)
  /api/*       -> API del portal FTL
  /chat        -> Chat web persistente

Características:
  * Token de acceso soberano (query ?key=... o cookie HttpOnly).
  * Proxy HTTP + WebSocket completo (terminal interactiva).
  * Streaming SSE sin buffering (chat TARDIS).
  * Healthcheck sin autenticación para monitoreo local.
  * Sin exposición directa de ttyd ni del portal a Internet.

El token se genera automáticamente en ~/.config/ftl/public_gateway.json
con permisos 0600. El túnel Cloudflare se encarga de la capa TLS pública.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

HOME = Path.home()
CONFIG_DIR = HOME / ".config" / "ftl"
CONFIG_PATH = CONFIG_DIR / "public_gateway.json"
ACCESS_PATH = CONFIG_DIR / "public_access.txt"

DEFAULT_PORT = 7690
PORTAL_UPSTREAM = os.environ.get("FTL_PORTAL_UPSTREAM", "http://127.0.0.1:8765")
TERMINAL_UPSTREAM = os.environ.get("FTL_TERMINAL_UPSTREAM", "http://127.0.0.1:7681")
TERMINAL_PREFIX = "/terminal"
COOKIE_NAME = "ftl_gateway"
SESSION_TTL = 60 * 60 * 24 * 30  # 30 días

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def _ensure_config() -> Dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg: Dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    changed = False
    if not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(32)
        changed = True
    cfg.setdefault("port", DEFAULT_PORT)
    cfg.setdefault("portal_upstream", PORTAL_UPSTREAM)
    cfg.setdefault("terminal_upstream", TERMINAL_UPSTREAM)
    cfg.setdefault("terminal_prefix", TERMINAL_PREFIX)
    cfg.setdefault("created_at", time.time())
    cfg["updated_at"] = time.time()
    if changed or not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        os.chmod(CONFIG_PATH, 0o600)
    return cfg


CONFIG = _ensure_config()
TOKEN: str = str(CONFIG["token"])
PORT: int = int(CONFIG.get("port", DEFAULT_PORT))
PORTAL: str = str(CONFIG.get("portal_upstream", PORTAL_UPSTREAM)).rstrip("/")
TERMINAL: str = str(CONFIG.get("terminal_upstream", TERMINAL_UPSTREAM)).rstrip("/")
TERM_PREFIX: str = str(CONFIG.get("terminal_prefix", TERMINAL_PREFIX)).rstrip("/")

START_TS = time.time()
METRICS: Dict[str, Any] = {
    "requests": 0,
    "auth_ok": 0,
    "auth_fail": 0,
    "ws_open": 0,
    "ws_close": 0,
    "errors": 0,
    "last_request": None,
}


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------


def _cookie_secure(request: web.Request) -> bool:
    proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "").lower()
    return proto == "https"


def _valid_token(candidate: Optional[str]) -> bool:
    if not candidate:
        return False
    return secrets.compare_digest(str(candidate), TOKEN)


def _is_authenticated(request: web.Request) -> bool:
    if _valid_token(request.query.get("key")):
        return True
    if _valid_token(request.cookies.get(COOKIE_NAME)):
        return True
    # Compatibilidad con proxies que inyectan el token como header.
    if _valid_token(request.headers.get("X-FTL-Token")):
        return True
    return False


def _wants_json(request: web.Request) -> bool:
    path = request.path
    accept = request.headers.get("Accept", "")
    return path.startswith("/api/") or "application/json" in accept


def _login_page(error: str = "") -> str:
    error_html = f'<div class="error">{error}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FTL · Acceso Soberano</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh; display: grid; place-items: center;
    background: radial-gradient(circle at 50% 0%, #10233a 0%, #07090e 55%, #030407 100%);
    color: #e2e8f0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }}
  .card {{
    width: min(92vw, 430px); padding: 34px 30px; border-radius: 20px;
    background: rgba(14, 20, 32, .82); border: 1px solid rgba(0, 255, 204, .28);
    box-shadow: 0 0 60px rgba(0, 255, 204, .08), inset 0 0 40px rgba(0, 255, 204, .03);
    backdrop-filter: blur(14px);
  }}
  h1 {{ margin: 0 0 6px; font-size: 1.25rem; color: #00ffcc; letter-spacing: .04em; }}
  p {{ margin: 0 0 22px; color: #94a3b8; font-size: .84rem; line-height: 1.5; }}
  input {{
    width: 100%; padding: 13px 14px; border-radius: 12px; border: 1px solid #24344d;
    background: #080d16; color: #e2e8f0; font: inherit; outline: none;
  }}
  input:focus {{ border-color: #00ffcc; box-shadow: 0 0 0 3px rgba(0, 255, 204, .12); }}
  button {{
    width: 100%; margin-top: 14px; padding: 13px 14px; border: 0; border-radius: 12px;
    background: linear-gradient(135deg, #00ffcc, #00b894); color: #04120f;
    font-weight: 800; font: inherit; cursor: pointer; letter-spacing: .05em;
  }}
  button:hover {{ filter: brightness(1.08); }}
  .error {{ margin: 0 0 14px; padding: 10px 12px; border-radius: 10px; background: rgba(255, 85, 85, .12); border: 1px solid rgba(255, 85, 85, .35); color: #ff8f8f; font-size: .8rem; }}
  .foot {{ margin-top: 18px; color: #52627a; font-size: .68rem; text-align: center; }}
</style>
</head>
<body>
  <form class="card" method="POST" action="/auth">
    <h1>⚡ FTL · ACCESO SOBERANO</h1>
    <p>Introduce la clave de acceso para entrar al portal y a la terminal TARDIS.</p>
    {error_html}
    <input type="password" name="token" placeholder="Clave de acceso" autofocus autocomplete="current-password" required>
    <button type="submit">DESBLOQUEAR PORTAL</button>
    <div class="foot">TARDIS · Nodo Soberano · Conexión cifrada</div>
  </form>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Proxy HTTP
# ---------------------------------------------------------------------------


def _upstream_for(request: web.Request) -> Tuple[str, str]:
    """Devuelve (base_upstream, path_upstream)."""
    path = request.path
    if path == TERM_PREFIX or path.startswith(TERM_PREFIX + "/"):
        # ttyd está configurado con --base-path /terminal: se conserva el prefijo.
        return TERMINAL, path
    return PORTAL, path


def _clean_query(request: web.Request) -> str:
    """Query para el upstream sin filtrar secretos (ej. ?key=) ni campos hop-by-hop."""
    params = [(k, v) for k, v in request.query.items() if k != "key"]
    return urlencode(params, doseq=True)


def _filtered_headers(headers: Iterable[Tuple[str, str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in headers:
        if key.lower() in HOP_BY_HOP:
            continue
        if key.lower() in {"accept-encoding"}:
            # Dejamos que aiohttp negocie y evita cuerpos comprimidos opacos.
            continue
        out[key] = value
    return out


async def _proxy_http(request: web.Request, session: ClientSession) -> web.StreamResponse:
    base, path = _upstream_for(request)
    query = _clean_query(request)
    url = base + path + (("?" + query) if query else "")

    body = await request.read()
    headers = _filtered_headers(request.headers.items())
    headers["X-FTL-Gateway"] = "1"
    headers["X-Forwarded-Host"] = request.host
    headers["X-Forwarded-Proto"] = request.scheme
    headers["X-Forwarded-For"] = request.remote or ""
    headers["X-Real-IP"] = request.remote or ""

    timeout = ClientTimeout(total=None, sock_connect=10, sock_read=3600)
    try:
        upstream = await session.request(
            request.method,
            url,
            headers=headers,
            data=body if body else None,
            allow_redirects=False,
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        METRICS["errors"] += 1
        return web.Response(status=504, text="Upstream timeout")
    except Exception as exc:  # noqa: BLE001
        METRICS["errors"] += 1
        return web.Response(status=502, text=f"Upstream error: {exc}")

    out_headers = _filtered_headers(upstream.headers.items())
    # No reenviar content-length: el streaming usa chunked.
    out_headers.pop("Content-Length", None)
    out_headers.pop("content-length", None)

    response = web.StreamResponse(status=upstream.status, headers=out_headers)
    if request.method == "HEAD":
        await response.prepare(request)
        await response.write_eof()
        upstream.release()
        return response

    await response.prepare(request)
    try:
        async for chunk in upstream.content.iter_chunked(16384):
            if chunk:
                await response.write(chunk)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        upstream.release()
    try:
        await response.write_eof()
    except Exception:
        pass
    return response


# ---------------------------------------------------------------------------
# Proxy WebSocket
# ---------------------------------------------------------------------------


async def _proxy_ws(
    request: web.Request,
    session: ClientSession,
    install_cookie: bool = False,
) -> web.WebSocketResponse:
    base, path = _upstream_for(request)
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
    query = _clean_query(request)
    url = ws_base + path + (("?" + query) if query else "")

    protocols = []
    raw_proto = request.headers.get("Sec-WebSocket-Protocol")
    if raw_proto:
        protocols = [p.strip() for p in raw_proto.split(",") if p.strip()]

    ws_server = web.WebSocketResponse(protocols=protocols or (), heartbeat=30)
    if install_cookie:
        # Set-Cookie debe fijarse ANTES del prepare() de la respuesta 101:
        # asi el navegador movil queda con sesion al abrir el enlace ?key=...
        secure = "; Secure" if _cookie_secure(request) else ""
        ws_server.headers["Set-Cookie"] = (
            f"{COOKIE_NAME}={TOKEN}; Max-Age={SESSION_TTL}; Path=/; "
            f"HttpOnly; SameSite=Lax{secure}"
        )
    await ws_server.prepare(request)
    METRICS["ws_open"] += 1

    headers = _filtered_headers(request.headers.items())
    headers["X-FTL-Gateway"] = "1"
    headers["X-Forwarded-Host"] = request.host
    headers["X-Forwarded-Proto"] = request.scheme

    ws_client = None
    try:
        ws_client = await session.ws_connect(
            url,
            headers=headers,
            protocols=protocols or (),
            heartbeat=30,
            timeout=ClientTimeout(total=None, sock_connect=10, sock_read=None),
        )

        async def relay(src, dst) -> None:
            try:
                async for msg in src:
                    if msg.type == WSMsgType.TEXT:
                        await dst.send_str(msg.data)
                    elif msg.type == WSMsgType.BINARY:
                        await dst.send_bytes(msg.data)
                    elif msg.type == WSMsgType.PING:
                        await dst.ping(msg.data)
                    elif msg.type == WSMsgType.PONG:
                        await dst.pong(msg.data)
                    elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                        break
                    elif msg.type == WSMsgType.ERROR:
                        break
            except Exception:
                pass
            finally:
                # Cuando un sentido termina (cliente móvil caído, ttyd cerrado,
                # etc.) se cierra inmediatamente el socket opuesto para que el
                # relay hermano también termine y no queden conexiones fantasma
                # agotando el límite de --max-clients de ttyd.
                try:
                    if dst is not None and not dst.closed:
                        await dst.close()
                except Exception:
                    pass

        await asyncio.gather(
            relay(ws_server, ws_client),
            relay(ws_client, ws_server),
        )
    except Exception:
        METRICS["errors"] += 1
    finally:
        METRICS["ws_close"] += 1
        for sock in (ws_client, ws_server):
            if sock is None:
                continue
            try:
                if not sock.closed:
                    await sock.close()
            except Exception:
                pass
    return ws_server


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def health(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "service": "ftl-public-gateway",
            "uptime_s": round(time.time() - START_TS, 1),
            "portal": PORTAL,
            "terminal": TERMINAL,
            "metrics": METRICS,
        }
    )


async def auth_post(request: web.Request) -> web.Response:
    data = await request.post()
    candidate = str(data.get("token", ""))
    if not _valid_token(candidate):
        METRICS["auth_fail"] += 1
        return web.Response(status=401, text=_login_page("Clave incorrecta. Inténtalo de nuevo."), content_type="text/html")
    METRICS["auth_ok"] += 1
    response = web.HTTPFound("/")
    response.set_cookie(
        COOKIE_NAME,
        TOKEN,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="Lax",
        secure=_cookie_secure(request),
        path="/",
    )
    return response


async def auth_get(request: web.Request) -> web.Response:
    return web.Response(text=_login_page(), content_type="text/html")


async def gateway(request: web.Request) -> web.StreamResponse:
    METRICS["requests"] += 1
    METRICS["last_request"] = {"ts": time.time(), "path": request.path, "ip": request.remote}

    is_ws = (request.headers.get("Upgrade", "").lower() == "websocket")

    # Healthcheck local sin token.
    if request.path == "/health":
        return await health(request)

    if request.path == "/auth":
        if request.method == "POST":
            return await auth_post(request)
        return await auth_get(request)

    session = request.app["client"]

    if is_ws:
        # Los upgrades websocket NO toleran redirecciones: aquí se autentica
        # de forma directa. Compatibilidad total con ?key=..., cookies y
        # cabecera X-FTL-Token. Con ?key válido además se entrega la cookie
        # de sesión en la respuesta 101 para persistir la sesión.
        auth_ok = (
            _valid_token(request.query.get("key"))
            or _valid_token(request.cookies.get(COOKIE_NAME))
            or _valid_token(request.headers.get("X-FTL-Token"))
        )
        if not auth_ok:
            METRICS["auth_fail"] += 1
            if _wants_json(request):
                return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
            return web.Response(status=401, text=_login_page("Acceso restringido. Introduce la clave."), content_type="text/html")
        METRICS["auth_ok"] += 1
        socket_key = _valid_token(request.query.get("key"))
        return await _proxy_ws(request, session, install_cookie=socket_key)

    # Token por query: autentica, deja cookie y limpia la URL.
    if _valid_token(request.query.get("key")):
        METRICS["auth_ok"] += 1
        query = {k: v for k, v in request.query.items() if k != "key"}
        clean_path = request.path + (("?" + urlencode(query, doseq=True)) if query else "")
        response = web.HTTPFound(clean_path or "/")
        response.set_cookie(
            COOKIE_NAME,
            TOKEN,
            max_age=SESSION_TTL,
            httponly=True,
            samesite="Lax",
            secure=_cookie_secure(request),
            path="/",
        )
        return response

    if not _is_authenticated(request):
        METRICS["auth_fail"] += 1
        if _wants_json(request):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        return web.Response(status=401, text=_login_page("Acceso restringido. Introduce la clave."), content_type="text/html")

    METRICS["auth_ok"] += 1

    # Los upgrades websocket ya fueron atendidos arriba; aquí solo fluye HTTP.
    return await _proxy_http(request, session)


async def on_startup(app: web.Application) -> None:
    app["client"] = ClientSession(
        auto_decompress=True,
        timeout=ClientTimeout(total=None, sock_connect=10, sock_read=3600),
    )
    print(f"[FTL-GATEWAY] Escuchando en 0.0.0.0:{PORT}", flush=True)
    print(f"[FTL-GATEWAY] Portal  -> {PORTAL}", flush=True)
    print(f"[FTL-GATEWAY] Terminal-> {TERMINAL}{TERM_PREFIX}", flush=True)


async def on_cleanup(app: web.Application) -> None:
    await app["client"].close()


def create_app() -> web.Application:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app.router.add_route("*", "/{tail:.*}", gateway)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    print("=" * 70)
    print("⚡ FTL PUBLIC GATEWAY · TARDIS SOBERANO")
    print("=" * 70)
    print(f"Token config: {CONFIG_PATH}")
    print(f"Acceso local: http://127.0.0.1:{PORT}/?key={TOKEN[:8]}…")
    print("=" * 70)
    web.run_app(create_app(), host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
