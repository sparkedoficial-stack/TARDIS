"""Módulo FTL: peticiones de cambio y mejora hacia los agentes de Qoder.

Se autocarga vía ftl_master_hub (clase QoderChangeRequest con método run).
Sólo deposita y consulta la bandeja; no ejecuta nada por sí mismo.
"""

import json
import sys
from pathlib import Path

GODWORKS_ROOT = "/home/timemachine/Escritorio/GODWORKS SYSTEM"
if GODWORKS_ROOT not in sys.path:
    sys.path.insert(0, GODWORKS_ROOT)

try:
    from core import qoder_request_bridge as _bridge
except Exception:
    _spec_path = Path(GODWORKS_ROOT) / "core" / "qoder_request_bridge.py"
    import importlib.util

    _spec = importlib.util.spec_from_file_location("qoder_request_bridge", str(_spec_path))
    _bridge = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_bridge)


class QoderChangeRequest:
    """Puente soberano FTL -> Qoder: solicitar cambios, mejoras o investigación."""

    SOURCE = "ftl:qoder_change_request"

    def run(self, action="stats", **kwargs):
        action = (action or "stats").strip().lower()

        if action in ("submit", "request", "ask"):
            return _bridge.submit_request(
                source=kwargs.get("source") or self.SOURCE,
                kind=kwargs.get("kind", "improvement"),
                title=kwargs.get("title", ""),
                body=kwargs.get("body", "") or kwargs.get("message", ""),
                target_files=kwargs.get("target_files") or kwargs.get("files") or [],
                evidence=kwargs.get("evidence") or [],
                risk=kwargs.get("risk", "low"),
                priority=kwargs.get("priority", "normal"),
                context=kwargs.get("context") or {},
            )

        if action in ("list", "pending"):
            states = kwargs.get("states") or kwargs.get("state")
            if isinstance(states, str):
                states = [states]
            return {"ok": True, "requests": _bridge.list_requests(states)}

        if action in ("status", "show", "get"):
            request_id = kwargs.get("request_id") or kwargs.get("id") or ""
            record = _bridge.get_request(request_id)
            return record or {"ok": False, "error": "not_found", "request_id": request_id}

        if action in ("update", "set_status", "answer"):
            return _bridge.update_status(
                kwargs.get("request_id") or kwargs.get("id") or "",
                kwargs.get("status", "triaged"),
                note=kwargs.get("note", ""),
            )

        if action == "wait":
            return self._wait_for_answer(
                kwargs.get("request_id") or kwargs.get("id") or "",
                timeout_s=float(kwargs.get("timeout_s", 60.0)),
            )

        return _bridge.stats()

    def _wait_for_answer(self, request_id, timeout_s=60.0, poll_s=2.0):
        import time

        deadline = time.time() + max(0.0, min(timeout_s, 900.0))
        last = None
        while time.time() < deadline:
            last = _bridge.get_request(request_id)
            if last and last.get("status") != "queued":
                return {"ok": True, "request_id": request_id, "status": last["status"], "decision": last.get("decision")}
            time.sleep(poll_s)
        return {"ok": False, "timeout": True, "request_id": request_id, "status": (last or {}).get("status", "queued")}


if __name__ == "__main__":
    hub_module = QoderChangeRequest()
    print(json.dumps(hub_module.run(), indent=2, ensure_ascii=False))
    demo = hub_module.run(
        action="submit",
        kind="question",
        title="Demo desde tardis --self-test FTL",
        body="¿El puente FTL->Qoder está operativo? Responde con el estado de la bandeja.",
        risk="low",
    )
    print(json.dumps(demo, indent=2, ensure_ascii=False))
    if demo.get("ok"):
        print(json.dumps(hub_module.run(action="status", request_id=demo["request_id"]), indent=2, ensure_ascii=False))
