"""Pruebas del modo prioritario de llamada de Telegram (TARDIS)."""

from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace

import pytest

import core.os_optimizer as _osopt_mod
import core.telegram_call_priority as tcp

_ORIG_OSOPT_PRIORITIZE = _osopt_mod.OSOptimizer.prioritize_for_telegram_call
_ORIG_OSOPT_RESTORE = _osopt_mod.OSOptimizer.restore_normal_priority
from core.telegram_call_priority import (
    TelegramCallPriorityManager,
    activate_call_priority,
    boost_process_for_call,
    get_call_priority_status,
    is_call_priority_active,
    release_call_priority,
    touch_call_priority,
)


class _FakePsutilProcess:
    _instances: dict[int, "_FakePsutilProcess"] = {}

    def __init__(self, pid: int | None = None):
        self.pid = pid if pid is not None else os.getpid()
        self._nice = 0
        self.ionice_calls: list[tuple] = []
        self._instances[self.pid] = self

    def nice(self, value: int | None = None) -> int:
        if value is not None:
            self._nice = value
        return self._nice

    def ionice(self, kind, value=0):
        self.ionice_calls.append((kind, value))


@pytest.fixture(autouse=True)
def _isolated_manager(monkeypatch, tmp_path):
    """Aísla el singleton, el archivo de estado y los efectos de SO en cada prueba."""
    monkeypatch.setattr(tcp, "STATE_FILE", tmp_path / "telegram_call_priority.json")
    monkeypatch.setattr(os, "getpriority", lambda *args: 0)
    monkeypatch.setattr(os, "setpriority", lambda *args: None)

    import psutil

    monkeypatch.setattr(psutil, "Process", lambda pid=None: _FakePsutilProcess(pid))

    import core.os_optimizer as osopt

    monkeypatch.setattr(osopt.OSOptimizer, "apply_runtime_optimizations", lambda self: {}, raising=False)
    monkeypatch.setattr(osopt.OSOptimizer, "prioritize_for_telegram_call", lambda self: {}, raising=False)
    monkeypatch.setattr(osopt.OSOptimizer, "restore_normal_priority", lambda self: {}, raising=False)

    import core.idle_evolution_daemon as idle

    monkeypatch.setattr(idle.IdleEvolutionDaemon, "suspend_for_call", lambda self: True, raising=False)
    monkeypatch.setattr(idle.IdleEvolutionDaemon, "resume_after_call", lambda self: True, raising=False)

    # Aislar el refuerzo trans-proceso y el gobernador CPU (evita efectos reales en pruebas).
    monkeypatch.setattr(tcp, "iter_system_processes", lambda: [])
    monkeypatch.setattr(tcp, "_set_cpu_governor", lambda value: "powersave")

    manager = TelegramCallPriorityManager()
    monkeypatch.setattr(TelegramCallPriorityManager, "_instance", manager)
    manager.clear()
    yield manager
    manager.clear()


def test_activate_escribe_estado_y_activa_modo(monkeypatch):
    monkeypatch.setattr(os, "getpriority", lambda *args: 0)
    calls: list[tuple] = []
    monkeypatch.setattr(os, "setpriority", lambda *a: calls.append(a))

    state = activate_call_priority("test:call-1", chat_id=REDACTED_PHONE)

    assert state["active"] is True
    assert state["priority_mode"] == "telegram_call"
    assert state["holder_count"] == 1
    assert state["holders"][0]["chat_id"] == "REDACTED_PHONE"
    assert is_call_priority_active() is True
    assert any(c[2] == tcp.DEFAULT_NICE for c in calls)
    assert tcp.STATE_FILE.exists()
    persisted = json.loads(tcp.STATE_FILE.read_text(encoding="utf-8"))
    assert persisted["active"] is True


def test_release_restaura_cuando_no_quedan_referencias():
    activate_call_priority("test:a", chat_id=1)
    activate_call_priority("test:b", chat_id=2)

    state = release_call_priority("test:a")
    assert state["active"] is True
    assert state["holder_count"] == 1

    state = release_call_priority("test:b")
    assert state["active"] is False
    assert state["priority_mode"] == "normal"
    assert state["holder_count"] == 0
    assert is_call_priority_active() is False


def test_touch_renueva_ttl_y_no_duplica_referencias():
    activate_call_priority("test:call", chat_id=1, ttl_sec=2)
    first = get_call_priority_status()["holders"][0]["expires_at"]
    time.sleep(0.02)
    state = touch_call_priority("test:call", chat_id=1, ttl_sec=60)
    assert state["holder_count"] == 1
    assert state["holders"][0]["expires_at"] > first


def test_ttl_expirado_libera_prioridad_automaticamente():
    activate_call_priority("test:stale", chat_id=1, ttl_sec=0.01)
    time.sleep(0.03)
    assert is_call_priority_active() is False
    assert get_call_priority_status()["holder_count"] == 0


def test_boost_process_for_call_refuerza_hijo_e_es_idempotente():
    activate_call_priority("test:call")
    proc = SimpleNamespace(pid=424242)

    first = boost_process_for_call(proc)
    second = boost_process_for_call(proc)

    assert first["ok"] is True
    assert second.get("already_boosted") is True
    fake = _FakePsutilProcess._instances[424242]
    assert fake.nice() == tcp.DEFAULT_NICE
    assert fake.ionice_calls


def test_idle_daemon_se_suspende_durante_llamada(monkeypatch):
    import core.idle_evolution_daemon as idle

    events: list[str] = []
    monkeypatch.setattr(
        idle.IdleEvolutionDaemon,
        "suspend_for_call",
        lambda self: events.append("suspend") or True,
        raising=False,
    )
    monkeypatch.setattr(
        idle.IdleEvolutionDaemon,
        "resume_after_call",
        lambda self: events.append("resume") or True,
        raising=False,
    )

    activate_call_priority("test:call")
    release_call_priority("test:call")
    assert events == ["suspend", "resume"]


def test_health_del_servidor_expone_prioridad():
    import asyncio

    from aiohttp.test_utils import TestClient, TestServer

    from core.telegram_live_call_server import create_app

    async def _check():
        async with TestClient(TestServer(create_app())) as client:
            resp = await client.get("/tg-call/health")
            assert resp.status == 200
            data = await resp.json()
            assert "system_priority_active" in data
            assert "priority_mode" in data

            resp = await client.get("/tg-call/priority")
            assert resp.status == 200
            assert (await resp.json())["active"] is False

    asyncio.run(_check())


class _FakeProcInfo:
    """Proceso ficticio con `.info` como devuelve psutil.process_iter."""

    def __init__(self, pid: int, name: str, cmdline: list[str]):
        self.info = {"pid": pid, "name": name, "cmdline": cmdline, "nice": 0}


def _patch_process_nice(monkeypatch, pid: int, nice: int) -> _FakePsutilProcess:
    """Hace que psutil.Process(pid) devuelva siempre el mismo fake con nice sembrado."""
    import psutil

    fake = _FakePsutilProcess(pid)
    fake._nice = nice
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda p=None: fake if p == pid else _FakePsutilProcess(p),
    )
    return fake


def test_boost_transproceso_refuerza_inferencia_y_restaura(monkeypatch):
    fake = _patch_process_nice(monkeypatch, 878736, 10)
    procs = [
        _FakeProcInfo(
            878736,
            "llama-server",
            ["/home/m11/.local/lib/ollama/llama-server", "--model", "TARDIS-NEURAL-SPACE-KAIJU"],
        )
    ]
    monkeypatch.setattr(tcp, "iter_system_processes", lambda: procs)
    monkeypatch.setattr(tcp, "_set_cpu_governor", lambda value: "powersave")

    activate_call_priority("test:call", chat_id=1)

    assert fake.nice() == tcp.DEFAULT_NICE
    state = get_call_priority_status()
    assert state["boosted_processes"] == 1
    assert 878736 in state["boosted_system_pids"]

    release_call_priority("test:call")
    assert fake.nice() == 10
    assert get_call_priority_status()["boosted_processes"] == 0


def test_deprioriza_demonios_de_fondo_y_restaura(monkeypatch):
    fake = _patch_process_nice(monkeypatch, 4242, 0)
    procs = [
        _FakeProcInfo(
            4242,
            "python3",
            ["python3", "/home/m11/.local/bin/tardis-music-maestro"],
        )
    ]
    monkeypatch.setattr(tcp, "iter_system_processes", lambda: procs)
    monkeypatch.setattr(tcp, "_set_cpu_governor", lambda value: "powersave")

    activate_call_priority("test:call")

    assert fake.nice() == tcp.DEFAULT_DEPRIORITIZE_NICE
    assert get_call_priority_status()["deprioritized_processes"] == 1

    release_call_priority("test:call")
    assert fake.nice() == 0
    assert get_call_priority_status()["deprioritized_processes"] == 0


def test_gobernador_performance_se_restaura_al_colgar(monkeypatch):
    writes: list[str] = []
    monkeypatch.setattr(tcp, "iter_system_processes", lambda: [])
    monkeypatch.setattr(tcp, "_set_cpu_governor", lambda value: writes.append(value) or "powersave")

    activate_call_priority("test:call")
    assert "performance" in writes

    release_call_priority("test:call")
    assert "powersave" in writes


def test_boost_process_for_call_restaura_nice_al_colgar(monkeypatch):
    fake = _patch_process_nice(monkeypatch, 515151, 0)
    activate_call_priority("test:call")
    proc = SimpleNamespace(pid=515151)

    boost_process_for_call(proc)
    assert fake.nice() == tcp.DEFAULT_NICE

    release_call_priority("test:call")
    assert fake.nice() == 0


def test_boost_process_for_call_degrada_ionice_rt_a_be0(monkeypatch):
    import psutil

    class _NoRtProc(_FakePsutilProcess):
        def ionice(self, kind=None, value=0):
            if kind == getattr(psutil, "IOPRIO_CLASS_RT", -1):
                raise PermissionError("CAP_SYS_ADMIN required")
            super().ionice(kind, value)

    fake = _NoRtProc(616161)
    monkeypatch.setattr(psutil, "Process", lambda p=None: fake if p == 616161 else _FakePsutilProcess(p))
    activate_call_priority("test:call")
    res = boost_process_for_call(SimpleNamespace(pid=616161))
    assert res["ok"] is True
    assert fake.ionice_calls == [(psutil.IOPRIO_CLASS_BE, 0)]


def test_cross_process_state_file_respeta_ttl_largo_y_pid_vivo(monkeypatch):
    """Un proceso distinto (ej. tardis.service) debe ver llamadas activas escritas por tardis-telegram-call."""
    now = time.time()
    remote_pid = os.getpid() + 999999
    monkeypatch.setattr(tcp, "_pid_is_alive", lambda pid: pid == remote_pid)
    # Simula un estado escrito hace 300s (>120s) pero con TTL todavía vigente (+1500s).
    tcp.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tcp.STATE_FILE.write_text(
        json.dumps(
            {
                "ok": True,
                "active": True,
                "priority_mode": "telegram_call",
                "owner_pid": remote_pid,
                "timestamp": now - 300.0,
                "holders": [{"source": "live_call:call_1", "chat_id": "REDACTED_PHONE", "expires_at": now + 1500.0}],
                "holder_count": 1,
            }
        ),
        encoding="utf-8",
    )

    assert is_call_priority_active() is True
    st = get_call_priority_status()
    assert st["active"] is True
    assert st.get("cross_process_active") is True

    # Si el proceso remoto murió, ya no debe reportarse activo.
    monkeypatch.setattr(tcp, "_pid_is_alive", lambda pid: False)
    assert is_call_priority_active() is False


def test_ftl_public_gateway_se_refuerza_y_no_se_deprioriza(monkeypatch):
    import psutil

    gw = _FakePsutilProcess(7001)
    gw._nice = 5
    omni_bg = _FakePsutilProcess(7002)
    omni_bg._nice = 0
    desk = _FakePsutilProcess(7003)
    desk._nice = -8
    by_pid = {7001: gw, 7002: omni_bg, 7003: desk}
    monkeypatch.setattr(psutil, "Process", lambda p=None: by_pid.get(p, _FakePsutilProcess(p)))

    procs = [
        _FakeProcInfo(7001, "python3", ["python3", "ftl_public_gateway.py"]),
        _FakeProcInfo(7002, "python3", ["python3", "tardis-omniscient-autonomy"]),
        _FakeProcInfo(7003, "tardis-desktop", ["/usr/bin/tardis-desktop"]),
    ]
    monkeypatch.setattr(tcp, "iter_system_processes", lambda: procs)

    activate_call_priority("test:call")

    assert gw.nice() == tcp.DEFAULT_NICE
    assert omni_bg.nice() == tcp.DEFAULT_DEPRIORITIZE_NICE
    assert desk.nice() == -8

    release_call_priority("test:call")
    assert gw.nice() == 5
    assert omni_bg.nice() == 0
    assert desk.nice() == -8


def test_os_optimizer_prioritize_y_restore_son_idempotentes_y_degradan_ionice(monkeypatch):
    import psutil
    from core.os_optimizer import OSOptimizer

    class _NoRtSelf(_FakePsutilProcess):
        def ionice(self, kind=None, value=0):
            if kind == getattr(psutil, "IOPRIO_CLASS_RT", -1):
                raise PermissionError("CAP_SYS_ADMIN required")
            super().ionice(kind, value)

    fake = _NoRtSelf(os.getpid())
    state_nice = {"v": 0}
    monkeypatch.setattr(os, "getpriority", lambda *a: state_nice["v"])
    monkeypatch.setattr(os, "setpriority", lambda which, who, val: state_nice.__setitem__("v", val))
    monkeypatch.setattr(psutil, "Process", lambda p=None: fake)

    monkeypatch.setattr(_osopt_mod.OSOptimizer, "prioritize_for_telegram_call", _ORIG_OSOPT_PRIORITIZE)
    monkeypatch.setattr(_osopt_mod.OSOptimizer, "restore_normal_priority", _ORIG_OSOPT_RESTORE)
    opt = OSOptimizer()
    r1 = opt.prioritize_for_telegram_call()
    r2 = opt.prioritize_for_telegram_call()
    assert r1["ok"] is True
    assert r2["ok"] is True
    assert state_nice["v"] == -10
    assert fake.nice() == -10
    assert r1["ionice"] == "best-effort (priority 0)"

    rr = opt.restore_normal_priority()
    assert rr["ok"] is True
    assert state_nice["v"] == 0
    assert fake.nice() == 0


def test_idle_daemon_detecta_prioridad_cross_process(monkeypatch):
    from core.idle_evolution_daemon import IdleEvolutionDaemon

    daemon = IdleEvolutionDaemon()
    assert daemon.is_suspended_for_call() is False

    now = time.time()
    remote_pid = os.getpid() + 888888
    monkeypatch.setattr(tcp, "_pid_is_alive", lambda pid: pid == remote_pid)
    tcp.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tcp.STATE_FILE.write_text(
        json.dumps(
            {
                "ok": True,
                "active": True,
                "owner_pid": remote_pid,
                "timestamp": now,
                "holders": [{"source": "live_call:ws_9", "chat_id": "REDACTED_PHONE", "expires_at": now + 600}],
                "holder_count": 1,
            }
        ),
        encoding="utf-8",
    )

    assert daemon.is_suspended_for_call() is True
    assert daemon.execute_evolution_cycle(force=False) is None


def test_live_call_ws_activa_y_libera_prioridad_en_hello_y_hangup(monkeypatch):
    import asyncio
    from aiohttp.test_utils import TestClient, TestServer
    import core.telegram_live_call_server as lcs

    async def _noop_synth(self, text, voice=lcs.DEFAULT_VOICE):
        return b""

    monkeypatch.setattr(lcs.RealtimeVoiceEngine, "synthesize_mp3", _noop_synth)
    monkeypatch.setattr(lcs, "load_recent_call_history", lambda *a, **k: [])
    monkeypatch.setattr(lcs, "append_call_history_log", lambda *a, **k: None)

    async def _notify_noop(*a, **k):
        return None

    monkeypatch.setattr(lcs, "notify_telegram_call_ended", _notify_noop)
    token = lcs.sign_call_token(chat_id=lcs.ARCHITECT_TELEGRAM_ID, user_name="Arquitecto")

    async def _run():
        async with TestClient(TestServer(lcs.create_app())) as client:
            assert is_call_priority_active() is False
            async with client.ws_connect(f"/tg-call/ws?ct={token}") as ws:
                await ws.send_json({"type": "hello", "ct": token, "reconnect": True})
                msg = await ws.receive_json(timeout=5)
                assert msg["type"] == "call_ready"
                assert msg["priority_active"] is True
                assert is_call_priority_active() is True

                await ws.send_json({"type": "hangup", "duration_sec": 3.5})
            # Al cerrar el WS la prioridad debe quedar liberada
            assert is_call_priority_active() is False

    asyncio.run(_run())
