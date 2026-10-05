"""
tests/test_traffic_monitor.py - Pruebas Unitarias para el Monitor de Tráfico y Accesos a Dispositivos
====================================================================================================
GODWORKS SYSTEM v26.4
"""
import tempfile
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from core.traffic_monitor import get_traffic_monitor, TrafficMonitor
from core.hardware_controller import get_hardware_controller
from omni_temporal_control import process_hardware_chat_intent
from core.telegram_bridge import TelegramBridge


class TestTrafficMonitor:

    def test_traffic_monitor_singleton(self):
        m1 = get_traffic_monitor()
        m2 = get_traffic_monitor()
        assert m1 is m2
        assert isinstance(m1, TrafficMonitor)

    def test_parse_conntrack_line(self):
        mon = get_traffic_monitor()

        # 1. Outbound TCP connection from iPhone
        line_out = "tcp 6 431996 ESTABLISHED src=REDACTED_IP dst=REDACTED_IP sport=51030 dport=5223 src=REDACTED_IP dst=REDACTED_IP sport=5223 dport=51030 [ASSURED] mark=0 use=1"
        flow_out = mon._parse_conntrack_line(line_out)
        assert flow_out is not None
        assert flow_out["proto"] == "TCP"
        assert flow_out["src_ip"] == "REDACTED_IP"
        assert flow_out["dst_ip"] == "REDACTED_IP"
        assert flow_out["dport"] == 5223
        assert "Apple Push" in flow_out["service"]
        assert flow_out["flow_type"] == "OUTBOUND"
        assert flow_out["is_inbound"] is False

        # 2. Inbound access attempt from external IP to local port
        line_in = "tcp 6 120 SYN_RECV src=REDACTED_IP dst=REDACTED_IP sport=44123 dport=8757 src=REDACTED_IP dst=REDACTED_IP sport=8757 dport=44123 mark=0 use=1"
        flow_in = mon._parse_conntrack_line(line_in)
        assert flow_in is not None
        assert flow_in["flow_type"] == "INBOUND"
        assert flow_in["is_inbound"] is True
        assert flow_in["src_ip"] == "REDACTED_IP"
        assert flow_in["dport"] == 8757
        assert "GODWORKS Web HUD" in flow_in["service"]

        # 3. Inter-device connection (iPad to Gateway DNS)
        line_inter = "udp 17 25 src=REDACTED_IP dst=REDACTED_IP sport=54321 dport=53 src=REDACTED_IP dst=REDACTED_IP sport=53 dport=54321 mark=0 use=1"
        flow_inter = mon._parse_conntrack_line(line_inter)
        assert flow_inter is not None
        assert flow_inter["flow_type"] == "INTER_DEVICE"
        assert flow_inter["is_inter_device"] is True
        assert flow_inter["service"] == "DNS"

        # 4. Ignored loopback connection
        line_loop = "tcp 6 60 TIME_WAIT src=REDACTED_IP dst=REDACTED_IP sport=40000 dport=8757 src=REDACTED_IP dst=REDACTED_IP sport=8757 dport=40000 [ASSURED] mark=0 use=1"
        assert mon._parse_conntrack_line(line_loop) is None

    def test_analyze_traffic_structure(self):
        mon = get_traffic_monitor()
        res = mon.analyze_traffic_and_accesses()
        assert res["ok"] is True
        assert "total_active_flows" in res
        assert "inbound_access_count" in res
        assert "outbound_flows_count" in res
        assert "wifi_clients_active" in res
        assert "assessment" in res
        assert isinstance(res["active_flows"], list)
        assert isinstance(res["alerts"], list)

    def test_hardware_controller_traffic_dispatch(self):
        hw = get_hardware_controller()
        res = hw.dispatch_action("traffic_flows")
        assert res["ok"] is True
        assert "total_active_flows" in res
        assert "inbound_access_count" in res

    def test_omni_temporal_slash_command_trafico(self):
        res = process_hardware_chat_intent("/trafico")
        assert res is not None
        assert res["action"] == "traffic_flows"
        assert res["direct_return"] is True
        assert "AUDITORÍA DE TRÁFICO" in res["system_feedback"]

    def test_omni_temporal_nlp_intent_quien_accede(self):
        res = process_hardware_chat_intent("quiero analizar quien accede a mis dispositivos y ver el trafico conectado a la red wifi")
        assert res is not None
        assert res["action"] == "device_access_audit"
        assert res["direct_return"] is True
        assert "AUDITORÍA DE TRÁFICO Y ACCESOS" in res["system_feedback"]

    def test_telegram_bridge_trafico_command(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "tg_test_cfg.json"
            bridge = TelegramBridge(config_path=cfg_path)
            chat_id = 999888
            bridge.authorized_chat_ids.add(chat_id)

            with patch.object(bridge, "send_message") as mock_msg:
                bridge._handle_incoming_text(chat_id, "/trafico", "SovereignUser")
                mock_msg.assert_called_once()
                args, _ = mock_msg.call_args
                msg_text = args[0]
                assert "AUDITORÍA DE TRÁFICO & ACCESOS" in msg_text
                assert "Flujos Totales:" in msg_text

    def test_resolve_organization(self):
        mon = get_traffic_monitor()

        # Apple
        org_apple = mon.resolve_organization("REDACTED_IP")
        assert org_apple["organization"] == "Apple Inc."
        assert org_apple["is_known"] is True
        assert "Apple" in org_apple["category"]

        # Cloudflare
        org_cf = mon.resolve_organization("REDACTED_IP")
        assert org_cf["organization"] == "Cloudflare Inc."
        assert org_cf["is_known"] is True

        # Telegram
        org_tg = mon.resolve_organization("REDACTED_IP")
        assert org_tg["organization"] == "Telegram Messenger Inc."
        assert org_tg["is_known"] is True

        # Google
        org_goog = mon.resolve_organization("REDACTED_IP")
        assert org_goog["organization"] == "Google LLC / Alphabet"

        # Local
        org_loc = mon.resolve_organization("REDACTED_IP")
        assert org_loc["is_local"] is True

    def test_get_recurring_traffic_report_structure(self):
        mon = get_traffic_monitor()
        rep = mon.get_recurring_traffic_report()
        assert rep["ok"] is True
        assert "recurring_organizations" in rep
        assert "device_breakdown" in rep
        assert "assessment" in rep
        assert "formatted_report" in rep
        assert "INFORME DE ENTIDADES QUE RECIBEN TU TRÁFICO" in rep["formatted_report"]

    def test_hardware_controller_recurring_traffic_dispatch(self):
        hw = get_hardware_controller()
        res = hw.dispatch_action("recurring_traffic")
        assert res["ok"] is True
        assert "recurring_organizations" in res
        assert "formatted_report" in res

    def test_omni_temporal_slash_command_recurrentes(self):
        res = process_hardware_chat_intent("/recurrentes")
        assert res is not None
        assert res["action"] == "recurring_traffic_report"
        assert res["direct_return"] is True
        assert "INFORME DE ENTIDADES QUE RECIBEN TU TRÁFICO" in res["system_feedback"]

    def test_omni_temporal_nlp_intent_quien_tiene_mi_trafico(self):
        res = process_hardware_chat_intent("reportar quien tiene mi tráfico recurrentemente")
        assert res is not None
        assert res["action"] == "recurring_traffic_report"
        assert res["direct_return"] is True
        assert "INFORME DE ENTIDADES QUE RECIBEN TU TRÁFICO" in res["system_feedback"]

    def test_telegram_bridge_recurrentes_command(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "tg_test_cfg.json"
            bridge = TelegramBridge(config_path=cfg_path)
            chat_id = 999888
            bridge.authorized_chat_ids.add(chat_id)

            with patch.object(bridge, "send_message") as mock_msg:
                bridge._handle_incoming_text(chat_id, "/recurrentes", "SovereignUser")
                mock_msg.assert_called_once()
                args, _ = mock_msg.call_args
                msg_text = args[0]
                assert "INFORME DE ENTIDADES QUE RECIBEN TU TRÁFICO" in msg_text

