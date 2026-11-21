"""Pruebas del canal soberano de avances visuales de programas."""
from __future__ import annotations

import time

import pytest

from core import program_progress as pp


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x00\x03\x00\x01\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture()
def notifier(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "STATE_FILE", tmp_path / "program_progress.json")
    instance = pp.ProgramProgressNotifier()
    instance.configure(enabled=True, interval_sec=30)
    instance._state["initial_delay_sec"] = 1
    return instance


def test_start_rejects_non_architect(notifier):
    assert notifier.start_job("job-1", -100123, "programa algo") is False
    assert notifier.status()["active_count"] == 0


def test_start_and_finish_emits_progress_and_final(notifier):
    sent = []
    notifier.capture_func = lambda window=None: (PNG_1X1, {"window": None, "width": 1, "height": 1, "method": "test"})
    notifier.send_photo_func = lambda raw, caption=None, chat_id=None: (
        sent.append({"caption": caption, "chat_id": chat_id}),
        {"ok": True},
    )[1]

    assert notifier.start_job(
        "job-2",
        pp.ARCHITECT_TELEGRAM_ID,
        "programa una función que cuente palabras",
        kind="TEST",
    )
    notifier.note_output("job-2", "Archivo: dynamic_tools/contar_palabras.py")
    notifier.note_output("job-2", "╭──────────╮")

    deadline = time.time() + 4
    while not sent and time.time() < deadline:
        time.sleep(0.1)

    notifier.finish_job(
        "job-2",
        ok=True,
        summary="función validada",
        files=["dynamic_tools/contar_palabras.py"],
    )

    assert len(sent) == 2
    assert sent[0]["chat_id"] == pp.ARCHITECT_TELEGRAM_ID
    assert "AVANCE DEL PROGRAMA" in sent[0]["caption"]
    assert "contar\\_palabras.py" in sent[0]["caption"]
    assert "PROGRAMA COMPLETADO" in sent[1]["caption"]
    assert notifier.status()["active_count"] == 0


def test_identical_frames_are_deduplicated(notifier):
    sent = []
    notifier.capture_func = lambda window=None: (PNG_1X1, {"window": None, "width": 1, "height": 1, "method": "test"})
    notifier.send_photo_func = lambda raw, caption=None, chat_id=None: (
        sent.append(caption),
        {"ok": True},
    )[1]
    notifier.start_job("job-3", pp.ARCHITECT_TELEGRAM_ID, "programa algo", kind="TEST")

    deadline = time.time() + 4
    while not sent and time.time() < deadline:
        time.sleep(0.1)
    assert len(sent) == 1

    # Forzar un segundo tick del mismo frame: no debe duplicarse.
    session = notifier._sessions["job-3"]
    notifier._tick(session)
    assert len(sent) == 1

    notifier.finish_job("job-3", ok=False, summary="sin cambios")


def test_configure_clamps_interval(notifier):
    state = notifier.configure(interval_sec=1)
    assert state["interval_sec"] == pp.MIN_INTERVAL_SEC
    state = notifier.configure(interval_sec=99999)
    assert state["interval_sec"] == pp.MAX_INTERVAL_SEC
