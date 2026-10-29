"""
tests/test_sovereign_autoprovision.py
Pruebas de la malla de cómputo y de la auto-provisión USB XG2TBK.
"""
from __future__ import annotations

import distributed_compute as dc
from core import hardware_autoprovision as ha


def test_local_subnets_returns_cidrs():
    nets = dc.local_subnets()
    assert isinstance(nets, list)
    assert nets, "debe detectar al menos una subred local"
    assert all("/" in n for n in nets)


def test_probe_ollama_local_is_tolerant():
    result = dc._probe_ollama("127.0.0.1", 11434, timeout=0.5)
    # Si el servicio está arriba debe devolver modelos; si no, None.
    assert result is None or "models" in result


def test_autoenroll_trusted_only_accepts_architect_hosts(monkeypatch):
    monkeypatch.setattr(
        dc, "_reverse_name",
        lambda ip: {"REDACTED_IP": "imac-14", "REDACTED_IP": "dns.google"}.get(ip, ""),
    )
    candidates = [
        {"url": "http://REDACTED_IP:11434", "models": ["qwen2.5:1.5b"]},
        {"url": "http://REDACTED_IP:11434", "models": []},
    ]
    result = dc.autoenroll_trusted(candidates, dry_run=True)
    enrolled = {item["url"] for item in result["enrolled"]}
    skipped = {item["url"] for item in result["skipped"]}
    assert enrolled == {"http://REDACTED_IP:11434"}
    assert skipped == {"http://REDACTED_IP:11434"}


def test_target_match_xg2tbk():
    assert ha._target_match("XG2TBK USB Audio")
    assert ha._target_match("alsa_card.usb-XG2-2TBK")
    assert not ha._target_match("Logitech G Pro X")


def test_best_output_profile_prefers_analog_stereo():
    card = {
        "profiles": [
            {"profile": "output:iec958-stereo", "priority": 9000, "available": True},
            {"profile": "output:analog-stereo", "priority": 6500, "available": True},
            {"profile": "input:analog-stereo", "priority": 6500, "available": True},
        ]
    }
    assert ha.best_output_profile(card) == "output:analog-stereo"


def test_apply_profile_dry_run(monkeypatch):
    monkeypatch.setattr(ha, "record_event", lambda *a, **k: None)
    target = {
        "kind": "sink",
        "sink": {"name": "alsa_output.usb-XG2TBK-00.analog-stereo"},
        "card": None,
    }
    result = ha.apply_profile(target, dry_run=True)
    assert result["target"] == "XG2TBK"
    assert any("set-default-sink" in action for action in result["actions"])
    assert any("s32le" in action for action in result["actions"])
