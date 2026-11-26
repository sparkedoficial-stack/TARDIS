"""Pruebas unitarias aisladas para core/network_traffic_controller.py (COEV-20261123-ADB934)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from core import network_traffic_controller as ntc


def test_network_traffic_controller_oui_classification_and_mocked_policies(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ntc, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ntc, "DEVICE_DB_FILE", tmp_path / "devices_db.json")
    monkeypatch.setattr(ntc, "CONTROL_POLICY_FILE", tmp_path / "policy.json")
    monkeypatch.setattr(ntc, "TRAFFIC_AUDIT_LOG_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(ntc, "NFT_CONTROLLER_FILE", tmp_path / "nft.conf")

    ctrl = ntc.TardisNetworkTrafficController()
    monkeypatch.setattr(ctrl, "_run_cmd", lambda args, timeout=4: subprocess.CompletedProcess(args, 0, "", ""))
    monkeypatch.setattr(ctrl, "_run_sudo", lambda args, timeout=5: subprocess.CompletedProcess(args, 0, "", ""))
    monkeypatch.setattr(ctrl, "apply_firewall_and_traffic_policy", lambda: {"ok": True, "mocked": True})

    vendor_apple = ctrl.resolve_oui_vendor("F4:D1:08:AA:BB:CC")
    vendor_rand = ctrl.resolve_oui_vendor("42:96:6F:11:22:33")
    assert isinstance(vendor_apple, str) and len(vendor_apple) > 0
    assert isinstance(vendor_rand, str) and len(vendor_rand) > 0

    cls = ctrl._classify_device(
        mac="14:13:33:01:02:03",
        ip="REDACTED_IP",
        iface="enp2s0",
        vendor="TP-Link",
        open_ports=[554, 80],
        mdns_info="",
        dhcp_hostname="tapo-c310",
    )
    assert isinstance(cls, (str, dict, tuple))

    ctrl.device_db["AA:BB:CC:DD:EE:FF"] = {
        "ip": "REDACTED_IP",
        "mac": "AA:BB:CC:DD:EE:FF",
        "alias": "Dispositivo Test",
        "trust_level": "UNKNOWN",
        "online": True,
    }
    res_meta = ctrl.set_device_metadata("AA:BB:CC:DD:EE:FF", alias="Lab Node", trust_level="TRUSTED")
    assert res_meta.get("ok") is True

    res_q = ctrl.quarantine_device("AA:BB:CC:DD:EE:FF", reason="test_isolation")
    assert res_q.get("ok") is True
    res_rel = ctrl.release_device("AA:BB:CC:DD:EE:FF")
    assert res_rel.get("ok") is True

    res_blk = ctrl.block_remote_endpoint("REDACTED_IP")
    assert res_blk.get("ok") is True
    res_unblk = ctrl.unblock_remote_endpoint("REDACTED_IP")
    assert res_unblk.get("ok") is True
