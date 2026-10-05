"""
tests/test_network_shield.py - Pruebas Unitarias e Integración para Escudo de Red y Anti-Espionaje
===================================================================================================
GODWORKS SYSTEM v26.4
"""
import tempfile
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock
from core.network_shield import get_network_shield, NetworkShield
from core.hardware_controller import get_hardware_controller
from omni_temporal_control import process_hardware_chat_intent
from core.telegram_bridge import TelegramBridge


class TestNetworkShield:

    def test_network_shield_singleton(self):
        s1 = get_network_shield()
        s2 = get_network_shield()
        assert s1 is s2
        assert isinstance(s1, NetworkShield)

    def test_shield_status_keys(self):
        shield = get_network_shield()
        st = shield.get_status()
        assert st["ok"] is True
        assert "adblock_active" in st
        assert "antispy_active" in st
        assert "security_score" in st
        assert "grade" in st
        assert "devices_count" in st
        assert "devices" in st
        assert "blocked_domains_count" in st
        assert st["sinkhole_ip"] == "REDACTED_IP"

    def test_audit_network_structure(self):
        shield = get_network_shield()
        audit = shield.audit_network()
        assert audit["ok"] is True
        assert 0 <= audit["security_score"] <= 100
        assert audit["grade"] in ("A+ (Soberano)", "A", "B", "C (Vulnerable)")
        assert isinstance(audit["devices"], list)
        assert isinstance(audit["alerts"], list)
        assert audit["blocked_domains_count"] > 0

    def test_toggle_adblock_and_antispy(self):
        shield = get_network_shield()
        
        # Test toggling off with mock to prevent system file manipulation in quick test
        with patch.object(shield, "_deploy_to_dnsmasq", return_value=True):
            res_off = shield.toggle_adblock(False)
            assert shield.adblock_enabled is False
            assert res_off["adblock_active"] is False

            res_on = shield.toggle_adblock(True)
            assert shield.adblock_enabled is True
            assert res_on["adblock_active"] is True

            res_anti_off = shield.toggle_antispy(False)
            assert shield.antispy_enabled is False
            assert res_anti_off["antispy_active"] is False

            res_anti_on = shield.toggle_antispy(True)
            assert shield.antispy_enabled is True
            assert res_anti_on["antispy_active"] is True

    def test_hardware_controller_shield_dispatch(self):
        hw = get_hardware_controller()
        
        # shield_status
        res_st = hw.dispatch_action("shield_status")
        assert res_st["ok"] is True
        assert "security_score" in res_st

        # shield_audit
        res_aud = hw.dispatch_action("shield_audit")
        assert res_aud["ok"] is True
        assert "grade" in res_aud

        # shield_toggle_adblock
        with patch.object(hw.shield, "_deploy_to_dnsmasq", return_value=True):
            res_t = hw.dispatch_action("shield_toggle_adblock", {"enabled": True})
            assert res_t["ok"] is True
            assert res_t["adblock_active"] is True

    def test_omni_temporal_nlp_intent_and_slash(self):
        # Slash command /auditar
        slash_res = process_hardware_chat_intent("/auditar")
        assert slash_res is not None
        assert slash_res["action"] == "shield_audit"
        assert slash_res["direct_return"] is True
        assert "ESCUDO SOBERANO" in slash_res["system_feedback"]

        # Slash command /adblock
        ad_res = process_hardware_chat_intent("/adblock")
        assert ad_res is not None
        assert ad_res["action"] == "shield_toggle_adblock"

        # NLP Intent: "auditar y cuidar mi red"
        nlp_res = process_hardware_chat_intent("el sistema puede auditar y cuidar mi red, eliminar publicidad y evitar espionaje")
        assert nlp_res is not None
        assert nlp_res["action"] == "shield_audit"
        assert "BLINDAJE CIBERNÉTICO" in nlp_res["system_feedback"]

    def test_telegram_bridge_shield_commands(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "tg_test_cfg.json"
            bridge = TelegramBridge(config_path=cfg_path)
            chat_id = 123456
            bridge.authorized_chat_ids.add(chat_id)

            with patch.object(bridge, "send_message") as mock_msg:
                # 1. /auditar
                bridge._handle_incoming_text(chat_id, "/auditar", "SovereignUser")
                mock_msg.assert_called_once()
                args, _ = mock_msg.call_args
                msg_text = args[0]
                assert "ESCUDO SOBERANO" in msg_text
                assert "AUDITORÍA DE RED" in msg_text
                assert "DNS Sinkhole" in msg_text

            with patch.object(bridge, "send_message") as mock_msg2:
                # 2. /adblock
                bridge._handle_incoming_text(chat_id, "/adblock", "SovereignUser")
                mock_msg2.assert_called_once()
                args2, _ = mock_msg2.call_args
                assert "Filtro DNS Sinkhole (AdBlock)" in args2[0]
