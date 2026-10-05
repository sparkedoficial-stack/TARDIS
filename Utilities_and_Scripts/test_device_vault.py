import pytest
import json
import time
from pathlib import Path
from core.device_vault import DeviceVault, get_device_vault
from core.security import is_request_authorized, verify_token


def test_device_vault_registration_and_persistence(tmp_path):
    vault_file = tmp_path / "test_devices.json"
    vault = DeviceVault(db_file=vault_file)

    # Initial state
    assert vault.is_device_authorized("dev_12345") is False
    assert len(vault.list_devices()) == 0

    # Short ID rejected
    assert vault.register_device("abc") is False
    assert vault.register_device("") is False

    # Valid registration
    assert vault.register_device("dev_phone_alpha", ip="REDACTED_IP", user_agent="Mozilla/5.0") is True
    assert vault.is_device_authorized("dev_phone_alpha") is True

    # Re-registration touches and increments count
    assert vault.register_device("dev_phone_alpha", ip="REDACTED_IP") is True
    devs = vault.list_devices()
    assert len(devs) == 1
    assert devs[0]["auth_count"] == 2
    assert devs[0]["last_ip"] == "REDACTED_IP"

    # Persistence verification: reload from disk in new instance
    new_vault = DeviceVault(db_file=vault_file)
    assert new_vault.is_device_authorized("dev_phone_alpha") is True
    assert new_vault.is_device_authorized("non_existent_device") is False
    assert new_vault.get_stats()["total_authorized_devices"] == 1


def test_device_vault_touch(tmp_path):
    vault_file = tmp_path / "test_touch.json"
    vault = DeviceVault(db_file=vault_file)
    vault.register_device("dev_laptop_001")
    
    dev = vault.list_devices()[0]
    time.sleep(0.01)
    vault.touch_device("dev_laptop_001", ip="REDACTED_IP")
    
    dev = vault.list_devices()[0]
    assert dev.get("last_seen_ts") is not None
    assert dev.get("last_ip") == "REDACTED_IP"


def test_security_device_authorization_flow():
    test_device = "dev_quantum_test_999"
    master_token = "REDACTED"

    # Step 1: Device without token and not yet registered -> Denied
    headers_initial = {"x-device-id": test_device}
    vault = get_device_vault()
    with vault._lock:
        vault._authorized_ids.discard(test_device)
        vault._devices_data.pop(test_device, None)

    assert is_request_authorized(headers_initial) is False

    # Step 2: Device provides token once along with X-Device-ID
    headers_with_token = {
        "x-api-key": master_token,
        "x-device-id": test_device
    }
    assert is_request_authorized(headers_with_token, client_ip="REDACTED_IP") is True

    # Step 3: Device now NEVER loses access - token no longer needed
    headers_subsequent = {"x-device-id": test_device}
    assert is_request_authorized(headers_subsequent, client_ip="REDACTED_IP") is True

    # Step 4: Device recognized via Cookie gia_device_id
    cookie_headers = {"cookie": f"gia_device_id={test_device}; theme=dark"}
    assert is_request_authorized(cookie_headers) is True

    # Step 5: Device recognized via Query Parameter
    query_params = {"device_id": test_device}
    assert is_request_authorized({}, query_params=query_params) is True

    # Clean up test device
    with vault._lock:
        vault._authorized_ids.discard(test_device)
        vault._devices_data.pop(test_device, None)
        vault._save()


def test_hardware_fingerprint_authorization_flow():
    test_fp = "dev_fp_1a2b3c4d5e6f7a8b"
    master_token = "REDACTED"
    vault = get_device_vault()

    # Step 1: Ensure clean state for test_fp
    with vault._lock:
        vault._authorized_ids.discard(test_fp)
        vault._devices_data.pop(test_fp, None)

    assert is_request_authorized({"x-device-fingerprint": test_fp}) is False

    # Step 2: Register via valid token + X-Device-Fingerprint
    auth_headers = {
        "x-api-key": master_token,
        "x-device-fingerprint": test_fp
    }
    assert is_request_authorized(auth_headers, client_ip="REDACTED_IP") is True

    # Step 3: Now access is granted with ONLY the hardware fingerprint (no token, no cookies)
    assert is_request_authorized({"x-device-fingerprint": test_fp}, client_ip="REDACTED_IP") is True

    # Step 4: Access granted via cookie gia_fp
    assert is_request_authorized({"cookie": f"gia_fp={test_fp}"}) is True

    # Clean up
    with vault._lock:
        vault._authorized_ids.discard(test_fp)
        vault._devices_data.pop(test_fp, None)
        vault._save()

