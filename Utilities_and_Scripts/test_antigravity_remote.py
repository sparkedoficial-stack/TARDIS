"""
tests/test_antigravity_remote.py
================================
Pruebas automatizadas del sistema de control remoto de conversaciones
GODWORKS SYSTEM v26.4 · TARDIS <-> Antigravity GUI
"""

import pytest
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.antigravity_remote_controller import (
    AntigravityRemoteController,
    get_remote_controller,
    CURRENT_CONVERSATION_ID,
    CLI_SUMMARIES_DB,
    GUI_SUMMARIES_DB,
    APP_STORAGE_FILE
)


def test_remote_controller_singleton():
    ctrl1 = get_remote_controller()
    ctrl2 = get_remote_controller()
    assert ctrl1 is ctrl2
    assert ctrl1.target_conversation_id == CURRENT_CONVERSATION_ID


def test_sync_session():
    ctrl = get_remote_controller()
    res = ctrl.sync_session()
    assert res.get("ok") is True
    assert res.get("conversation_id") == CURRENT_CONVERSATION_ID
    assert res.get("db_synced") is True
    assert res.get("symlinks_ok") is True
    assert res.get("storage_synced") is True


def test_get_gui_status():
    ctrl = get_remote_controller()
    status = ctrl.get_gui_status()
    assert status.get("ok") is True
    assert "running" in status
    assert "cdp_available" in status
    assert "target_conversation_open" in status
    assert status.get("target_conversation_id") == CURRENT_CONVERSATION_ID


def test_open_conversation_idempotent():
    ctrl = get_remote_controller()
    res = ctrl.open_conversation_in_gui(CURRENT_CONVERSATION_ID)
    assert res.get("ok") is True
    assert res.get("conversation_id") == CURRENT_CONVERSATION_ID
    assert "sync" in res
