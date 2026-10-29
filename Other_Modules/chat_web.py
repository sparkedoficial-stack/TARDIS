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

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

import chat_store as store
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
    text = (payload.get("text") or "").strip()
    if not text:
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
    return JSONResponse({
        "run_id": run_id,
        "session_id": session["id"],
        "model": session.get("model"),
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
      <div class="pill"><span class="dot" id="statusDot"></span><span id="statusText">EN LÍNEA</span></div>
      <div class="pill" id="tokenPill">↑0 ↓0</div>
    </div>
    <div class="wave" id="wave"></div>
    <div class="messages" id="messages"></div>
    <div class="composer">
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

<script>
const $ = (id) => document.getElementById(id);
const state = { session:null, sessions:[], models:[], busy:false, es:null, runId:null, files:[], streamBuf:"", composing:false, stick:true };

/* Borrador persistente: el texto escrito nunca se pierde (recarga, fallo de red, cambio de sesión). */
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
function restoreDraft(){
  const draft = loadDraft();
  const t = $("input");
  if(draft && !t.value){ t.value = draft; autoGrow(); }
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
  restoreDraft();
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
  const r = await fetch("/api/chat/sessions", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({model: $("modelSel").value || null, agent: $("agentInput").value.trim()})});
  const data = await r.json();
  state.session = data.session;
  state.files = [];
  renderSessions(); applySession(); renderMessages();
  $("input").focus();
}

async function openSession(id){
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
      $("input").value = c.dataset.p; autoGrow(); saveDraft(c.dataset.p); $("input").focus();
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
  if(state.busy || state.composing) return;
  const input = $("input");
  const text = input.value.trim();
  if(!text) return;
  if(!state.session) await newSession();
  if(state.busy) return;

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
        text,
        files: state.files,
        model: $("modelSel").value || undefined,
        agent: $("agentInput").value.trim(),
        thinking: $("tgThink").classList.contains("on"),
        auto: $("tgAuto").classList.contains("on"),
      })});
    if(!r.ok){ throw new Error((await r.json()).detail || "Fallo al enviar"); }
    const data = await r.json();
    // Solo se limpia el campo cuando el servidor aceptó la petición.
    // Si el usuario escribió más mientras esperaba, se respeta su texto.
    if(input.value.trim() === text){ input.value = ""; saveDraft(""); autoGrow(); }
    addShell("user").innerHTML = md(text);
    state.runId = data.run_id;
    state.files = []; renderAtts();
    listen(data.run_id, mdBox, holder, pendingThink, pendingTools);
  }catch(err){
    holder.remove();
    bubble.parentElement.remove();
    finish();
    // El borrador y los adjuntos permanecen intactos para reintentar.
    toast("✖ " + err.message);
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
$("input").addEventListener("input", () => {
  autoGrow();
  saveDraft($("input").value);
});
$("input").addEventListener("compositionstart", () => { state.composing = true; });
$("input").addEventListener("compositionend", () => {
  state.composing = false;
  autoGrow();
  saveDraft($("input").value);
});
$("input").addEventListener("keydown", (e) => {
  // Nunca enviar mientras se compone texto (acentos, chino, japonés, emoji…).
  if(e.isComposing || state.composing || e.keyCode === 229) return;
  if(e.key === "Enter" && !e.shiftKey && !e.altKey && !e.ctrlKey && !e.metaKey){
    e.preventDefault();
    send();
  }
});
document.addEventListener("keydown", (e) => {
  if((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k"){ e.preventDefault(); $("input").focus(); }
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
