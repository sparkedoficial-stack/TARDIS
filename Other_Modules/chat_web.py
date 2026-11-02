#!/usr/bin/env python3
"""
GODWORKS · FTL Quantum Chat · Web Bridge
========================================
Capa web del chat persistente FTL. Comparte el mismo almacén
(`chat_store`) y el mismo motor (`chat_engine`) que la TUI, de modo que una
conversación iniciada en terminal puede continuarse en el navegador y
viceversa, conservando la sesión nativa de OpenCode.

Rutas expuestas (montadas en el portal :8765):
  GET    /chat                        interfaz completa (cuásar animado)
  GET    /api/chat/bootstrap          sesiones + modelos + defaults
  GET    /api/chat/sessions           lista de sesiones
  POST   /api/chat/sessions           crea sesión
  GET    /api/chat/sessions/{id}      sesión completa con mensajes
  PATCH  /api/chat/sessions/{id}      título/modelo/agente/thinking/auto
  DELETE /api/chat/sessions/{id}      elimina sesión
  POST   /api/chat/send               lanza un turno → {run_id}
  GET    /api/chat/stream/{run_id}    SSE con eventos normalizados
  POST   /api/chat/cancel/{run_id}    cancela el turno en curso
  POST   /api/chat/upload             adjunto base64 → ruta temporal
  GET    /api/chat/export/{id}        descarga Markdown/JSON
"""

from __future__ import annotations

import base64
import json
import threading
import time
import uuid
from pathlib import Path
from queue import Empty, Queue
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

import chat_history as history
import chat_store as store
import chat_vault as vault
import free_models as fm
from chat_engine import ChatConfig, ChatRunner, resolve_model, short_model

router = APIRouter()

UPLOADS_DIR = store.CHAT_DIR / "uploads"

# ---------------------------------------------------------------------------
# Registro de ejecuciones activas
# ---------------------------------------------------------------------------
RUNS: dict[str, dict] = {}
_RUNS_LOCK = threading.Lock()


def _session_or_404(session_id: str) -> dict:
    session = store.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sesión no encontrada: {session_id}")
    return session


def _default_model() -> str:
    try:
        from config import load_config

        cfg = load_config()
        return cfg.get("default_model") or cfg.get("fallback_model") or \
            "opencode/deepseek-v4.1-flash-free#max"
    except Exception:
        return "opencode/deepseek-v4.1-flash-free#max"


def _models_payload() -> list[dict]:
    try:
        rows = fm.summary().get("models", [])
    except Exception:
        rows = []
    out = []
    for m in rows:
        out.append({
            "key": m.get("key"),
            "ref": m.get("ref"),
            "name": m.get("name") or m.get("key"),
            "roles": list(m.get("roles") or []),
            "enabled": bool(m.get("enabled", True)),
            "available": m.get("available"),
            "latency_s": m.get("latency_s"),
        })
    return out


# ---------------------------------------------------------------------------
# Ejecución de un turno en hilo de fondo
# ---------------------------------------------------------------------------
def _emit(entry: dict, payload: dict) -> None:
    entry["queue"].put(payload)


def _execute_turn(entry: dict, session: dict, prompt: str, files: list[str]) -> None:
    settings = session.get("settings", {})
    cfg = ChatConfig(
        model=session.get("model") or _default_model(),
        agent=session.get("agent") or "",
        thinking=bool(settings.get("thinking")),
        auto=bool(settings.get("auto", True)),
        cwd=session.get("cwd") or str(Path.home()),
        files=list(files),
        title=session.get("title", "") if not session.get("opencode_session_id") else "",
    )
    runner = ChatRunner(prompt, cfg, opencode_session_id=session.get("opencode_session_id"))
    entry["runner"] = runner

    assistant_parts: list[str] = []
    thinking_parts: list[str] = []
    tools: list[dict] = []
    tokens_in = tokens_out = 0
    cost = 0.0
    rc: Optional[int] = None
    error: Optional[dict] = None
    session_id = session.get("opencode_session_id")
    last_saved_sid = session_id

    _emit(entry, {"kind": "start", "model": cfg.model, "agent": cfg.agent,
                  "files": files, "session_id": session["id"]})

    try:
        for event in runner.run():
            kind = event.get("kind")
            if kind == "tick":
                if entry.get("cancelled"):
                    break
                _emit(entry, {"kind": "tick"})
                continue
            if kind == "text":
                text = event.get("text") or ""
                assistant_parts.append(text)
                _emit(entry, {"kind": "text", "text": text})
            elif kind == "thinking":
                text = event.get("text") or ""
                if text:
                    thinking_parts.append(text)
                    _emit(entry, {"kind": "thinking", "text": text})
            elif kind == "tool":
                tool = {
                    "tool": event.get("tool") or "tool",
                    "status": event.get("status") or "",
                    "input": event.get("input") or {},
                    "output": (event.get("output") or "")[:4000],
                    "title": event.get("title") or event.get("tool") or "tool",
                }
                tools.append(tool)
                _emit(entry, {"kind": "tool", **tool})
            elif kind == "step_start":
                _emit(entry, {"kind": "step_start"})
            elif kind == "step_finish":
                tokens = event.get("tokens") or {}
                tokens_in += int(tokens.get("input") or 0)
                tokens_out += int(tokens.get("output") or 0)
                cost += float(event.get("cost") or 0.0)
                _emit(entry, {
                    "kind": "step_finish",
                    "tokens": tokens,
                    "cost": event.get("cost") or 0,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                })
            elif kind == "process_end":
                rc = event.get("rc")
                session_id = event.get("session_id") or session_id
                _emit(entry, {"kind": "process_end", "rc": rc, "session_id": session_id})
            elif kind == "error":
                error = event
                _emit(entry, {
                    "kind": "error",
                    "message": event.get("message"),
                    "status": event.get("status"),
                    "error_type": event.get("error_type"),
                    "retry_after_ms": event.get("retry_after_ms"),
                })
            else:
                _emit(entry, {"kind": "raw", "line": (event.get("line") or "")[:400]})

            # Persistir el id real de OpenCode en cuanto se conozca.
            if runner.session_id and runner.session_id != last_saved_sid:
                last_saved_sid = runner.session_id
                session_id = runner.session_id
                session["opencode_session_id"] = runner.session_id
                store.save_session(session)
    except Exception as exc:  # noqa: BLE001
        error = {"kind": "error", "message": f"Fallo interno del motor: {exc}"}
        _emit(entry, error)
    finally:
        entry["runner"] = None

    if session_id and session_id != session.get("opencode_session_id"):
        session["opencode_session_id"] = session_id
        store.save_session(session)

    answer = "\n\n".join(p for p in assistant_parts if p.strip()).strip()
    thinking_text = "\n\n".join(p for p in thinking_parts if p.strip()).strip()

    if entry.get("cancelled"):
        store.add_message(session, "system", "Turno cancelado desde el portal web.")
        _emit(entry, {"kind": "done", "cancelled": True, "session_id": session["id"]})
    else:
        if error:
            store.add_message(
                session, "system",
                f"Error: {error.get('message', 'desconocido')}",
            )
            _emit(entry, {"kind": "done", "error": error.get("message"),
                          "session_id": session["id"]})
        else:
            if not answer and tools:
                answer = "*(El agente ejecutó herramientas sin emitir texto final.)*"
            store.add_message(
                session, "assistant", answer, tools=tools,
                meta={
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "cost": cost,
                    "rc": rc,
                    "thinking": thinking_text[:20000],
                },
            )
            store.record_turn(
                session, tokens_in=tokens_in, tokens_out=tokens_out,
                cost=cost, tool_calls=len(tools),
            )
            _emit(entry, {
                "kind": "done",
                "session_id": session["id"],
                "opencode_session_id": session.get("opencode_session_id"),
                "answer": answer,
                "tools": len(tools),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost": cost,
                "rc": rc,
            })

    _emit(entry, {"kind": "eof"})
    entry["finished"] = time.time()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/api/chat/bootstrap")
async def chat_bootstrap():
    sessions = store.list_sessions()
    latest = store.latest_session()
    return JSONResponse({
        "sessions": sessions,
        "latest": latest["id"] if latest else None,
        "models": _models_payload(),
        "default_model": _default_model(),
        "store_dir": str(store.SESSIONS_DIR),
        "cwd": str(Path.home()),
    })


@router.get("/api/chat/sessions")
async def chat_sessions():
    return JSONResponse({"sessions": store.list_sessions()})


@router.post("/api/chat/sessions")
async def chat_new_session(payload: Optional[dict] = None):
    payload = payload or {}
    model_token = payload.get("model") or _default_model()
    try:
        model = resolve_model(model_token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session = store.new_session(
        model=model,
        agent=payload.get("agent") or "",
        cwd=payload.get("cwd") or str(Path.home()),
        title=payload.get("title") or "Nueva conversación",
        thinking=bool(payload.get("thinking")),
        auto=bool(payload.get("auto", True)),
    )
    return JSONResponse({"session": session})


@router.get("/api/chat/sessions/{session_id}")
async def chat_get_session(session_id: str):
    return JSONResponse({"session": _session_or_404(session_id)})


@router.patch("/api/chat/sessions/{session_id}")
async def chat_patch_session(session_id: str, payload: dict):
    session = _session_or_404(session_id)
    if "title" in payload and payload["title"]:
        session["title"] = str(payload["title"])[:120]
    if payload.get("model"):
        try:
            session["model"] = resolve_model(str(payload["model"]))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "agent" in payload:
        session["agent"] = str(payload["agent"] or "")
    settings = session.setdefault("settings", {})
    for key in ("thinking", "auto"):
        if key in payload:
            settings[key] = bool(payload[key])
    if payload.get("cwd"):
        session["cwd"] = str(Path(str(payload["cwd"])).expanduser())
    store.save_session(session)
    return JSONResponse({"session": session})


@router.delete("/api/chat/sessions/{session_id}")
async def chat_delete_session(session_id: str):
    if not store.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return JSONResponse({"deleted": session_id})


@router.post("/api/chat/upload")
async def chat_upload(payload: dict):
    name = str(payload.get("name") or "adjunto.bin")
    data = payload.get("data") or ""
    if "," in data and data.strip().startswith("data:"):
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Base64 inválido: {exc}") from exc
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Adjunto mayor a 25 MB")
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in name if c.isalnum() or c in "._- ").strip() or "adjunto.bin"
    target = UPLOADS_DIR / f"{int(time.time())}_{safe}"
    target.write_bytes(raw)
    return JSONResponse({"path": str(target), "name": safe, "bytes": len(raw)})


@router.post("/api/chat/send")
async def chat_send(payload: dict):
    session = _session_or_404(str(payload.get("session_id") or ""))
    raw_text = payload.get("text") or ""
    draft_id = str(payload.get("draft_id") or "").strip()
    draft_token = str(payload.get("draft_token") or payload.get("token") or "")

    # ------------------------------------------------------------------
    # Camino soberano: la petición viaja sellada desde la bóveda.
    # Sin token válido, revisión exacta y checksum intacto, NO se envía.
    # ------------------------------------------------------------------
    sealed = None
    if draft_id:
        revision = payload.get("revision")
        try:
            revision = int(revision) if revision is not None else None
        except (TypeError, ValueError):
            revision = None
        try:
            sealed = vault.claim_for_send(
                draft_id,
                draft_token,
                revision=revision,
                text=str(raw_text) if raw_text else None,
            )
        except vault.VaultError as exc:
            return JSONResponse(status_code=exc.status, content=exc.payload())
        text = (sealed.get("text") or "").strip()
    else:
        # Clientes legacy (TUI/CLI): no pueden robar una bóveda abierta.
        try:
            busy = [d for d in vault.active_drafts() if d.get("session_id") == session["id"]]
        except Exception:
            busy = []
        if busy:
            return JSONResponse(
                status_code=423,
                content={
                    "ok": False,
                    "code": "vault_locked",
                    "message": "La petición blindada de esta sesión está abierta en otro cliente.",
                    "active": busy,
                },
            )
        text = raw_text.strip()

    if not text:
        if sealed:
            try:
                vault.release(draft_id, draft_token)
            except vault.VaultError:
                pass
        raise HTTPException(status_code=400, detail="Mensaje vacío")
    files = [str(Path(f).expanduser()) for f in (payload.get("files") or []) if f]

    # Materializar cambios de configuración enviados por el cliente.
    if payload.get("model"):
        try:
            session["model"] = resolve_model(str(payload["model"]))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    settings = session.setdefault("settings", {})
    for key in ("thinking", "auto"):
        if key in payload:
            settings[key] = bool(payload[key])
    if "agent" in payload:
        session["agent"] = str(payload.get("agent") or "")
    store.save_session(session)

    display_text = text
    store.add_message(session, "user", display_text)

    run_id = "run_" + uuid.uuid4().hex[:12]
    entry = {
        "id": run_id,
        "session_id": session["id"],
        "queue": Queue(),
        "runner": None,
        "cancelled": False,
        "started": time.time(),
        "finished": None,
        "draft_id": draft_id or None,
    }
    with _RUNS_LOCK:
        RUNS[run_id] = entry
        # Poda de ejecuciones antiguas
        if len(RUNS) > 64:
            for key in sorted(RUNS, key=lambda k: RUNS[k]["started"])[:16]:
                if RUNS[key].get("finished"):
                    RUNS.pop(key, None)

    thread = threading.Thread(
        target=_execute_turn,
        args=(entry, session, text, files),
        daemon=True,
        name=f"ftlchat-{run_id}",
    )
    thread.start()

    # El texto ya está en manos de FTL: se archiva la bóveda y se libera
    # la compuerta de mantenimiento (no se interrumpen actualizaciones más
    # allá de la transmisión de la petición).
    if sealed:
        try:
            vault.attach_run(draft_id, run_id)
            vault.consume(draft_id, run_id=run_id)
        except vault.VaultError:
            pass

    return JSONResponse({
        "run_id": run_id,
        "session_id": session["id"],
        "model": session.get("model"),
        "sealed": bool(sealed),
        "draft_id": draft_id or None,
        "user_message": session.get("messages", [])[-1] if session.get("messages") else None,
    })


@router.get("/api/chat/stream/{run_id}")
async def chat_stream(run_id: str):
    entry = RUNS.get(run_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Ejecución no encontrada")

    def generate():
        yield "retry: 3000\n\n"
        while True:
            try:
                event = entry["queue"].get(timeout=15)
            except Empty:
                yield ": keepalive\n\n"
                continue
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            if event.get("kind") == "eof":
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/api/chat/cancel/{run_id}")
async def chat_cancel(run_id: str):
    entry = RUNS.get(run_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Ejecución no encontrada")
    entry["cancelled"] = True
    runner = entry.get("runner")
    if runner:
        try:
            runner.cancel()
        except Exception:
            pass
    return JSONResponse({"cancelled": run_id})


@router.get("/api/chat/export/{session_id}")
async def chat_export(session_id: str, fmt: str = "md"):
    session = _session_or_404(session_id)
    if fmt.lower() == "json":
        path = store.export_json(session)
        media = "application/json"
    else:
        path = store.export_markdown(session)
        media = "text/markdown"
    return Response(
        content=path.read_bytes(),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{path.name}"',
            "X-FTL-Path": str(path),
        },
    )


# ---------------------------------------------------------------------------
# Bóveda de petición inmutable (ventana que el sistema no puede modificar)
# ---------------------------------------------------------------------------
@router.post("/api/chat/composer/open")
async def composer_open(payload: dict, request: Request):
    """Abre (o reanuda) la bóveda exclusiva de una sesión."""
    session = _session_or_404(str(payload.get("session_id") or ""))
    text = str(payload.get("text") or "")
    draft_id = str(payload.get("draft_id") or "").strip()
    token = str(payload.get("draft_token") or payload.get("token") or "")

    if draft_id and token:
        try:
            revision = payload.get("revision")
            record = vault.heartbeat(
                draft_id,
                token,
                text=text if text else None,
                revision=int(revision) if revision is not None else None,
            )
            return JSONResponse({
                "ok": True,
                "resumed": True,
                "draft": record,
                "token": token,
                "gate": vault.gate_status(write=False),
            })
        except vault.VaultError:
            pass  # bóveda vencida o de otro cliente: se abre una nueva

    client_id = str(payload.get("client_id") or "web")[:120]
    meta = {
        "user_agent": (request.headers.get("user-agent") or "")[:300],
        "client_ip": (request.client.host if request.client else ""),
        "origin": (request.headers.get("origin") or "")[:200],
    }
    try:
        record = vault.acquire(
            session["id"],
            client_id=client_id,
            text=text,
            takeover=bool(payload.get("takeover")),
            meta=meta,
        )
    except vault.VaultError as exc:
        return JSONResponse(status_code=exc.status, content=exc.payload())

    return JSONResponse({
        "ok": True,
        "resumed": False,
        "draft": record,
        "token": record.pop("token", ""),
        "gate": vault.gate_status(write=False),
    })


@router.post("/api/chat/composer/heartbeat")
async def composer_heartbeat(payload: dict):
    """Renueva el candado y persiste el texto autoritativo."""
    revision = payload.get("revision")
    try:
        record = vault.heartbeat(
            str(payload.get("draft_id") or ""),
            str(payload.get("draft_token") or payload.get("token") or ""),
            text=payload.get("text"),
            revision=int(revision) if revision is not None else None,
        )
    except vault.VaultError as exc:
        return JSONResponse(status_code=exc.status, content=exc.payload())
    return JSONResponse({
        "ok": True,
        "draft": record,
        "gate": vault.gate_status(write=False),
    })


@router.post("/api/chat/composer/close")
async def composer_close(payload: dict):
    try:
        record = vault.release(
            str(payload.get("draft_id") or ""),
            str(payload.get("draft_token") or payload.get("token") or ""),
            keep=payload.get("keep", True) is not False,
        )
    except vault.VaultError as exc:
        return JSONResponse(status_code=exc.status, content=exc.payload())
    return JSONResponse({"ok": True, "draft": record, "gate": vault.gate_status(write=False)})


@router.get("/api/chat/composer/status")
async def composer_status():
    return JSONResponse(vault.status())


@router.get("/api/chat/composer/active")
async def composer_active():
    return JSONResponse({"ok": True, "active": vault.active_drafts(), "gate": vault.gate_status(write=False)})


@router.get("/api/chat/composer/recover")
async def composer_recover(session_id: str = ""):
    drafts = vault.recover(session_id or None)
    return JSONResponse({
        "ok": True,
        "drafts": drafts,
        "gate": vault.gate_status(write=False),
    })


# ---------------------------------------------------------------------------
# Historial unificado de TODAS las interacciones con FTL
# ---------------------------------------------------------------------------
@router.get("/api/chat/history")
async def chat_history(q: str = "", limit: int = 100, offset: int = 0, source: str = "all"):
    return JSONResponse(history.unified(q, limit=limit, offset=offset, source=source))


@router.get("/api/chat/history/stats")
async def chat_history_stats():
    return JSONResponse(history.stats())


@router.get("/api/chat/history/export")
async def chat_history_export(fmt: str = "md", source: str = "all", q: str = ""):
    if fmt.lower() == "json":
        payload = history.unified(q, limit=500, source=source)
        return Response(
            content=json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="historial_ftl_unificado.json"'},
        )
    path = history.export_markdown(source=source, query=q)
    return Response(
        content=path.read_bytes(),
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="{path.name}"',
            "X-FTL-Path": str(path),
        },
    )


@router.get("/chat", response_class=HTMLResponse)
@router.get("/chat/", response_class=HTMLResponse)
async def chat_page():
    return HTMLResponse(CHAT_HTML)


# ---------------------------------------------------------------------------
# Interfaz web (autocontenida: sin CDN, sin dependencias externas)
# ---------------------------------------------------------------------------
CHAT_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>FTL Quantum Chat · TON 618</title>
<style>
  :root{
    --bg:#04060c; --bg2:#070b14; --panel:rgba(10,16,28,.72); --panel2:rgba(14,22,38,.86);
    --cyan:#00ffcc; --purple:#bd93f9; --gold:#ffb86c; --blue:#7aa2f7; --green:#50fa7b;
    --red:#ff5555; --dim:#6272a4; --text:#dbe6f5;
    --mono:"JetBrains Mono","Fira Code","SFMono-Regular",ui-monospace,Consolas,monospace;
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{
    margin:0;background:var(--bg);color:var(--text);font-family:var(--mono);
    overflow:hidden;-webkit-font-smoothing:antialiased;
  }
  /* ---------- fondo cuásar ---------- */
  .cosmos{position:fixed;inset:0;z-index:0;overflow:hidden;background:
    radial-gradient(circle at 50% 42%, #0a1522 0%, #05080f 45%, #02040a 100%);}
  .stars,.stars2,.stars3{position:absolute;inset:-50%;background-repeat:repeat;
    animation:drift 240s linear infinite;opacity:.55}
  .stars{background-image:
    radial-gradient(1.4px 1.4px at 20% 30%, #fff 40%, transparent 41%),
    radial-gradient(1.1px 1.1px at 70% 60%, #cfe9ff 40%, transparent 41%),
    radial-gradient(1.6px 1.6px at 40% 80%, #fff 40%, transparent 41%),
    radial-gradient(1px 1px at 85% 15%, #9fd7ff 40%, transparent 41%);
    background-size:340px 340px, 480px 480px, 620px 620px, 260px 260px;}
  .stars2{background-image:
    radial-gradient(1px 1px at 12% 66%, #fff 40%, transparent 41%),
    radial-gradient(1.3px 1.3px at 63% 22%, #ffd9a8 40%, transparent 41%),
    radial-gradient(0.9px 0.9px at 33% 12%, #b9ffe9 40%, transparent 41%);
    background-size:520px 520px, 380px 380px, 700px 700px;animation-duration:420s;opacity:.4}
  .stars3{background-image:
    radial-gradient(1.2px 1.2px at 80% 80%, #fff 40%, transparent 41%),
    radial-gradient(1px 1px at 22% 44%, #cbb6ff 40%, transparent 41%);
    background-size:880px 880px, 560px 560px;animation-duration:600s;opacity:.32}
  @keyframes drift{from{transform:translate3d(0,0,0)}to{transform:translate3d(-14%,-9%,0)}}

  .quasar{position:absolute;left:50%;top:44%;width:min(120vmin,1100px);aspect-ratio:1;
    transform:translate(-50%,-50%);pointer-events:none;filter:saturate(1.1)}
  .disk{position:absolute;inset:0;border-radius:50%;
    background:conic-gradient(from 0deg,
      rgba(0,255,204,0) 0deg, rgba(0,255,204,.55) 38deg, rgba(122,162,247,.75) 92deg,
      rgba(189,147,249,.85) 150deg, rgba(255,184,108,.7) 210deg, rgba(0,255,204,.5) 275deg,
      rgba(0,255,204,0) 330deg, rgba(0,255,204,0) 360deg);
    -webkit-mask:radial-gradient(circle, transparent 27%, #000 34%, #000 52%, transparent 60%);
    mask:radial-gradient(circle, transparent 27%, #000 34%, #000 52%, transparent 60%);
    filter:blur(14px);animation:spin 34s linear infinite;opacity:.5}
  .disk2{position:absolute;inset:9%;border-radius:50%;
    background:conic-gradient(from 180deg, rgba(255,184,108,0) 0deg, rgba(255,184,108,.55) 60deg,
      rgba(0,255,204,.35) 140deg, rgba(189,147,249,.4) 220deg, rgba(255,184,108,0) 320deg);
    -webkit-mask:radial-gradient(circle, transparent 38%, #000 46%, #000 56%, transparent 62%);
    mask:radial-gradient(circle, transparent 38%, #000 46%, #000 56%, transparent 62%);
    filter:blur(22px);animation:spin 58s linear infinite reverse;opacity:.35}
  @keyframes spin{to{transform:rotate(360deg)}}
  .ring{position:absolute;left:50%;top:50%;width:52%;height:52%;transform:translate(-50%,-50%);
    border-radius:50%;border:1.5px solid rgba(0,255,204,.28);
    box-shadow:0 0 40px rgba(0,255,204,.18) inset,0 0 22px rgba(0,255,204,.16);
    animation:pulse 5.5s ease-in-out infinite}
  .ring.r2{width:63%;height:63%;border-color:rgba(189,147,249,.16);animation-delay:1.4s}
  .ring.r3{width:41%;height:41%;border-color:rgba(255,184,108,.2);animation-delay:2.6s}
  @keyframes pulse{0%,100%{opacity:.45;transform:translate(-50%,-50%) scale(1)}
    50%{opacity:.95;transform:translate(-50%,-50%) scale(1.035)}}
  .core{position:absolute;left:50%;top:50%;width:15%;aspect-ratio:1;transform:translate(-50%,-50%);
    border-radius:50%;background:radial-gradient(circle,#000 40%,#04070d 52%,rgba(0,255,204,.35) 66%,transparent 74%);
    box-shadow:0 0 60px 12px rgba(0,255,204,.22),0 0 140px 40px rgba(189,147,249,.12);
    animation:breathe 7s ease-in-out infinite}
  @keyframes breathe{0%,100%{box-shadow:0 0 55px 10px rgba(0,255,204,.18),0 0 120px 30px rgba(189,147,249,.1)}
    50%{box-shadow:0 0 85px 20px rgba(0,255,204,.3),0 0 180px 60px rgba(189,147,249,.18)}}
  .scan{position:absolute;inset:0;background:repeating-linear-gradient(180deg,
    rgba(255,255,255,.035) 0 1px, transparent 1px 3px);
    mix-blend-mode:overlay;animation:scan 9s linear infinite;opacity:.5}
  @keyframes scan{from{background-position:0 0}to{background-position:0 30px}}
  .vignette{position:absolute;inset:0;background:radial-gradient(circle at 50% 45%,
    transparent 30%, rgba(2,4,10,.55) 72%, rgba(2,4,10,.92) 100%)}

  /* ---------- estructura ---------- */
  .shell{position:relative;z-index:2;display:grid;grid-template-columns:326px 1fr;height:100vh;height:100dvh}
  aside{border-right:1px solid rgba(0,255,204,.14);background:linear-gradient(180deg,rgba(6,11,20,.92),rgba(5,9,16,.78));
    backdrop-filter:blur(14px);display:flex;flex-direction:column;min-height:0}
  .brand{padding:18px 18px 12px;border-bottom:1px solid rgba(0,255,204,.1)}
  .brand .mark{display:flex;align-items:center;gap:10px}
  .orb{width:26px;height:26px;border-radius:50%;flex:0 0 26px;
    background:radial-gradient(circle at 50% 50%,#000 34%,rgba(0,255,204,.85) 52%,rgba(189,147,249,.65) 68%,transparent 76%);
    box-shadow:0 0 18px rgba(0,255,204,.55);animation:pulse 4.2s ease-in-out infinite}
  .brand h1{margin:0;font-size:13px;letter-spacing:.22em;color:var(--cyan);font-weight:700}
  .brand small{display:block;margin-top:3px;font-size:10px;letter-spacing:.14em;color:var(--dim)}
  .newchat{margin:14px 16px 10px;padding:11px;border-radius:9px;cursor:pointer;text-align:center;
    border:1px solid rgba(0,255,204,.45);color:var(--cyan);background:rgba(0,255,204,.06);
    font-family:var(--mono);font-size:11.5px;letter-spacing:.16em;transition:.18s}
  .newchat:hover{background:rgba(0,255,204,.14);box-shadow:0 0 22px rgba(0,255,204,.22)}
  .side-actions{display:flex;gap:6px;padding:0 16px 4px;flex-wrap:wrap}
  .sidebtn{flex:1;min-width:120px;border:1px solid rgba(122,162,247,.26);background:rgba(10,16,28,.7);
    color:#9fb4d4;border-radius:8px;padding:7px 6px;font-family:var(--mono);font-size:9px;
    letter-spacing:.08em;cursor:pointer;transition:.15s}
  .sidebtn:hover{border-color:var(--cyan);color:var(--cyan);background:rgba(0,255,204,.07)}
  .side-label{padding:12px 18px 6px;font-size:9.5px;letter-spacing:.2em;color:var(--dim)}
  .sessions{flex:1;overflow-y:auto;padding:0 10px 10px;min-height:80px}
  .session{padding:9px 10px;border-radius:8px;cursor:pointer;display:flex;gap:8px;align-items:flex-start;
    border:1px solid transparent;transition:.15s;margin-bottom:2px}
  .session:hover{background:rgba(122,162,247,.1);border-color:rgba(122,162,247,.25)}
  .session.active{background:rgba(0,255,204,.09);border-color:rgba(0,255,204,.42)}
  .session .txt{flex:1;min-width:0}
  .session .t{font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#e6f0ff}
  .session .m{font-size:9.5px;color:var(--dim);margin-top:3px;white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis}
  .session .del{opacity:0;border:0;background:none;color:var(--red);cursor:pointer;font-size:13px;
    padding:0 2px;transition:.15s}
  .session:hover .del{opacity:.75}
  .session .del:hover{opacity:1}
  .config{padding:12px 16px 16px;border-top:1px solid rgba(0,255,204,.1);display:grid;gap:9px}
  .field{display:grid;gap:4px}
  .field label{font-size:9px;letter-spacing:.16em;color:var(--dim)}
  select,input[type=text]{width:100%;background:rgba(4,8,14,.9);color:var(--text);
    border:1px solid rgba(122,162,247,.28);border-radius:7px;padding:7px 8px;font-family:var(--mono);
    font-size:11px;outline:none;transition:.15s}
  select:focus,input[type=text]:focus{border-color:var(--cyan);box-shadow:0 0 0 2px rgba(0,255,204,.12)}
  .toggles{display:flex;gap:8px}
  .toggle{flex:1;padding:6px;border-radius:7px;text-align:center;font-size:10px;cursor:pointer;
    border:1px solid rgba(122,162,247,.28);color:var(--dim);transition:.15s;user-select:none}
  .toggle.on{border-color:rgba(0,255,204,.6);color:var(--cyan);background:rgba(0,255,204,.08)}
  .side-foot{padding:10px 16px 14px;font-size:9px;color:var(--dim);line-height:1.6;
    border-top:1px solid rgba(255,255,255,.05)}
  .side-foot b{color:var(--purple);font-weight:500}

  main{display:flex;flex-direction:column;min-width:0;min-height:0}
  .topbar{display:flex;align-items:center;gap:14px;padding:12px 22px;border-bottom:1px solid rgba(0,255,204,.12);
    background:rgba(5,9,16,.62);backdrop-filter:blur(12px)}
  .topbar .title{font-size:12px;letter-spacing:.1em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
    flex:1;color:#e9f3ff}
  .pill{display:flex;align-items:center;gap:7px;font-size:10px;letter-spacing:.12em;color:var(--dim);
    border:1px solid rgba(122,162,247,.24);border-radius:999px;padding:5px 11px;white-space:nowrap}
  .dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 10px var(--green)}
  .dot.busy{background:var(--gold);box-shadow:0 0 10px var(--gold);animation:blink .9s infinite}
  .dot.err{background:var(--red);box-shadow:0 0 10px var(--red)}
  @keyframes blink{50%{opacity:.25}}

  .messages{flex:1;overflow-y:auto;padding:26px 8% 12px;scroll-behavior:smooth}
  .msg{max-width:960px;margin:0 auto 20px;animation:rise .32s ease both}
  @keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
  .who{display:flex;align-items:center;gap:9px;font-size:9.5px;letter-spacing:.2em;margin-bottom:7px}
  .who .avatar{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;font-size:9px}
  .msg.user .who{color:var(--blue);justify-content:flex-end}
  .msg.user .who .avatar{background:rgba(122,162,247,.16);border:1px solid rgba(122,162,247,.5);color:var(--blue)}
  .msg.assistant .who{color:var(--cyan)}
  .msg.assistant .who .avatar{background:radial-gradient(circle,#000 30%,rgba(0,255,204,.9) 55%,rgba(189,147,249,.7) 72%,transparent 80%);
    box-shadow:0 0 12px rgba(0,255,204,.5)}
  .bubble{border-radius:12px;padding:14px 17px;font-size:13px;line-height:1.72;
    border:1px solid rgba(0,255,204,.2);background:linear-gradient(160deg,rgba(8,16,28,.92),rgba(6,11,20,.86));
    box-shadow:0 8px 28px rgba(0,0,0,.35)}
  .msg.user .bubble{border-color:rgba(122,162,247,.32);background:linear-gradient(160deg,rgba(20,30,52,.92),rgba(12,18,32,.88))}
  .msg.system .bubble{border-color:rgba(255,184,108,.35);background:rgba(28,20,10,.6);color:#ffd9b0;font-size:11.5px}
  .bubble p{margin:0 0 10px}.bubble p:last-child{margin:0}
  .bubble h1,.bubble h2,.bubble h3{margin:14px 0 8px;color:var(--cyan);font-size:14px;letter-spacing:.04em}
  .bubble ul,.bubble ol{margin:6px 0 10px;padding-left:22px}
  .bubble li{margin:3px 0}
  .bubble code{background:rgba(0,255,204,.08);border:1px solid rgba(0,255,204,.16);
    padding:1px 5px;border-radius:4px;font-size:11.5px;color:#9dffe6}
  .bubble pre{background:rgba(2,5,10,.92);border:1px solid rgba(122,162,247,.22);border-radius:8px;
    padding:11px 13px;overflow:auto;margin:10px 0;font-size:11.5px;line-height:1.55}
  .bubble pre code{background:none;border:0;padding:0;color:#c9e6ff}
  .bubble a{color:var(--gold)}
  .bubble blockquote{margin:8px 0;padding-left:12px;border-left:2px solid var(--purple);color:#c8b6ff}
  .caret::after{content:"▌";color:var(--cyan);animation:blink .85s steps(1) infinite;margin-left:2px}

  .thinking{border:1px solid rgba(189,147,249,.32);border-radius:9px;margin-bottom:10px;
    background:rgba(30,20,48,.42);overflow:hidden}
  .thinking summary{cursor:pointer;padding:8px 12px;font-size:10px;letter-spacing:.16em;color:var(--purple);
    list-style:none;user-select:none}
  .thinking summary::-webkit-details-marker{display:none}
  .thinking[open] summary{border-bottom:1px solid rgba(189,147,249,.22)}
  .thinking .body{padding:10px 13px;font-size:11.5px;line-height:1.65;color:#bfa9ef;white-space:pre-wrap}

  .tool{border:1px solid rgba(80,250,123,.28);border-radius:9px;margin-bottom:10px;
    background:rgba(6,18,12,.55);overflow:hidden}
  .tool summary{cursor:pointer;padding:8px 12px;font-size:10.5px;letter-spacing:.1em;color:var(--green);
    list-style:none;display:flex;gap:8px;align-items:center;user-select:none}
  .tool summary::-webkit-details-marker{display:none}
  .tool summary .badge{font-size:8.5px;letter-spacing:.14em;border:1px solid rgba(80,250,123,.4);
    border-radius:999px;padding:1px 7px;color:var(--green);opacity:.85}
  .tool .body{padding:9px 12px;border-top:1px solid rgba(80,250,123,.18);background:rgba(2,8,5,.6)}
  .tool .cmd{color:var(--gold);font-size:11.5px;margin-bottom:6px}
  .tool pre{margin:0;max-height:320px;overflow:auto;font-size:11px;line-height:1.55;color:#b9e8cd;white-space:pre-wrap}

  .empty{max-width:760px;margin:6vh auto;text-align:center;color:var(--dim)}
  .empty .big{width:120px;height:120px;margin:0 auto 22px;border-radius:50%;
    background:radial-gradient(circle,#000 26%,rgba(0,255,204,.85) 44%,rgba(189,147,249,.6) 60%,transparent 70%);
    box-shadow:0 0 60px rgba(0,255,204,.35);animation:pulse 4s ease-in-out infinite}
  .empty h2{color:var(--cyan);font-size:15px;letter-spacing:.2em;margin:0 0 8px}
  .empty p{font-size:11.5px;line-height:1.8;margin:0 0 20px}
  .chips{display:flex;flex-wrap:wrap;gap:8px;justify-content:center}
  .chip{border:1px solid rgba(122,162,247,.3);border-radius:999px;padding:7px 13px;font-size:10.5px;
    color:#c3d4ee;cursor:pointer;background:rgba(12,18,32,.8);transition:.16s}
  .chip:hover{border-color:var(--cyan);color:var(--cyan);box-shadow:0 0 16px rgba(0,255,204,.2)}

  .composer{padding:10px 8% 18px;background:linear-gradient(180deg,transparent,rgba(4,6,12,.85) 40%)}
  .composer .box{max-width:960px;margin:0 auto;border:1px solid rgba(0,255,204,.26);border-radius:14px;
    background:rgba(6,11,20,.9);backdrop-filter:blur(10px);box-shadow:0 10px 40px rgba(0,0,0,.5);
    transition:.2s}
  .composer .box:focus-within{border-color:rgba(0,255,204,.6);box-shadow:0 0 0 3px rgba(0,255,204,.08),0 10px 40px rgba(0,0,0,.55)}
  .attachments{display:flex;flex-wrap:wrap;gap:6px;padding:9px 12px 0}
  .att{display:flex;align-items:center;gap:6px;font-size:9.5px;color:var(--gold);
    border:1px solid rgba(255,184,108,.35);border-radius:999px;padding:3px 9px;background:rgba(40,28,12,.5)}
  .att button{border:0;background:none;color:var(--red);cursor:pointer;font-size:12px;padding:0}
  textarea{width:100%;border:0;outline:none;resize:none;background:transparent;color:var(--text);
    font-family:var(--mono);font-size:13px;line-height:1.6;padding:13px 15px 4px;max-height:190px;min-height:46px}
  textarea::placeholder{color:#4a5a78}
  .controls{display:flex;align-items:center;gap:8px;padding:6px 11px 10px}
  .iconbtn{border:1px solid rgba(122,162,247,.28);background:rgba(10,16,28,.8);color:#9fb4d4;
    border-radius:8px;padding:6px 10px;font-family:var(--mono);font-size:10.5px;cursor:pointer;transition:.15s;
    letter-spacing:.08em}
  .iconbtn:hover{border-color:var(--cyan);color:var(--cyan)}
  .iconbtn.danger{border-color:rgba(255,85,85,.4);color:var(--red)}
  .iconbtn.danger:hover{background:rgba(255,85,85,.12)}
  .spacer{flex:1}
  .send{border:1px solid rgba(0,255,204,.6);background:linear-gradient(120deg,rgba(0,255,204,.2),rgba(189,147,249,.18));
    color:var(--cyan);border-radius:9px;padding:8px 20px;font-family:var(--mono);font-size:11px;
    letter-spacing:.18em;cursor:pointer;transition:.18s;font-weight:700}
  .send:hover{box-shadow:0 0 22px rgba(0,255,204,.35)}
  .send:disabled{opacity:.4;cursor:not-allowed;box-shadow:none}
  .hint{max-width:960px;margin:7px auto 0;font-size:9px;color:#3f4d68;display:flex;gap:14px;justify-content:space-between}

  .wave{position:relative;height:2px;overflow:hidden;background:rgba(0,255,204,.1);opacity:0;transition:.3s}
  .wave.on{opacity:1}
  .wave::after{content:"";position:absolute;inset:0;width:40%;
    background:linear-gradient(90deg,transparent,var(--cyan),var(--purple),transparent);
    animation:sweep 1.1s linear infinite}
  @keyframes sweep{from{transform:translateX(-100%)}to{transform:translateX(350%)}}

  .toast{position:fixed;right:18px;bottom:18px;z-index:50;max-width:360px;padding:11px 15px;border-radius:9px;
    border:1px solid rgba(255,85,85,.5);background:rgba(30,8,12,.95);color:#ffc9c9;font-size:11px;
    opacity:0;transform:translateY(12px);transition:.25s;pointer-events:none;line-height:1.6}
  .toast.show{opacity:1;transform:none}
  .toast.ok{border-color:rgba(0,255,204,.5);background:rgba(6,26,22,.95);color:#b6ffef}
  ::-webkit-scrollbar{width:9px;height:9px}
  ::-webkit-scrollbar-track{background:rgba(255,255,255,.02)}
  ::-webkit-scrollbar-thumb{background:rgba(0,255,204,.22);border-radius:9px}
  ::-webkit-scrollbar-thumb:hover{background:rgba(0,255,204,.4)}

  /* ---------- bóveda de petición inmutable ---------- */
  .vaultPill{display:none;border-color:rgba(0,255,204,.55);color:var(--cyan);
    background:rgba(0,255,204,.08);animation:vaultPulse 2.4s ease-in-out infinite}
  .vaultPill.on{display:inline-flex;align-items:center;gap:6px}
  .vaultPill .lockico{font-size:10px}
  .vault-overlay{position:fixed;inset:0;z-index:40;display:flex;align-items:flex-end;justify-content:center;
    padding:0 10px 8px;pointer-events:none;opacity:0;visibility:hidden;transition:opacity .2s ease,visibility .2s}
  .vault-overlay.on{opacity:1;visibility:visible}
  body.vault-open .composer{display:none}
  .vault-panel{pointer-events:auto;width:min(1000px,100%);max-height:78vh;overflow:auto;
    border:1px solid rgba(0,255,204,.5);border-radius:16px;
    background:linear-gradient(180deg,rgba(6,16,26,.985),rgba(4,8,16,.995));
    box-shadow:0 0 0 1px rgba(0,255,204,.12),0 0 70px rgba(0,255,204,.16),0 24px 80px rgba(0,0,0,.8);
    transform:translateY(16px) scale(.995);transition:transform .24s cubic-bezier(.2,.9,.3,1)}
  .vault-overlay.on .vault-panel{transform:none}
  .vault-head{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid rgba(0,255,204,.16)}
  .vault-shield{width:26px;height:26px;border-radius:50%;display:grid;place-items:center;font-size:13px;
    color:#04110d;background:radial-gradient(circle at 35% 30%,#8bffe6,#00ffcc 60%,#00b894);
    box-shadow:0 0 18px rgba(0,255,204,.55);flex:none}
  .vault-title{font-size:10.5px;letter-spacing:.2em;color:var(--cyan);font-weight:700}
  .vault-sub{font-size:9px;color:#5f7397;letter-spacing:.06em;margin-top:2px}
  .vault-meta{margin-left:auto;display:flex;align-items:center;gap:9px;font-size:9px;color:#7f93b3;letter-spacing:.08em}
  .vault-meta b{color:var(--gold);font-weight:600}
  .vault-badge{border:1px solid rgba(0,255,204,.4);border-radius:999px;padding:2px 8px;
    color:var(--cyan);font-size:8.5px;letter-spacing:.14em;white-space:nowrap}
  .vault-badge.sending{border-color:rgba(255,184,108,.6);color:var(--gold)}
  .vault-close{border:1px solid rgba(255,85,85,.35);background:transparent;color:#ff8f8f;
    border-radius:7px;padding:4px 8px;font-family:var(--mono);font-size:9px;cursor:pointer;letter-spacing:.1em}
  .vault-close:hover{background:rgba(255,85,85,.12)}
  .vault-panel .composer{padding:0;background:none}
  .vault-panel .box{max-width:none;border:0;border-radius:0 0 14px 14px;
    background:transparent;box-shadow:none;backdrop-filter:none}
  .vault-panel .box:focus-within{box-shadow:none;border-color:transparent}
  .vault-panel .hint{display:none}
  .vault-foot{display:flex;align-items:center;gap:10px;padding:8px 14px 11px;border-top:1px solid rgba(0,255,204,.1);
    font-size:9px;color:#55688a;letter-spacing:.06em}
  .vault-foot .spacer{flex:1}
  .vault-foot b{color:#9fb4d4;font-weight:600}
  .vault-lockbox{display:flex;align-items:center;gap:7px;color:var(--cyan);font-size:9px;letter-spacing:.1em}
  .vault-lockbox .dotlive{width:6px;height:6px;border-radius:50%;background:var(--cyan);
    box-shadow:0 0 8px var(--cyan);animation:pulse 1.8s infinite}
  .vault-backdrop{position:fixed;inset:0;z-index:39;background:radial-gradient(circle at 50% 100%,rgba(0,20,18,.5),rgba(0,0,0,.55));
    opacity:0;visibility:hidden;transition:.2s;pointer-events:none;backdrop-filter:blur(1.5px)}
  .vault-backdrop.on{opacity:1;visibility:visible}

  /* ---------- historial unificado ---------- */
  .history-drawer{position:fixed;top:0;right:0;bottom:0;width:min(520px,100%);z-index:46;
    background:linear-gradient(180deg,rgba(7,12,22,.99),rgba(4,7,13,.995));
    border-left:1px solid rgba(122,162,247,.25);box-shadow:-30px 0 90px rgba(0,0,0,.75);
    transform:translateX(102%);transition:transform .26s cubic-bezier(.2,.9,.3,1);
    display:flex;flex-direction:column}
  .history-drawer.on{transform:none}
  .history-scrim{position:fixed;inset:0;z-index:44;background:rgba(2,4,9,.6);opacity:0;visibility:hidden;transition:.22s}
  .history-scrim.on{opacity:1;visibility:visible}
  .history-head{padding:14px 16px 10px;border-bottom:1px solid rgba(122,162,247,.14)}
  .history-head h3{margin:0;font-size:11px;letter-spacing:.2em;color:var(--blue)}
  .history-head p{margin:5px 0 0;font-size:9px;color:#526480;letter-spacing:.05em}
  .history-tools{display:flex;gap:7px;padding:10px 14px 4px;flex-wrap:wrap}
  .history-tools input{flex:1;min-width:140px;border:1px solid rgba(122,162,247,.25);border-radius:8px;
    background:rgba(8,14,26,.9);color:var(--text);font-family:var(--mono);font-size:11px;padding:7px 10px;outline:none}
  .history-tools input:focus{border-color:rgba(0,255,204,.5)}
  .hfilt{border:1px solid rgba(122,162,247,.25);background:rgba(10,16,28,.8);color:#8fa4c4;border-radius:999px;
    padding:5px 10px;font-family:var(--mono);font-size:9px;cursor:pointer;letter-spacing:.08em}
  .hfilt.on{border-color:var(--cyan);color:var(--cyan);background:rgba(0,255,204,.08)}
  .history-list{flex:1;overflow:auto;padding:8px 12px 24px}
  .hitem{border:1px solid rgba(122,162,247,.13);border-radius:10px;padding:9px 11px;margin-bottom:8px;
    background:rgba(9,14,25,.7);cursor:pointer;transition:.15s}
  .hitem:hover{border-color:rgba(0,255,204,.34);background:rgba(9,20,30,.85)}
  .hitem .hrow{display:flex;align-items:center;gap:7px;margin-bottom:5px;font-size:8.5px;
    letter-spacing:.1em;color:#5b6f8f}
  .hitem .hsrc{border-radius:999px;padding:1px 7px;border:1px solid rgba(122,162,247,.3);color:#9db3d6}
  .hitem .hsrc.chat{border-color:rgba(0,255,204,.4);color:var(--cyan)}
  .hitem .hsrc.terminal{border-color:rgba(255,184,108,.4);color:var(--gold)}
  .hitem .hsrc.tardis{border-color:rgba(189,147,249,.4);color:var(--purple)}
  .hitem .hsrc.vault{border-color:rgba(80,250,123,.4);color:var(--green)}
  .hitem .htitle{font-size:11px;color:#c7d6ea;margin-bottom:3px;line-height:1.45}
  .hitem .hprev{font-size:10px;color:#7286a5;line-height:1.55;max-height:42px;overflow:hidden}
  .hitem .hsid{font-size:8.5px;color:#44546f;margin-top:5px;letter-spacing:.04em}
  .history-foot{padding:9px 14px;border-top:1px solid rgba(122,162,247,.14);display:flex;gap:8px;align-items:center;
    font-size:9px;color:#4d5f7c}
  .hbtn{border:1px solid rgba(0,255,204,.35);background:rgba(0,255,204,.06);color:var(--cyan);border-radius:7px;
    padding:5px 9px;font-family:var(--mono);font-size:9px;cursor:pointer;letter-spacing:.08em}
  .hbtn:hover{background:rgba(0,255,204,.14)}

  /* aviso de borrador recuperado */
  .recover-banner{display:none;max-width:960px;margin:0 auto 6px;padding:7px 11px;border-radius:9px;
    border:1px solid rgba(255,184,108,.4);background:rgba(40,28,12,.65);color:#ffd9a8;font-size:10px;
    align-items:center;gap:9px;line-height:1.45}
  .recover-banner.on{display:flex}
  .recover-banner button{border:1px solid rgba(255,184,108,.5);background:transparent;color:var(--gold);
    border-radius:6px;padding:3px 8px;font-family:var(--mono);font-size:9px;cursor:pointer}

  @keyframes vaultPulse{0%,100%{box-shadow:0 0 0 rgba(0,255,204,0)}50%{box-shadow:0 0 18px rgba(0,255,204,.22)}}

  @media (max-width:900px){
    .shell{grid-template-columns:1fr}
    aside{position:fixed;inset:0 auto 0 0;width:300px;z-index:20;transform:translateX(-102%);
      transition:transform .25s ease}
    aside.open{transform:none;box-shadow:0 0 60px rgba(0,0,0,.8)}
    .messages{padding:18px 14px 10px}
    .composer{padding:8px 12px 14px}
    .hint{flex-direction:column;gap:3px}
    .hint span:last-child{display:none}
    textarea{font-size:12.5px}
    .menu-btn{display:inline-flex !important}
  }
  .menu-btn{display:none;border:1px solid rgba(0,255,204,.3);background:rgba(6,11,20,.8);color:var(--cyan);
    border-radius:8px;padding:5px 9px;cursor:pointer;font-family:var(--mono);font-size:11px}
</style>
</head>
<body>
<div class="cosmos">
  <div class="stars"></div><div class="stars2"></div><div class="stars3"></div>
  <div class="quasar">
    <div class="disk"></div><div class="disk2"></div>
    <div class="ring"></div><div class="ring r2"></div><div class="ring r3"></div>
    <div class="core"></div>
  </div>
  <div class="scan"></div><div class="vignette"></div>
</div>

<div class="shell">
  <aside id="sidebar">
    <div class="brand">
      <div class="mark"><div class="orb"></div>
        <div><h1>FTL QUANTUM CHAT</h1><small>TON 618 · NÚCLEO DE ACREACIÓN</small></div>
      </div>
    </div>
    <button class="newchat" id="newChat">＋ NUEVA CONVERSACIÓN</button>
    <div class="side-actions">
      <button class="sidebtn" id="vaultBtn">🛡 PETICIÓN BLINDADA</button>
      <button class="sidebtn" id="historyBtn">🕘 HISTORIAL GLOBAL</button>
    </div>
    <div class="side-label">SESIONES PERSISTENTES</div>
    <div class="sessions" id="sessions"></div>
    <div class="config">
      <div class="field"><label>MODELO</label><select id="modelSel"></select></div>
      <div class="field"><label>AGENTE OPENCODE</label>
        <input type="text" id="agentInput" placeholder="build · plan · (vacío)"></div>
      <div class="toggles">
        <div class="toggle" id="tgThink">🧠 THINKING</div>
        <div class="toggle on" id="tgAuto">⚡ AUTO</div>
      </div>
    </div>
    <div class="side-foot">
      núcleo <b>OpenCode</b> · persistencia <b>~/.config/ftl/chat</b><br>
      <span id="storeInfo">—</span>
    </div>
  </aside>

  <main>
    <div class="topbar">
      <button class="menu-btn" id="menuBtn">☰</button>
      <div class="title" id="topTitle">Nueva conversación</div>
      <div class="pill vaultPill" id="vaultPill"><span class="lockico">🛡</span><span id="vaultPillText">BÓVEDA ACTIVA</span></div>
      <div class="pill"><span class="dot" id="statusDot"></span><span id="statusText">EN LÍNEA</span></div>
      <div class="pill" id="tokenPill">↑0 ↓0</div>
    </div>
    <div class="wave" id="wave"></div>
    <div class="messages" id="messages"></div>
    <div class="composer">
      <div class="recover-banner" id="recoverBanner">
        <span>⚠ Hay un borrador no enviado recuperado de la bóveda.</span>
        <button id="recoverLoad">RESTAURAR</button>
        <button id="recoverDismiss">DESCARTAR</button>
      </div>
      <div class="box">
        <div class="attachments" id="atts"></div>
        <textarea id="input" rows="1" placeholder="Transmite una instrucción al núcleo…  (Enter envía · Shift+Enter salto de línea)"></textarea>
        <div class="controls">
          <button class="iconbtn" id="attachBtn">📎 ADJUNTAR</button>
          <button class="iconbtn" id="exportBtn">⇩ EXPORTAR</button>
          <div class="spacer"></div>
          <button class="iconbtn danger" id="cancelBtn" style="display:none">■ CANCELAR</button>
          <button class="send" id="sendBtn">ENVIAR ◉</button>
        </div>
      </div>
      <div class="hint"><span id="sessionHint">sesión —</span><span>Enter envía · Shift+Enter nueva línea · Ctrl+K foco</span></div>
    </div>
  </main>
</div>

<input type="file" id="filePicker" multiple style="display:none">
<div class="toast" id="toast"></div>

<!-- ================= BÓVEDA DE PETICIÓN INMUTABLE ================= -->
<div class="vault-backdrop" id="vaultBackdrop"></div>
<div class="vault-overlay" id="vaultOverlay" role="dialog" aria-modal="false"
     aria-label="Bóveda de petición inmutable">
  <div class="vault-panel" id="vaultPanel">
    <div class="vault-head">
      <div class="vault-shield">🛡</div>
      <div>
        <div class="vault-title" id="vaultTitle">BÓVEDA DE PETICIÓN · INMUTABLE</div>
        <div class="vault-sub" id="vaultSub">Ningún proceso, actualización o cliente puede modificar este texto.</div>
      </div>
      <div class="vault-meta">
        <span class="vault-badge" id="vaultState">ESCUDO ACTIVO</span>
        <span id="vaultTimer">—</span>
        <button class="vault-close" id="vaultClose" title="Guardar el borrador y cerrar">GUARDAR ✕</button>
      </div>
    </div>
    <div id="vaultSlot"></div>
    <div class="vault-foot">
      <span class="vault-lockbox"><span class="dotlive"></span><span id="vaultLockText">CANDADO EXCLUSIVO</span></span>
      <span>·</span><span id="vaultRev">rev 0</span>
      <span>·</span><span id="vaultChars">0 car.</span>
      <span>·</span><span id="vaultChecksum">sha256 —</span>
      <div class="spacer"></div>
      <span id="vaultHint">Ctrl+Enter envía · Esc guarda y cierra</span>
    </div>
  </div>
</div>

<!-- ================= HISTORIAL GLOBAL ================= -->
<div class="history-scrim" id="historyScrim"></div>
<aside class="history-drawer" id="historyDrawer" aria-label="Historial global FTL">
  <div class="history-head">
    <h3>HISTORIAL GLOBAL · TODAS LAS INTERACCIONES</h3>
    <p id="historySub">Memoria transversal: chat, consola, TARDIS y bóveda.</p>
  </div>
  <div class="history-tools">
    <input id="historySearch" placeholder="Buscar en la memoria FTL…" autocomplete="off">
    <button class="hfilt on" data-src="all">TODO</button>
    <button class="hfilt" data-src="chat">CHAT</button>
    <button class="hfilt" data-src="terminal">TERMINAL</button>
    <button class="hfilt" data-src="tardis">TARDIS</button>
    <button class="hfilt" data-src="vault">BÓVEDA</button>
  </div>
  <div class="history-list" id="historyList"></div>
  <div class="history-foot">
    <button class="hbtn" id="historyExport">⇩ EXPORTAR</button>
    <button class="hbtn" id="historyRefresh">↻ ACTUALIZAR</button>
    <div class="spacer"></div>
    <span id="historyCount">—</span>
  </div>
</aside>

<script>
const $ = (id) => document.getElementById(id);
const state = { session:null, sessions:[], models:[], busy:false, es:null, runId:null, files:[], streamBuf:"", composing:false, stick:true, sending:false };

/* ===================================================================
   BÓVEDA DE PETICIÓN INMUTABLE
   -------------------------------------------------------------------
   Mientras el Arquitecto redacta o transmite, ningún proceso del
   sistema puede alterar esta ventana. Triple defensa:
     1. Token exclusivo + revisión + checksum en el servidor.
     2. Interceptor del setter `value` + observador de mutaciones.
     3. Borrador espejo en localStorage y en disco (recuperable).
   =================================================================== */
const VAULT_LS = "ftl.chat.vault";
const DRAFT_KEY = "ftl.chat.draft";

function saveDraft(value){
  try{
    if(value && value.trim()) localStorage.setItem(DRAFT_KEY, value);
    else localStorage.removeItem(DRAFT_KEY);
  }catch(e){}
}
function loadDraft(){
  try{ return localStorage.getItem(DRAFT_KEY) || ""; }catch(e){ return ""; }
}

const Guard = {
  _native: Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value"),
  lastSeen: "",
  lastInputAt: 0,
  blocked: 0,
  allowWrite: false,
  _observer: null,
  input(){ return $("input"); },
  nativeGet(){ try{ return this._native.get.call(this.input()); }catch(e){ return ""; } },
  nativeSet(value){ try{ this._native.set.call(this.input(), value); this.lastSeen = value; }catch(e){} },
  write(value){
    this.allowWrite = true;
    try{ this.input().value = value; } finally { this.allowWrite = false; }
    this.lastSeen = value;
  },
  init(){
    const el = this.input();
    const native = this._native;
    this.lastSeen = native.get.call(el);
    try{
      Object.defineProperty(el, "value", {
        configurable: true,
        get(){ return native.get.call(this); },
        set(v){
          if(Vault.active && !Guard.allowWrite){
            Guard.blocked++;
            Guard.onBlocked();
            return;
          }
          native.set.call(this, (v === null || v === undefined) ? "" : String(v));
        }
      });
    }catch(e){}
    el.addEventListener("input", () => {
      Guard.lastSeen = Guard.nativeGet();
      Guard.lastInputAt = performance.now();
      if(Vault.active){
        Vault.text = Guard.lastSeen;
        Vault.render();
        Vault.storeLocal();
      }
    });
    // Observador: si algo reemplaza el nodo o inyecta texto, se restaura.
    this._observer = new MutationObserver(() => { if(Vault.active) Vault.verify(); });
    this._observer.observe(el, {attributes:true, childList:true, characterData:true, subtree:true});
    this._observer.observe($("vaultSlot"), {childList:true, subtree:true});
  },
  onBlocked(){
    if(Vault.active) Vault.onTamper("Bloqueo activo: un proceso intentó escribir en la ventana de petición.");
  }
};

const Vault = {
  active:false, opening:false, frozen:false,
  draftId:null, token:null, revision:0,
  text:"", checksum:"", expiresAt:0,
  timer:null, hbTimer:null, saving:false, savingPromise:null,
  tamper:0, _tamperAt:0, _overlay:null, _panel:null, _origin:null,

  initDom(){
    this._overlay = $("vaultOverlay");
    this._panel = $("vaultPanel");
    this._origin = document.querySelector(".composer");
    Guard.init();
  },

  clientId(){
    try{
      let id = localStorage.getItem("ftl.chat.client");
      if(!id){ id = "web_" + Math.random().toString(36).slice(2, 12); localStorage.setItem("ftl.chat.client", id); }
      return id;
    }catch(e){ return "web"; }
  },

  stored(){
    try{ return JSON.parse(localStorage.getItem(VAULT_LS) || "null") || {}; }catch(e){ return {}; }
  },

  storeLocal(extra){
    try{
      if(this.text && this.text.trim()){
        localStorage.setItem(VAULT_LS, JSON.stringify({
          draft_id:this.draftId, token:this.token, text:this.text,
          revision:this.revision, session_id:state.session ? state.session.id : null,
          ts:Date.now(), ...(extra||{})
        }));
        localStorage.setItem(DRAFT_KEY, this.text);
      } else {
        localStorage.removeItem(VAULT_LS);
        localStorage.removeItem(DRAFT_KEY);
      }
    }catch(e){}
  },

  mount(){
    if(!this._overlay || !this._panel){ this.initDom(); }
    const box = document.querySelector(".composer .box");
    if(box && !$("vaultSlot").contains(box)) $("vaultSlot").appendChild(box);
    document.body.classList.add("vault-open");
    this._overlay.classList.add("on");
    $("vaultBackdrop").classList.add("on");
    $("vaultPill").classList.add("on");
    this.updatePill();
    setTimeout(() => {
      const el = $("input");
      try{ el.focus({preventScroll:true}); el.setSelectionRange(el.value.length, el.value.length); }catch(e){}
    }, 60);
  },

  unmount(){
    const box = document.querySelector("#vaultSlot .box");
    if(box && this._origin){
      const hint = this._origin.querySelector(".hint");
      if(hint) this._origin.insertBefore(box, hint); else this._origin.appendChild(box);
    }
    document.body.classList.remove("vault-open");
    if(this._overlay) this._overlay.classList.remove("on");
    $("vaultBackdrop").classList.remove("on");
    $("vaultPill").classList.remove("on");
  },

  async open(opts){
    opts = opts || {};
    if(this.opening) return;
    if(this.active){ this.mount(); return; }
    this.opening = true;
    try{
      if(!state.session) await newSession();
      if(!state.session) throw new Error("No hay sesión activa.");
      const resume = this.stored();
      const text = (opts.text !== undefined && opts.text !== null) ? opts.text : (Guard.nativeGet() || loadDraft() || "");
      const body = {
        session_id: state.session.id,
        text,
        client_id: this.clientId(),
        takeover: !!opts.takeover
      };
      if(resume && resume.token && resume.draft_id && resume.session_id === state.session.id){
        body.draft_id = resume.draft_id;
        body.draft_token = resume.token;
        body.revision = resume.revision || 0;
      }
      const r = await fetch("/api/chat/composer/open", {
        method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)
      });
      const d = await r.json().catch(() => ({}));
      if(!r.ok){
        if(r.status === 423 && d.active){
          const ok = confirm("Otra ventana posee la bóveda de esta sesión.\n\n¿Tomar el control? La otra ventana quedará bloqueada.");
          this.opening = false;
          if(ok) return this.open({...opts, takeover:true});
          return;
        }
        throw new Error(d.message || d.detail || "No se pudo abrir la bóveda.");
      }
      this.active = true;
      this.frozen = false;
      this.draftId = d.draft.draft_id;
      this.token = d.token;
      this.revision = d.draft.revision || 0;
      const base = d.draft.text !== undefined ? d.draft.text : text;
      const live = Guard.nativeGet();
      // Preserva las teclas pulsadas mientras viajaba la petición de apertura.
      this.text = (live && live.length > base.length && live.startsWith(base)) ? live : base;
      this.checksum = d.draft.checksum || "";
      this.expiresAt = Date.now() + ((d.draft.expires_in || 120) * 1000);
      Guard.write(this.text);
      autoGrow();
      this.storeLocal();
      this.mount();
      this.render();
      this.startTimers();
      if(!opts.silent && !d.resumed) toast("🛡 Bóveda abierta · la petición ya no puede ser modificada por el sistema.", true);
    }catch(err){
      if(!opts.silent) toast("✖ " + err.message);
      console.warn("[vault]", err);
    }finally{
      this.opening = false;
    }
  },

  startTimers(){
    this.stopTimers();
    this.timer = setInterval(() => this.tick(), 1000);
    this.hbTimer = setInterval(() => this.persist(false), 2500);
  },
  stopTimers(){
    if(this.timer){ clearInterval(this.timer); this.timer = null; }
    if(this.hbTimer){ clearInterval(this.hbTimer); this.hbTimer = null; }
  },
  tick(){
    if(!this.active) return;
    const left = Math.max(0, Math.round((this.expiresAt - Date.now()) / 1000));
    $("vaultTimer").textContent = left > 0 ? left + "s" : "renovando…";
    this.updatePill(left);
    this.verify();
    if(left <= 0) this.persist(true);
  },
  updatePill(left){
    if(!this.active){ $("vaultPill").classList.remove("on"); return; }
    $("vaultPill").classList.add("on");
    const secs = (left !== undefined) ? left : Math.max(0, Math.round((this.expiresAt - Date.now()) / 1000));
    $("vaultPillText").textContent = this.frozen ? "SELLANDO…" : "BÓVEDA " + secs + "s";
  },

  render(){
    if(!this.active) return;
    $("vaultRev").textContent = "rev " + this.revision;
    $("vaultChars").textContent = (this.text || "").length + " car.";
    $("vaultChecksum").textContent = "sha256 " + (this.checksum || "—").slice(0, 10);
    $("vaultState").textContent = this.frozen ? "SELLANDO" : "ESCUDO ACTIVO";
    $("vaultState").classList.toggle("sending", !!this.frozen);
    $("vaultClose").style.display = this.frozen ? "none" : "";
  },

  async persist(force){
    if(!this.active || this.frozen) return;
    if(this.savingPromise) return this.savingPromise;
    const el = Guard.input();
    const text = Guard.nativeGet();
    this.text = text;
    this.savingPromise = (async () => {
      this.saving = true;
      try{
        const r = await fetch("/api/chat/composer/heartbeat", {
          method:"POST", headers:{"Content-Type":"application/json"},
          body: JSON.stringify({
            draft_id:this.draftId, draft_token:this.token,
            text, revision:this.revision
          })
        });
        const d = await r.json().catch(() => ({}));
        if(r.ok && d.draft){
          this.revision = d.draft.revision || 0;
          this.checksum = d.draft.checksum || "";
          this.expiresAt = Date.now() + ((d.draft.expires_in || 120) * 1000);
          if((d.draft.text || "") !== Guard.nativeGet()){
            // El servidor tiene un texto distinto: restauración autoritativa.
            this.text = d.draft.text || "";
            Guard.write(this.text);
            autoGrow();
            this.onTamper("El texto de la bóveda fue restaurado desde el servidor.");
          }
          this.storeLocal();
          this.render();
        } else if(r.status === 409){
          this.tamper++;
          const auth = d.authoritative;
          this.onTamper(d.message || "Modificación externa detectada.");
          if(auth && typeof auth.text === "string" && auth.text){
            this.text = auth.text;
            this.revision = auth.revision || this.revision;
            Guard.write(this.text);
            autoGrow();
          }
        } else if(r.status === 403 || r.status === 404){
          this.active = false;
          this.stopTimers();
          this.unmount();
          toast("✖ La bóveda dejó de ser tuya: " + (d.message || "token invalidado"));
        }
      }catch(e){
        // Sin red: el borrador local sigue siendo la verdad. La bóveda
        // expirará en el servidor, pero nada se pierde.
      }finally{
        this.saving = false;
        this.savingPromise = null;
      }
    })();
    return this.savingPromise;
  },

  verify(){
    if(!this.active) return;
    // 1. Ventana eliminada o reemplazada por otro proceso → remontar.
    if(this._overlay && !document.body.contains(this._overlay)){
      try{
        document.body.appendChild(this._overlay);
        this.mount();
        Guard.write(this.text);
        this.onTamper("La ventana fue retirada del DOM; se restauró automáticamente.");
        return;
      }catch(e){}
    }
    // 2. Escritura externa en el textarea.
    const native = Guard.nativeGet();
    if(native !== Guard.lastSeen){
      const recent = (performance.now() - Guard.lastInputAt) < 1500;
      if(recent){
        Guard.lastSeen = native;
        this.text = native;
      } else {
        Guard.nativeSet(Guard.lastSeen);
        this.onTamper("Se detectó una escritura externa; el texto original fue restaurado.");
      }
    }
  },

  onTamper(message){
    this.tamper++;
    $("vaultSub").textContent = "⚠ " + message;
    $("vaultSub").style.color = "#ffb86c";
    if(Date.now() - this._tamperAt > 4000){
      this._tamperAt = Date.now();
      toast("🛡 " + message);
    }
  },

  async close(keep){
    if(!this.active){ this.unmount(); return; }
    if(this.frozen) return;
    await this.persist(true).catch(() => {});
    try{
      await fetch("/api/chat/composer/close", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({draft_id:this.draftId, draft_token:this.token, keep:keep !== false})
      });
    }catch(e){}
    this.active = false;
    this.stopTimers();
    this.storeLocal();
    this.unmount();
    toast("🛡 Bóveda cerrada · el borrador queda guardado y recuperable.", true);
  },

  freeze(on){
    this.frozen = !!on;
    const el = Guard.input();
    el.readOnly = !!on;
    $("vaultState").textContent = on ? "SELLANDO" : "ESCUDO ACTIVO";
    $("vaultState").classList.toggle("sending", !!on);
    $("vaultLockText").textContent = on ? "TRANSMITIENDO · NO CERRAR" : "CANDADO EXCLUSIVO";
    $("vaultClose").style.display = on ? "none" : "";
    this.updatePill();
  },

  sent(){
    // Sólo tras el 200 del servidor: el texto ya está en FTL.
    this.active = false;
    this.frozen = false;
    this.stopTimers();
    this.text = "";
    this.draftId = null;
    this.token = null;
    this.revision = 0;
    this.checksum = "";
    try{ localStorage.removeItem(VAULT_LS); localStorage.removeItem(DRAFT_KEY); }catch(e){}
    Guard.write("");
    autoGrow();
    this.unmount();
  }
};

/* ---------------- historial global ---------------- */
const Hist = { open:false, source:"all", query:"", timer:null, loading:false };

function histBadge(source){
  return ({chat:"CHAT", terminal:"TERMINAL", tardis:"TARDIS", vault:"BÓVEDA"})[source] || source.toUpperCase();
}

function histItem(row){
  const badge = histBadge(row.source);
  const when = (row.iso || "").replace("T", " ").slice(0, 16);
  return `<div class="hitem" data-id="${esc(row.id)}" data-session="${esc(row.session_id || "")}" data-src="${esc(row.source)}">
    <div class="hrow"><span class="hsrc ${esc(row.source)}">${esc(badge)}</span>
      <span>${esc(when)}</span><span>·</span><span>${esc(row.role || "")}</span>
      ${row.model ? `<span>·</span><span>${esc(shortModel(row.model))}</span>` : ""}</div>
    <div class="htitle">${esc(row.title || "")}</div>
    <div class="hprev">${esc(row.preview || "")}</div>
    ${row.session_id ? `<div class="hsid">sesión ${esc(row.session_id)}</div>` : ""}
  </div>`;
}

async function historyLoad(){
  if(Hist.loading) return;
  Hist.loading = true;
  try{
    const params = new URLSearchParams({q:Hist.query, source:Hist.source, limit:"120"});
    const r = await fetch("/api/chat/history?" + params.toString());
    const d = await r.json();
    const list = $("historyList");
    if(!d.entries || !d.entries.length){
      list.innerHTML = `<div style="padding:26px 12px;text-align:center;color:#4d5f7c;font-size:10.5px;line-height:1.8">
        Sin interacciones que coincidan.<br>La memoria transversal se llena con cada chat, consola y operación TARDIS.</div>`;
    } else {
      list.innerHTML = d.entries.map(histItem).join("");
      list.querySelectorAll(".hitem").forEach(el => {
        el.addEventListener("click", () => {
          if(el.dataset.session){ closeHistory(); openSession(el.dataset.session); }
          else el.classList.toggle("expanded");
        });
      });
    }
    $("historyCount").textContent = (d.total || 0) + " interacciones";
    $("historySub").textContent = "Memoria transversal · " +
      Object.entries(d.counts || {}).map(([k,v]) => k + " " + v).join(" · ");
  }catch(e){
    $("historyList").innerHTML = `<div style="padding:20px;color:#ff8f8f;font-size:10.5px">✖ ${esc(e.message)}</div>`;
  }finally{
    Hist.loading = false;
  }
}

function openHistory(){
  Hist.open = true;
  $("historyDrawer").classList.add("on");
  $("historyScrim").classList.add("on");
  historyLoad();
  setTimeout(() => $("historySearch").focus(), 120);
}
function closeHistory(){
  Hist.open = false;
  $("historyDrawer").classList.remove("on");
  $("historyScrim").classList.remove("on");
}

function esc(s){ return (s??"").toString().replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function md(src){
  if(!src) return "";
  const blocks = [];
  let text = src.replace(/```([\s\S]*?)```/g, (m, code) => {
    blocks.push("<pre><code>"+esc(code.replace(/^\n/,""))+"</code></pre>");
    return "\u0000B"+(blocks.length-1)+"\u0000";
  });
  text = esc(text);
  text = text.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  text = text.replace(/^###\s+(.*)$/gm, "<h3>$1</h3>")
             .replace(/^##\s+(.*)$/gm, "<h2>$1</h2>")
             .replace(/^#\s+(.*)$/gm, "<h1>$1</h1>");
  text = text.replace(/^\s*&gt;\s?(.*)$/gm, "<blockquote>$1</blockquote>");
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
             .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  text = text.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  text = text.replace(/^\s*[-*]\s+(.*)$/gm, "<li>$1</li>");
  text = text.replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, "<ul>$1</ul>");
  text = text.split(/\n{2,}/).map(p => /^\s*<(h\d|ul|pre|blockquote)/.test(p.trim()) ? p : "<p>"+p.replace(/\n/g,"<br>")+"</p>").join("");
  text = text.replace(/\u0000B(\d+)\u0000/g, (m,i)=> blocks[+i]);
  return text;
}

function toast(msg, ok){
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (ok ? " ok" : "");
  clearTimeout(t._t);
  t._t = setTimeout(()=> t.className = "toast" + (ok ? " ok" : ""), 6000);
}

function setStatus(kind, text){
  $("statusDot").className = "dot" + (kind === "busy" ? " busy" : kind === "err" ? " err" : "");
  $("statusText").textContent = text;
}

function shortModel(ref){
  if(!ref) return "—";
  const [base, variant] = ref.split("#");
  return base.split("/").pop() + (variant ? "#"+variant : "");
}

function fmtDate(iso){
  if(!iso) return "";
  return iso.replace("T"," ").slice(0,16);
}

/* ---------------- sesiones ---------------- */
async function boot(){
  const r = await fetch("/api/chat/bootstrap");
  const data = await r.json();
  state.models = data.models || [];
  state.sessions = data.sessions || [];
  $("storeInfo").textContent = data.store_dir || "";
  $("modelSel").innerHTML = state.models.map(m => {
    const bad = (m.available === false) || (m.enabled === false);
    return `<option value="${esc(m.key)}" ${bad ? "disabled" : ""}>${esc(m.key)} · ${esc(m.ref.split("/").pop())}${m.latency_s ? " · "+m.latency_s+"s" : ""}${bad ? " · no disponible" : ""}</option>`;
  }).join("");
  renderSessions();
  const target = data.latest;
  if(target){ await openSession(target); }
  else { await newSession(); }
  await restoreDraft();
}

/* Recuperación de la bóveda: recarga, caída del portal o reinicio del sistema. */
async function restoreDraft(){
  Vault.initDom();
  const local = loadDraft();
  if(local && !Guard.nativeGet()){ Guard.write(local); autoGrow(); }

  let serverDraft = null;
  try{
    const qs = state.session ? ("?session_id=" + encodeURIComponent(state.session.id)) : "";
    const r = await fetch("/api/chat/composer/recover" + qs);
    const d = await r.json();
    if(d.drafts && d.drafts.length) serverDraft = d.drafts[0];
  }catch(e){}

  const stored = Vault.stored();
  if(stored && stored.token && stored.draft_id && (!state.session || stored.session_id === state.session.id)){
    await Vault.open({silent:true});
    if(Vault.active) return;
  }

  if(serverDraft && serverDraft.text && !Guard.nativeGet()){
    Guard.write(serverDraft.text);
    autoGrow();
    state.recovered = serverDraft;
    $("recoverBanner").classList.add("on");
    $("vaultSub").textContent = "Borrador recuperado de la bóveda · pulsa el escudo para blindarlo de nuevo.";
  }
}

function renderSessions(){
  const box = $("sessions");
  if(!state.sessions.length){ box.innerHTML = `<div style="padding:14px;color:#3f4d68;font-size:10.5px">Sin sesiones todavía.</div>`; return; }
  box.innerHTML = state.sessions.map(s => `
    <div class="session ${state.session && state.session.id === s.id ? "active" : ""}" data-id="${esc(s.id)}">
      <div class="txt">
        <div class="t">${esc(s.title || "Nueva conversación")}</div>
        <div class="m">${esc(shortModel(s.model))} · ${s.message_count || 0} msj · ${esc(fmtDate(s.updated_at))}</div>
      </div>
      <button class="del" data-del="${esc(s.id)}" title="Eliminar">✕</button>
    </div>`).join("");
  box.querySelectorAll(".session").forEach(el => {
    el.addEventListener("click", async (ev) => {
      if(ev.target.dataset.del) return;
      await openSession(el.dataset.id);
      $("sidebar").classList.remove("open");
    });
  });
  box.querySelectorAll(".del").forEach(btn => {
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const id = btn.dataset.del;
      if(!confirm("¿Eliminar la sesión " + id + "?")) return;
      await fetch("/api/chat/sessions/"+id, {method:"DELETE"});
      state.sessions = state.sessions.filter(s => s.id !== id);
      if(state.session && state.session.id === id) await newSession();
      else renderSessions();
      toast("Sesión eliminada.", true);
    });
  });
}

async function newSession(){
  if(Vault.active && Vault.text.trim()){
    if(!confirm("Hay una petición blindada sin enviar. ¿Cerrar la bóveda y crear otra conversación?")) return;
    await Vault.close(true);
  }
  const r = await fetch("/api/chat/sessions", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({model: $("modelSel").value || null, agent: $("agentInput").value.trim()})});
  const data = await r.json();
  state.session = data.session;
  state.files = [];
  renderSessions(); applySession(); renderMessages();
  $("input").focus();
}

async function openSession(id){
  if(state.session && state.session.id === id){
    renderSessions(); applySession(); renderMessages(); return;
  }
  if(Vault.active && Vault.text.trim()){
    if(!confirm("Hay una petición blindada sin enviar. ¿Cerrar la bóveda y abrir otra sesión?")) return;
    await Vault.close(true);
  }
  const r = await fetch("/api/chat/sessions/"+id);
  if(!r.ok) return;
  const data = await r.json();
  state.session = data.session;
  state.files = [];
  renderSessions(); applySession(); renderMessages();
}

function applySession(){
  const s = state.session;
  if(!s) return;
  $("topTitle").textContent = s.title || "Nueva conversación";
  $("sessionHint").textContent = "sesión " + s.id + (s.opencode_session_id ? " · opencode " + s.opencode_session_id : " · opencode pendiente");
  const key = (s.model || "").split("/").pop().split("#")[0];
  const match = state.models.find(m => m.ref === s.model || m.key === key);
  if(match) $("modelSel").value = match.key;
  $("agentInput").value = s.agent || "";
  const st = s.settings || {};
  $("tgThink").classList.toggle("on", !!st.thinking);
  $("tgAuto").classList.toggle("on", st.auto !== false);
  const stats = s.stats || {};
  $("tokenPill").textContent = "↑"+(stats.tokens_in||0)+" ↓"+(stats.tokens_out||0);
  renderAtts();
}

/* ---------------- mensajes ---------------- */
function addShell(role){
  const wrap = document.createElement("div");
  wrap.className = "msg " + role;
  const who = role === "user" ? "ARQUITECTO" : role === "system" ? "SISTEMA" : "FTL · NÚCLEO";
  wrap.innerHTML = `<div class="who"><span class="avatar">${role==="user"?"◇":role==="system"?"!":"◉"}</span>${who}</div>
    <div class="bubble"></div>`;
  $("messages").appendChild(wrap);
  scrollBottom();
  return wrap.querySelector(".bubble");
}

function toolCard(t){
  const card = document.createElement("details");
  card.className = "tool";
  const inp = t.input || {};
  const head = inp.command ? "$ " + inp.command
             : (inp.path || inp.filePath) ? (t.tool + ": " + (inp.path || inp.filePath))
             : (t.tool || "tool");
  const out = (t.output || "").slice(0, 6000);
  card.innerHTML = `<summary>⚙ ${esc(t.tool || "tool")} <span class="badge">${esc(t.status || "")}</span></summary>
    <div class="body"><div class="cmd">${esc(head.slice(0,600))}</div><pre>${esc(out || "(sin salida)")}</pre></div>`;
  return card;
}

function renderMessages(){
  const box = $("messages");
  box.innerHTML = "";
  const s = state.session;
  if(!s || !(s.messages || []).length){
    box.innerHTML = `<div class="empty">
      <div class="big"></div>
      <h2>NÚCLEO CUÁNTICO EN LÍNEA</h2>
      <p>Sesión persistente <b style="color:#bd93f9">${esc(s ? s.id : "—")}</b> anclada al horizonte de sucesos.<br>
      Todo lo que transmitas quedará grabado y podrá reanudarse desde terminal o navegador.</p>
      <div class="chips">
        <div class="chip" data-p="Explícame la arquitectura de este sistema y sus subsistemas activos.">Arquitectura del sistema</div>
        <div class="chip" data-p="Ejecuta un diagnóstico de salud: CPU, memoria, disco, servicios activos y kernel.">Diagnóstico de salud</div>
        <div class="chip" data-p="Revisa el directorio actual y propón las tres mejoras más importantes.">Auditar directorio</div>
        <div class="chip" data-p="¿Qué skills soberanas tengo disponibles y para qué sirve cada una?">Skills soberanas</div>
      </div>
    </div>`;
    box.querySelectorAll(".chip").forEach(c => c.addEventListener("click", ()=>{
      Guard.write(c.dataset.p); autoGrow(); saveDraft(c.dataset.p);
      if(Vault.active) { Vault.text = c.dataset.p; Vault.persist(true); Vault.mount(); }
      else Vault.open({silent:true, text:c.dataset.p});
      $("input").focus();
    }));
    return;
  }
  for(const m of s.messages){
    if(m.role === "system"){
      addShell("system").innerHTML = md(m.content || "");
      continue;
    }
    if(m.role === "user"){
      addShell("user").innerHTML = md(m.content || "");
      continue;
    }
    // assistant
    const bubble = addShell("assistant");
    const holder = document.createElement("div");
    const meta = m.meta || {};
    if(meta.thinking){
      const th = document.createElement("details");
      th.className = "thinking";
      th.innerHTML = `<summary>🧠 RAZONAMIENTO · horizonte de sucesos</summary><div class="body">${esc(meta.thinking)}</div>`;
      holder.appendChild(th);
    }
    (m.tools || []).forEach(t => holder.appendChild(toolCard(t)));
    const mdBox = document.createElement("div");
    mdBox.innerHTML = md(m.content || "");
    holder.appendChild(mdBox);
    bubble.appendChild(holder);
  }
  scrollBottom();
}

function nearBottom(){
  const box = $("messages");
  return box.scrollHeight - box.scrollTop - box.clientHeight < 120;
}

function scrollBottom(force){
  const box = $("messages");
  if(force === true) state.stick = true;
  if(state.stick) box.scrollTop = box.scrollHeight;
}

/* El scroll del usuario manda: si sube a leer, el streaming no lo devuelve al fondo. */
$("messages").addEventListener("scroll", () => { state.stick = nearBottom(); }, {passive:true});

/* ---------------- envío / streaming ---------------- */
async function send(){
  if(state.busy || state.sending || state.composing) return;
  const text = Guard.nativeGet().trim();
  if(!text) return;
  if(!state.session) await newSession();
  if(state.busy) return;

  // Toda petición se sella en la bóveda antes de viajar a FTL.
  if(!Vault.active){
    await Vault.open({silent:true, text:Guard.nativeGet()});
    if(!Vault.active){
      toast("✖ La bóveda no pudo abrirse: la petición no se envió (texto intacto).");
      return;
    }
  }
  await Vault.persist(true);
  if(Vault.frozen) return;

  const snapshot = Guard.nativeGet();
  if(!snapshot.trim()) return;

  Vault.freeze(true);
  state.sending = true;
  state.busy = true;
  state.streamBuf = "";
  state.stick = true;
  $("sendBtn").disabled = true;
  $("cancelBtn").style.display = "inline-flex";
  $("wave").classList.add("on");
  setStatus("busy", "ACELERANDO");

  const bubble = addShell("assistant");
  const holder = document.createElement("div");
  bubble.appendChild(holder);
  const mdBox = document.createElement("div");
  mdBox.className = "caret";
  holder.appendChild(mdBox);
  const pendingTools = [];
  const pendingThink = [];

  try{
    const r = await fetch("/api/chat/send", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        session_id: state.session.id,
        text: snapshot,
        files: state.files,
        model: $("modelSel").value || undefined,
        agent: $("agentInput").value.trim(),
        thinking: $("tgThink").classList.contains("on"),
        auto: $("tgAuto").classList.contains("on"),
        draft_id: Vault.draftId,
        draft_token: Vault.token,
        revision: Vault.revision,
      })});
    const data = await r.json().catch(() => ({}));
    if(!r.ok){
      if(data.authoritative){
        Vault.text = data.authoritative.text || Vault.text;
        Vault.revision = data.authoritative.revision || Vault.revision;
        Guard.write(Vault.text);
        autoGrow();
      }
      throw new Error(data.message || data.detail || "Fallo al enviar");
    }

    // El servidor aceptó: recién aquí el texto puede abandonar la ventana.
    Vault.sent();
    state.sending = false;
    state.files = []; renderAtts();
    addShell("user").innerHTML = md(snapshot);
    state.runId = data.run_id;
    listen(data.run_id, mdBox, holder, pendingThink, pendingTools);
  }catch(err){
    Vault.freeze(false);
    state.sending = false;
    holder.remove();
    bubble.parentElement.remove();
    finish();
    // El borrador y los adjuntos permanecen intactos para reintentar.
    toast("✖ " + err.message + " — la petición sigue protegida en la bóveda.");
  }
}

function listen(runId, mdBox, holder, pendingThink, pendingTools){
  if(state.es) state.es.close();
  const es = new EventSource("/api/chat/stream/"+runId);
  state.es = es;

  es.onmessage = (ev) => {
    let e; try{ e = JSON.parse(ev.data); }catch{ return; }
    if(e.kind === "text"){
      state.streamBuf += e.text;
      mdBox.innerHTML = md(state.streamBuf);
      scrollBottom();
    } else if(e.kind === "thinking"){
      if(!pendingThink.el){
        const d = document.createElement("details");
        d.className = "thinking"; d.open = false;
        d.innerHTML = `<summary>🧠 RAZONAMIENTO · en curso</summary><div class="body"></div>`;
        holder.insertBefore(d, mdBox);
        pendingThink.el = d.querySelector(".body");
      }
      pendingThink.el.textContent += (pendingThink.el.textContent ? "\n\n" : "") + e.text;
    } else if(e.kind === "tool"){
      const card = toolCard(e);
      holder.insertBefore(card, mdBox);
      scrollBottom();
    } else if(e.kind === "step_finish"){
      $("tokenPill").textContent = "↑"+(e.tokens_in||0)+" ↓"+(e.tokens_out||0);
    } else if(e.kind === "error"){
      setStatus("err", "ANOMALÍA");
      const box = document.createElement("div");
      box.className = "tool";
      box.style.borderColor = "rgba(255,85,85,.5)";
      box.innerHTML = `<summary style="color:#ff5555">⚠ ERROR DEL NÚCLEO</summary>
        <div class="body"><pre style="color:#ffb3b3">${esc(e.message || "desconocido")}
${e.retry_after_ms ? "\nReintenta en ~"+Math.round(e.retry_after_ms/60000)+" min o cambia de modelo." : ""}</pre></div>`;
      holder.insertBefore(box, mdBox);
      toast("✖ " + (e.message || "Error del núcleo"));
    } else if(e.kind === "done"){
      state.streamBuf = e.answer || state.streamBuf;
      mdBox.classList.remove("caret");
      mdBox.innerHTML = md(state.streamBuf);
      if(e.cancelled) addShell("system").innerHTML = "Turno cancelado.";
      finish();
      refreshSessions();
    } else if(e.kind === "eof"){
      es.close();
      if(state.busy) finish();
    }
  };
  es.onerror = () => {
    // El servidor cierra el stream al terminar; reconectar sólo si seguimos ocupados.
    if(!state.busy){ es.close(); }
  };
}

function finish(){
  state.busy = false;
  $("sendBtn").disabled = false;
  $("cancelBtn").style.display = "none";
  $("wave").classList.remove("on");
  setStatus("", "EN LÍNEA");
  const boxes = $("messages").querySelectorAll(".bubble .caret");
  boxes.forEach(b => b.classList.remove("caret"));
  if(state.es){ state.es.close(); state.es = null; }
  scrollBottom();
}

async function refreshSessions(){
  const r = await fetch("/api/chat/sessions");
  const data = await r.json();
  state.sessions = data.sessions || [];
  renderSessions();
  if(state.session){
    const r2 = await fetch("/api/chat/sessions/"+state.session.id);
    if(r2.ok){
      const d = await r2.json();
      state.session = d.session;
      $("topTitle").textContent = state.session.title || "Nueva conversación";
      $("sessionHint").textContent = "sesión " + state.session.id + (state.session.opencode_session_id ? " · opencode " + state.session.opencode_session_id : " · opencode pendiente");
      const stats = state.session.stats || {};
      $("tokenPill").textContent = "↑"+(stats.tokens_in||0)+" ↓"+(stats.tokens_out||0);
    }
  }
}

async function cancel(){
  if(!state.runId) return;
  await fetch("/api/chat/cancel/"+state.runId, {method:"POST"});
  toast("Cancelación solicitada.", true);
}

/* ---------------- adjuntos ---------------- */
function renderAtts(){
  const box = $("atts");
  box.innerHTML = state.files.map((f,i) => `<span class="att">📎 ${esc(f.split("/").pop())}<button data-i="${i}">✕</button></span>`).join("");
  box.querySelectorAll("button").forEach(b => b.addEventListener("click", ()=>{
    state.files.splice(+b.dataset.i, 1); renderAtts();
  }));
}

async function handleFiles(fileList){
  for(const file of fileList){
    if(file.size > 25*1024*1024){ toast("✖ " + file.name + " supera 25 MB"); continue; }
    const b64 = await new Promise((res, rej) => {
      const fr = new FileReader();
      fr.onload = () => res(fr.result);
      fr.onerror = rej;
      fr.readAsDataURL(file);
    });
    const r = await fetch("/api/chat/upload", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({name: file.name, data: b64})});
    if(r.ok){ const d = await r.json(); state.files.push(d.path); renderAtts(); }
    else toast("✖ No se pudo adjuntar " + file.name);
  }
}

/* ---------------- eventos UI ---------------- */
function autoGrow(){
  const t = $("input");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 190) + "px";
}

$("sendBtn").addEventListener("click", send);
$("cancelBtn").addEventListener("click", cancel);
$("newChat").addEventListener("click", newSession);
$("menuBtn").addEventListener("click", () => $("sidebar").classList.toggle("open"));
$("attachBtn").addEventListener("click", () => $("filePicker").click());
$("filePicker").addEventListener("change", (e) => { handleFiles(e.target.files); e.target.value = ""; });
$("exportBtn").addEventListener("click", () => {
  if(!state.session) return;
  window.open("/api/chat/export/"+state.session.id+"?fmt=md", "_blank");
});

/* ---------- bóveda ---------- */
$("vaultBtn").addEventListener("click", () => Vault.active ? Vault.mount() : Vault.open({}));
$("vaultClose").addEventListener("click", () => Vault.close(true));
$("vaultBackdrop").addEventListener("click", () => { /* no cerrar: la bóveda exige acción explícita */ });

/* ---------- historial ---------- */
$("historyBtn").addEventListener("click", openHistory);
$("historyScrim").addEventListener("click", closeHistory);
$("historyRefresh").addEventListener("click", historyLoad);
$("historyExport").addEventListener("click", () => {
  window.open("/api/chat/history/export?fmt=md&source="+encodeURIComponent(Hist.source)+
    "&q="+encodeURIComponent(Hist.query), "_blank");
});
$("historySearch").addEventListener("input", (e) => {
  Hist.query = e.target.value;
  clearTimeout(Hist.timer);
  Hist.timer = setTimeout(historyLoad, 320);
});
document.querySelectorAll(".hfilt").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".hfilt").forEach(b => b.classList.remove("on"));
    btn.classList.add("on");
    Hist.source = btn.dataset.src || "all";
    historyLoad();
  });
});

/* ---------- borrador recuperado ---------- */
$("recoverLoad").addEventListener("click", async () => {
  const text = Guard.nativeGet();
  $("recoverBanner").classList.remove("on");
  await Vault.open({text});
});
$("recoverDismiss").addEventListener("click", () => {
  $("recoverBanner").classList.remove("on");
  state.recovered = null;
  Guard.write("");
  saveDraft("");
  autoGrow();
});

/* ---------- entrada soberana ---------- */
$("input").addEventListener("input", () => {
  autoGrow();
  const value = Guard.nativeGet();
  saveDraft(value);
  if(!Vault.active && !Vault.opening && !state.busy && value.trim()){
    Vault.open({silent:true, text:value});
  }
});
$("input").addEventListener("compositionstart", () => { state.composing = true; });
$("input").addEventListener("compositionend", () => {
  state.composing = false;
  autoGrow();
  saveDraft(Guard.nativeGet());
});
$("input").addEventListener("keydown", (e) => {
  // Nunca enviar mientras se compone texto (acentos, chino, japonés, emoji…).
  if(e.isComposing || state.composing || e.keyCode === 229) return;
  if(e.key === "Enter" && !e.shiftKey && (Vault.active || !e.altKey && !e.ctrlKey && !e.metaKey)){
    e.preventDefault();
    send();
  }
  if(e.key === "Escape" && Vault.active){
    e.preventDefault();
    Vault.close(true);
  }
});
document.addEventListener("keydown", (e) => {
  if((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "k"){
    e.preventDefault();
    if(Vault.active){ $("input").focus(); }
    else Vault.open({});
  }
  if((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "h"){
    e.preventDefault();
    Hist.open ? closeHistory() : openHistory();
  }
  if((e.ctrlKey || e.metaKey) && e.shiftKey && e.code === "Space"){
    e.preventDefault();
    Vault.active ? Vault.mount() : Vault.open({});
  }
  if(e.key === "Escape" && Hist.open){ closeHistory(); }
});

/* Defensa de navegación: una actualización externa no debe descartar la petición. */
window.addEventListener("beforeunload", (e) => {
  if(Vault.active && Guard.nativeGet().trim()){
    e.preventDefault();
    e.returnValue = "Hay una petición blindada sin enviar. El borrador está a salvo, pero saldrás de la bóveda.";
    return e.returnValue;
  }
});
document.addEventListener("visibilitychange", () => {
  if(document.visibilityState === "hidden" && Vault.active) Vault.persist(true);
});

$("tgThink").addEventListener("click", async () => {
  $("tgThink").classList.toggle("on");
  if(state.session) await fetch("/api/chat/sessions/"+state.session.id, {method:"PATCH",
    headers:{"Content-Type":"application/json"}, body: JSON.stringify({thinking: $("tgThink").classList.contains("on")})});
});
$("tgAuto").addEventListener("click", async () => {
  $("tgAuto").classList.toggle("on");
  if(state.session) await fetch("/api/chat/sessions/"+state.session.id, {method:"PATCH",
    headers:{"Content-Type":"application/json"}, body: JSON.stringify({auto: $("tgAuto").classList.contains("on")})});
});
$("modelSel").addEventListener("change", async () => {
  if(state.session) await fetch("/api/chat/sessions/"+state.session.id, {method:"PATCH",
    headers:{"Content-Type":"application/json"}, body: JSON.stringify({model: $("modelSel").value})});
});
$("agentInput").addEventListener("change", async () => {
  if(state.session) await fetch("/api/chat/sessions/"+state.session.id, {method:"PATCH",
    headers:{"Content-Type":"application/json"}, body: JSON.stringify({agent: $("agentInput").value.trim()})});
});

// Reanudar la última sesión al volver al portal.
boot().catch(err => toast("✖ No se pudo iniciar: " + err.message));
</script>
</body>
</html>
"""
