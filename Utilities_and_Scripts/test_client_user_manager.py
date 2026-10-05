import pytest
import json
import time
from pathlib import Path
from core.device_vault import DeviceVault
from core.protected_users_vault import ARCHITECT_TELEGRAM_ID


def test_device_vault_revoke_individual_device(tmp_path):
    vault_file = tmp_path / "test_devices_revocation.json"
    vault = DeviceVault(db_file=vault_file)

    vault.register_device("device_alpha", client_name="Cliente Alpha")
    vault.register_device("device_beta", client_name="Cliente Beta")

    assert vault.is_device_authorized("device_alpha") is True
    assert vault.is_device_authorized("device_beta") is True
    assert len(vault.list_devices()) == 2

    # Revoke single device
    assert vault.revoke_device("device_alpha") is True
    assert vault.is_device_authorized("device_alpha") is False
    assert vault.is_device_authorized("device_beta") is True
    assert len(vault.list_devices()) == 1

    # Revoking again returns False
    assert vault.revoke_device("device_alpha") is False

    # Persistence check
    reloaded = DeviceVault(db_file=vault_file)
    assert reloaded.is_device_authorized("device_alpha") is False
    assert reloaded.is_device_authorized("device_beta") is True


def test_telegram_config_security_rules(tmp_path):
    cfg_file = tmp_path / "telegram_config.json"
    initial_data = {
        "allowed_chats": [ARCHITECT_TELEGRAM_ID, 12345678],
        "admin_chat_id": ARCHITECT_TELEGRAM_ID,
        "allowed_phones": ["+529841112233"]
    }
    cfg_file.write_text(json.dumps(initial_data), encoding="utf-8")

    # Architect cannot be removed
    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert ARCHITECT_TELEGRAM_ID in data["allowed_chats"]
    assert data["admin_chat_id"] == ARCHITECT_TELEGRAM_ID

    # Adding new chat
    new_chat = 99887766
    if new_chat not in data["allowed_chats"]:
        data["allowed_chats"].append(new_chat)
    cfg_file.write_text(json.dumps(data), encoding="utf-8")

    reloaded = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert new_chat in reloaded["allowed_chats"]
    assert ARCHITECT_TELEGRAM_ID in reloaded["allowed_chats"]

    # Removing non-architect chat
    reloaded["allowed_chats"].remove(new_chat)
    cfg_file.write_text(json.dumps(reloaded), encoding="utf-8")

    final_data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert new_chat not in final_data["allowed_chats"]
    assert ARCHITECT_TELEGRAM_ID in final_data["allowed_chats"]


def test_invitations_vault_lifecycle(tmp_path):
    vpath = tmp_path / "missions_vault.json"
    vdata = {
        "version": "26.4",
        "invitations": []
    }
    vpath.write_text(json.dumps(vdata), encoding="utf-8")

    # Create invitation
    tok = "test_inv_token_12345"
    record = {
        "token": tok,
        "note": "Test Client",
        "created_ts": time.time(),
        "expires_ts": time.time() + 3600,
        "status": "ACTIVE"
    }
    vdata["invitations"].append(record)
    vpath.write_text(json.dumps(vdata), encoding="utf-8")

    # Read back
    saved = json.loads(vpath.read_text(encoding="utf-8"))
    assert len(saved["invitations"]) == 1
    assert saved["invitations"][0]["token"] == tok

    # Revoke invitation
    saved["invitations"] = [i for i in saved["invitations"] if i["token"] != tok]
    vpath.write_text(json.dumps(saved), encoding="utf-8")

    empty = json.loads(vpath.read_text(encoding="utf-8"))
    assert len(empty["invitations"]) == 0
