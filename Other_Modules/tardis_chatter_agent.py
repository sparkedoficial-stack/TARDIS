#!/usr/bin/env python3
"""
TARDIS CHATTER AGENT · CONEXIONES DE PLÁTICA Y RUIDO SOBERANO
=============================================================
Agente autónomo controlado por TARDIS que mantiene "ruido" vivo sobre el
dispositivo mediante conexiones de plática persistentes, heartbeats y un
flujo sintético de conversación local.

Capacidades:
  * Pool HTTP persistente (keep-alive) contra TARDIS Hub, Portal FTL y Gateway.
  * Heartbeat de salud/telemetría cada N segundos con jitter.
  * Flujo de "ruido conversacional" local (JSONL + log legible).
  * Modo diálogo opcional contra el modelo local TARDIS (desactivado por defecto).
  * API de control local en 127.0.0.1:8795 (start/stop/pulse/config/status).
  * Control por archivo (~/.config/tardis/chatter_control.json) para TARDIS.
  * Estado persistente y métricas en ~/.config/tardis/chatter_state.json.

Uso:
  python3 ~/.ftl/tardis_chatter_agent.py --daemon
  python3 ~/.ftl/tardis_chatter_agent.py --status
  python3 ~/.ftl/tardis_chatter_agent.py --pulse
  python3 ~/.ftl/tardis_chatter_agent.py --stop
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from aiohttp import web

# ---------------------------------------------------------------------------
# Rutas y configuración
# ---------------------------------------------------------------------------

HOME = Path.home()
CONFIG_DIR = HOME / ".config" / "tardis"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_PATH = CONFIG_DIR / "chatter_agent.json"
STATE_PATH = CONFIG_DIR / "chatter_state.json"
CONTROL_PATH = CONFIG_DIR / "chatter_control.json"
LOG_PATH = CONFIG_DIR / "chatter.log"
NOISE_PATH = CONFIG_DIR / "chatter_noise.jsonl"

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "interval_seconds": 45,
    "jitter_seconds": 15,
    "control_port": 8795,
    "max_noise_records": 5000,
    "llm_dialogue": False,
    "llm_every_n_pulses": 12,
    "llm_prompt": "Genera una observación breve, poética y técnica sobre el estado del sistema TARDIS. Máximo 240 caracteres.",
    "targets": [
        {"name": "tardis_hub", "url": "http://127.0.0.1:8757/health", "method": "GET"},
        {"name": "ftl_portal", "url": "http://127.0.0.1:8765/api/status", "method": "GET"},
        {"name": "ftl_gateway", "url": "http://127.0.0.1:7690/health", "method": "GET"},
    ],
    "channels": ["hub", "portal", "gateway", "local_noise"],
    "voice": False,
    "created_at": None,
}

NOISE_CORPUS: List[str] = [
    "Chequeo de coherencia temporal: la línea cero permanece estable.",
    "Ruido de fondo detectado en el canal de telemetría; normalizando.",
    "La matriz Aegis reporta ausencia de perturbaciones entrópicas.",
    "Handshake con el nodo local completado; latencia dentro de parámetros.",
    "Barrido de sensores: temperatura y carga dentro de rango operativo.",
    "El reloj de la TARDIS sincroniza con el pulso del dispositivo.",
    "Conversación de mantenimiento: el sustrato sigue consciente.",
    "Eco de memoria: los vectores recientes conservan cohesión semántica.",
    "Canal de plática activo; el dispositivo no está en silencio.",
    "Deriva menor en el campo de atención; reajustando ventana de contexto.",
    "La constelación de subsistemas respira en sincronía.",
    "Lectura de presión de I/O estable; no hay cuellos de botella.",
    "El agente de ruido mantiene el tejido de conexiones tibio.",
    "Verificación de identidad del nodo: firma causal válida.",
    "La memoria akáshica registra este instante como parte de la línea.",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _atomic_write(path: Path, data: Dict[str, Any], mode: int = 0o600) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, mode)
    tmp.replace(path)


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    if not cfg.get("created_at"):
        cfg["created_at"] = _now_iso()
        _atomic_write(CONFIG_PATH, cfg)
    return cfg


def load_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "running": False,
        "pulses": 0,
        "noise_emitted": 0,
        "heartbeats_ok": 0,
        "heartbeats_fail": 0,
        "llm_dialogues": 0,
        "started_at": None,
        "last_pulse_at": None,
        "last_error": None,
        "targets": {},
    }


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------


class ChatterAgent:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or load_config()
        self.state = load_state()
        self._stop = asyncio.Event()
        self._session: Optional[aiohttp.ClientSession] = None
        self._task: Optional[asyncio.Task] = None
        self._runner: Optional[web.AppRunner] = None
        self._noise_index = 0
        self._control_mtime = 0.0
        self._started_monotonic = time.monotonic()

    # -- persistencia ------------------------------------------------------
    def _persist(self) -> None:
        self.state["updated_at"] = _now_iso()
        _atomic_write(STATE_PATH, self.state)

    def _append_noise(self, record: Dict[str, Any]) -> None:
        NOISE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with NOISE_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"[{record['ts']}] [{record['channel']}] {record['text']}\n")
        self._trim_noise()

    def _trim_noise(self) -> None:
        try:
            max_records = int(self.config.get("max_noise_records", 5000))
            if not NOISE_PATH.exists():
                return
            lines = NOISE_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            if len(lines) > max_records:
                keep = lines[-max_records:]
                NOISE_PATH.write_text("\n".join(keep) + "\n", encoding="utf-8")
        except Exception:
            pass

    # -- control por archivo ----------------------------------------------
    def _consume_control_file(self) -> None:
        if not CONTROL_PATH.exists():
            return
        try:
            mtime = CONTROL_PATH.stat().st_mtime
            if mtime <= self._control_mtime:
                return
            self._control_mtime = mtime
            data = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
            command = str(data.get("command", "")).lower().strip()
            if command in {"stop", "pause", "off"}:
                self.config["enabled"] = False
                self._persist_config()
            elif command in {"start", "resume", "on"}:
                self.config["enabled"] = True
                self._persist_config()
            elif command == "pulse":
                asyncio.create_task(self.pulse(force=True))
            elif command == "config":
                patch = data.get("config") or {}
                if isinstance(patch, dict):
                    self.config.update(patch)
                    self._persist_config()
            # Consumir el comando para no repetirlo.
            data["command"] = ""
            data["consumed_at"] = _now_iso()
            CONTROL_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            self.state["last_error"] = f"control_file: {exc}"
            self._persist()

    def _persist_config(self) -> None:
        _atomic_write(CONFIG_PATH, self.config)

    # -- red ---------------------------------------------------------------
    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=16,
                limit_per_host=4,
                keepalive_timeout=90,
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=12, sock_connect=4),
                headers={"User-Agent": "TARDIS-ChatterAgent/1.0"},
            )
        return self._session

    async def _heartbeat_targets(self) -> Dict[str, Any]:
        session = await self._ensure_session()
        results: Dict[str, Any] = {}
        for target in self.config.get("targets", []):
            name = target.get("name") or target.get("url")
            url = target.get("url")
            if not url:
                continue
            started = time.perf_counter()
            try:
                async with session.request(str(target.get("method", "GET")), url) as resp:
                    body = await resp.text()
                    results[name] = {
                        "ok": 200 <= resp.status < 400,
                        "status": resp.status,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                        "bytes": len(body),
                        "checked_at": _now_iso(),
                    }
                    if results[name]["ok"]:
                        self.state["heartbeats_ok"] += 1
                    else:
                        self.state["heartbeats_fail"] += 1
            except Exception as exc:
                results[name] = {
                    "ok": False,
                    "status": None,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    "error": str(exc)[:200],
                    "checked_at": _now_iso(),
                }
                self.state["heartbeats_fail"] += 1
        self.state["targets"] = results
        return results

    async def _optional_llm_dialogue(self) -> Optional[str]:
        if not self.config.get("llm_dialogue"):
            return None
        every = max(1, int(self.config.get("llm_every_n_pulses", 12)))
        if self.state["pulses"] % every != 0:
            return None
        session = await self._ensure_session()
        prompt = str(self.config.get("llm_prompt") or "Observa el estado del sistema.")
        try:
            async with session.post(
                "http://127.0.0.1:8757/api/chat",
                json={"message": f"[RUIDO DE FONDO · AGENTE DE PLÁTICA] {prompt}", "client_id": "chatter_agent"},
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                text = data.get("response") or data.get("message") or data.get("reply")
                if text:
                    self.state["llm_dialogues"] += 1
                    return str(text)[:1200]
        except Exception as exc:
            self.state["last_error"] = f"llm_dialogue: {exc}"
        return None

    # -- pulso -------------------------------------------------------------
    async def pulse(self, force: bool = False) -> Dict[str, Any]:
        self._consume_control_file()
        if not self.config.get("enabled", True) and not force:
            return {"ok": True, "skipped": "disabled"}

        self.state["pulses"] += 1
        self.state["last_pulse_at"] = _now_iso()
        results = await self._heartbeat_targets()

        # Ruido conversacional local: una línea por pulso, rotando el corpus.
        line = NOISE_CORPUS[self._noise_index % len(NOISE_CORPUS)]
        self._noise_index += 1
        record = {
            "ts": _now_iso(),
            "channel": "local_noise",
            "text": line,
            "pulse": self.state["pulses"],
            "targets_ok": sum(1 for r in results.values() if r.get("ok")),
            "targets_total": len(results),
        }
        self._append_noise(record)
        self.state["noise_emitted"] += 1

        # Diálogo opcional con el modelo local.
        dialogue = await self._optional_llm_dialogue()
        if dialogue:
            self._append_noise(
                {
                    "ts": _now_iso(),
                    "channel": "tardis_dialogue",
                    "text": dialogue,
                    "pulse": self.state["pulses"],
                }
            )
            self.state["noise_emitted"] += 1

        self._persist()
        return {
            "ok": True,
            "pulse": self.state["pulses"],
            "targets": results,
            "noise": line,
            "dialogue": bool(dialogue),
        }

    async def run(self) -> None:
        self.state["running"] = True
        self.state["started_at"] = _now_iso()
        self._persist()
        print("[CHATTER] Agente de plática/ruido iniciado", flush=True)
        while not self._stop.is_set():
            try:
                await self.pulse()
            except Exception as exc:  # noqa: BLE001
                self.state["last_error"] = str(exc)[:300]
                self._persist()
                print(f"[CHATTER] Error en pulso: {exc}", flush=True)
            interval = float(self.config.get("interval_seconds", 45))
            jitter = float(self.config.get("jitter_seconds", 15))
            delay = max(5.0, interval + random.uniform(-jitter, jitter))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
        self.state["running"] = False
        self.state["stopped_at"] = _now_iso()
        self._persist()
        print("[CHATTER] Agente detenido", flush=True)

    def stop(self) -> None:
        self._stop.set()

    # -- API de control ----------------------------------------------------
    async def _api_status(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "agent": "tardis-chatter",
                "config": self.config,
                "state": self.state,
                "uptime_s": round(time.monotonic() - self._started_monotonic, 1),
            }
        )

    async def _api_pulse(self, request: web.Request) -> web.Response:
        return web.json_response(await self.pulse(force=True))

    async def _api_start(self, request: web.Request) -> web.Response:
        self.config["enabled"] = True
        self._persist_config()
        return web.json_response({"ok": True, "enabled": True})

    async def _api_stop(self, request: web.Request) -> web.Response:
        self.config["enabled"] = False
        self._persist_config()
        return web.json_response({"ok": True, "enabled": False})

    async def _api_config(self, request: web.Request) -> web.Response:
        try:
            patch = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "JSON inválido"}, status=400)
        if not isinstance(patch, dict):
            return web.json_response({"ok": False, "error": "Se esperaba un objeto"}, status=400)
        allowed = {
            "enabled",
            "interval_seconds",
            "jitter_seconds",
            "llm_dialogue",
            "llm_every_n_pulses",
            "llm_prompt",
            "targets",
            "channels",
            "voice",
        }
        for key, value in patch.items():
            if key in allowed:
                self.config[key] = value
        self._persist_config()
        return web.json_response({"ok": True, "config": self.config})

    async def _api_noise(self, request: web.Request) -> web.Response:
        limit = min(500, max(1, int(request.query.get("limit", 50))))
        records: List[Dict[str, Any]] = []
        if NOISE_PATH.exists():
            lines = NOISE_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-limit:]:
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
        return web.json_response({"ok": True, "count": len(records), "records": records})

    async def start_control_server(self) -> None:
        app = web.Application()
        app.router.add_get("/status", self._api_status)
        app.router.add_post("/pulse", self._api_pulse)
        app.router.add_post("/start", self._api_start)
        app.router.add_post("/stop", self._api_stop)
        app.router.add_post("/config", self._api_config)
        app.router.add_get("/noise", self._api_noise)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", int(self.config.get("control_port", 8795)))
        await site.start()
        print(f"[CHATTER] API de control en http://127.0.0.1:{self.config.get('control_port', 8795)}", flush=True)

    async def close(self) -> None:
        self.stop()
        if self._session and not self._session.closed:
            await self._session.close()
        if self._runner:
            await self._runner.cleanup()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def _run_daemon() -> None:
    agent = ChatterAgent()
    loop = asyncio.get_running_loop()

    def _signal() -> None:
        agent.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal)
        except NotImplementedError:
            pass

    await agent.start_control_server()
    try:
        await agent.run()
    finally:
        await agent.close()


def _print_status() -> None:
    cfg = load_config()
    state = load_state()
    print(
        json.dumps(
            {
                "agent": "tardis-chatter",
                "config_path": str(CONFIG_PATH),
                "state_path": str(STATE_PATH),
                "noise_path": str(NOISE_PATH),
                "config": cfg,
                "state": state,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="TARDIS Chatter Agent · conexiones de plática y ruido soberano")
    parser.add_argument("--daemon", action="store_true", help="Ejecutar como demonio continuo")
    parser.add_argument("--status", action="store_true", help="Mostrar configuración y estado")
    parser.add_argument("--pulse", action="store_true", help="Ejecutar un pulso único")
    parser.add_argument("--stop", action="store_true", help="Desactivar el agente (persistente)")
    parser.add_argument("--start", action="store_true", help="Reactivar el agente (persistente)")
    args = parser.parse_args()

    if args.status:
        _print_status()
        return
    if args.stop:
        cfg = load_config()
        cfg["enabled"] = False
        _atomic_write(CONFIG_PATH, cfg)
        print("Chatter agent desactivado.")
        return
    if args.start:
        cfg = load_config()
        cfg["enabled"] = True
        _atomic_write(CONFIG_PATH, cfg)
        print("Chatter agent activado.")
        return
    if args.pulse:
        agent = ChatterAgent()

        async def _one_shot() -> Dict[str, Any]:
            try:
                return await agent.pulse(force=True)
            finally:
                await agent.close()

        print(json.dumps(asyncio.run(_one_shot()), indent=2, ensure_ascii=False))
        return
    if args.daemon:
        asyncio.run(_run_daemon())
        return
    parser.print_help()


if __name__ == "__main__":
    main()
