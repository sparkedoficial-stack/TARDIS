import pytest
from core.task_manager import get_task_manager

def test_task_lifecycle():
    tm = get_task_manager()
    req_id = "test_req_123"
    info = tm.register(req_id, client_id="test_client", model="hermes3:8b")
    assert info["request_id"] == req_id
    assert info["client_id"] == "test_client"
    assert info["cancelled"] is False

    active = tm.list_active()
    assert any(t["request_id"] == req_id for t in active)

    cancelled = tm.cancel(request_id=req_id)
    assert req_id in cancelled
    assert info["cancel_event"].is_set()

    unreg = tm.unregister(req_id)
    assert unreg["request_id"] == req_id
