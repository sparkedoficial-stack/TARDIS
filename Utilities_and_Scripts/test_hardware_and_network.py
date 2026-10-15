"""
tests/test_hardware_and_network.py - Suite de Pruebas Unitarias de Hardware y Autonomía Wi-Fi
=============================================================================================
GODWORKS SYSTEM v26.4 - Suite Soberana de Control Temporal e Inteligencia Causal
"""
import pytest
from core.network_controller import NetworkController, WiFiKeepAliveDaemon, get_network_controller
from core.hardware_controller import HardwareController, get_hardware_controller


class TestNetworkController:
    """Pruebas del controlador de red y escaneo Wi-Fi."""

    def test_singleton_instance(self):
        c1 = get_network_controller()
        c2 = NetworkController.get_instance()
        assert c1 is c2

    def test_check_internet_access(self):
        ctrl = get_network_controller()
        res = ctrl.check_internet_access(timeout=2.0)
        assert isinstance(res, dict)
        assert "online" in res
        assert isinstance(res["online"], bool)

    def test_get_status(self):
        ctrl = get_network_controller()
        status = ctrl.get_status()
        assert status["ok"] is True
        assert "internet_online" in status
        assert "lan_ip" in status
        assert "devices" in status
        assert isinstance(status["devices"], list)

    def test_scan_networks(self):
        ctrl = get_network_controller()
        scan = ctrl.scan_networks(rescan=False)
        assert scan["ok"] is True
        assert "networks" in scan
        assert "count" in scan
        assert isinstance(scan["networks"], list)
        if scan["networks"]:
            first = scan["networks"][0]
            assert "ssid" in first
            assert "signal" in first
            assert "security" in first
            assert "is_open" in first

    def test_get_saved_connections(self):
        ctrl = get_network_controller()
        saved = ctrl.get_saved_connections()
        assert isinstance(saved, list)

    def test_wifi_keepalive_daemon(self):
        recovered_called = []

        def on_recover(info):
            recovered_called.append(info)

        daemon = WiFiKeepAliveDaemon(check_interval_seconds=1.0, on_recovered_callback=on_recover)
        st = daemon.get_status()
        assert st["enabled"] is True
        assert st["daemon_running"] is False
        daemon.set_enabled(False)
        assert daemon.enabled is False
        daemon.set_enabled(True)
        assert daemon.enabled is True


class TestHardwareController:
    """Pruebas del controlador unificado de hardware físico."""

    def test_singleton_instance(self):
        h1 = get_hardware_controller()
        h2 = HardwareController.get_instance()
        assert h1 is h2

    def test_audio_volume(self):
        hw = get_hardware_controller()
        vol = hw.get_volume()
        assert vol.get("ok") is True
        assert "percent" in vol
        assert 0 <= vol["percent"] <= 100

    def test_keyboard_brightness(self):
        hw = get_hardware_controller()
        kbd = hw.get_keyboard_brightness()
        assert kbd.get("ok") is True
        assert "level" in kbd
        assert 0 <= kbd["level"] <= 3

    def test_bluetooth_status(self):
        hw = get_hardware_controller()
        bt = hw.get_bluetooth_status()
        assert bt.get("ok") is True
        assert "powered" in bt
        assert isinstance(bt["powered"], bool)

    def test_power_profile(self):
        hw = get_hardware_controller()
        pwr = hw.get_power_profile()
        assert pwr.get("ok") is True
        assert "active_profile" in pwr

    def test_thermals_and_battery(self):
        hw = get_hardware_controller()
        tb = hw.get_thermals_and_battery()
        assert tb.get("ok") is True
        assert "temperatures" in tb

    def test_full_diagnostic(self):
        hw = get_hardware_controller()
        diag = hw.get_full_diagnostic()
        assert diag["ok"] is True
        assert "audio" in diag
        assert "keyboard" in diag
        assert "bluetooth" in diag
        assert "power_profile" in diag
        assert "network" in diag
        assert "display" in diag

    def test_dispatch_actions(self):
        hw = get_hardware_controller()
        # Test status dispatch
        res_st = hw.dispatch_action("status")
        assert res_st.get("ok") is True
        assert "audio" in res_st

        # Test wifi_status dispatch
        res_wifi = hw.dispatch_action("wifi_status")
        assert res_wifi.get("ok") is True
        assert "internet_online" in res_wifi

        # Test volume get dispatch
        res_vol = hw.dispatch_action("get_volume")
        assert res_vol.get("ok") is True
        assert "percent" in res_vol

        # Test unknown action
        res_err = hw.dispatch_action("unknown_xyz")
        assert res_err.get("ok") is False
