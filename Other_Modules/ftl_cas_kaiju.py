"""
modulos_ftl/ftl_cas_kaiju.py - Puente Soberano FTL para CaS · Cognitive & Context as a Service
==============================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU

Expone el motor CaS (`core.cas_neural_space_kaiju`) como módulo de primera clase
del Master Hub FTL, con despacho individual no bloqueante:

  - status     : versión, endpoint, telemetría y estado AEGIS.
  - context    : construye un bundle cognitivo multi-fuente.
  - compress   : compresión extractiva sintrópica de texto.
  - telemetry  : contadores acumulados del motor.
  - sources    : salud y firmas de las fuentes de contexto.
  - aegis      : verificación de La Constante AEGIS.
  - selftest   : prueba integral de humo.
  - serve      : instrucciones de servicio (no bloquea el proceso llamador).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

GODWORKS_ROOT = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM")
if str(GODWORKS_ROOT) not in sys.path:
    sys.path.insert(0, str(GODWORKS_ROOT))


class FtlCasKaiju:
    """Control individual de CaS desde FTL, TARDIS y AGY."""

    name = "cas_kaiju"

    def _engine(self):
        from core.cas_neural_space_kaiju import get_cas

        return get_cas()

    def _meta(self) -> Dict[str, Any]:
        from core.cas_neural_space_kaiju import DEFAULT_HOST, DEFAULT_PORT, VERSION

        return {
            "version": VERSION,
            "endpoint": f"http://{DEFAULT_HOST}:{DEFAULT_PORT}",
            "dashboard": f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/dashboard",
            "service": "cas-kaiju.service",
            "source_file": str(Path(__file__).resolve()),
        }

    def run(self, action: str = "status", **kwargs: Any) -> Dict[str, Any]:
        action = (action or "status").lower().strip()
        try:
            if action in ("status", "health", "info"):
                engine = self._engine()
                return {
                    "status": "ok",
                    **self._meta(),
                    "telemetry": engine.telemetry(),
                    "aegis": engine.verify_aegis(),
                    "sources": engine.sources_status(),
                }

            if action in ("context", "build", "build_context"):
                engine = self._engine()
                query = str(kwargs.get("query") or kwargs.get("prompt") or "")
                profile = str(kwargs.get("profile") or "interactive")
                budget = int(kwargs.get("budget") or kwargs.get("budget_tokens") or 6000)
                bundle = engine.build_context(query, profile=profile, budget_tokens=budget)
                return {"status": "ok", **bundle.to_dict()}

            if action in ("compress", "compression"):
                engine = self._engine()
                text = str(kwargs.get("text") or kwargs.get("query") or "")
                if not text.strip():
                    return {"status": "error", "error": "Parámetro 'text' requerido."}
                result = engine.compress_text(
                    text,
                    query=str(kwargs.get("focus") or kwargs.get("focus_query") or ""),
                    ratio=float(kwargs.get("ratio") or 0.55),
                    max_tokens=(
                        int(kwargs["max_tokens"]) if kwargs.get("max_tokens") is not None else None
                    ),
                )
                return {"status": "ok", **result}

            if action in ("telemetry", "stats"):
                return {"status": "ok", **self._meta(), "telemetry": self._engine().telemetry()}

            if action in ("sources", "source", "health_sources"):
                engine = self._engine()
                sources = engine.sources_status()
                return {
                    "status": "ok",
                    "total": len(sources),
                    "healthy": sum(1 for item in sources if item.get("ok")),
                    "sources": sources,
                }

            if action in ("aegis", "verify", "verify_aegis"):
                return {"status": "ok", **self._engine().verify_aegis()}

            if action in ("selftest", "self_test", "test"):
                return self._selftest(str(kwargs.get("query") or ""))

            if action == "serve":
                return {
                    "status": "ok",
                    "blocking": False,
                    "message": "El servicio se gestiona con systemd --user; no se bloquea el llamador.",
                    **self._meta(),
                    "commands": [
                        "systemctl --user start cas-kaiju.service",
                        "systemctl --user restart cas-kaiju.service",
                        "systemctl --user status cas-kaiju.service --no-pager",
                    ],
                }

            return {
                "status": "error",
                "error": f"Acción '{action}' no reconocida.",
                "available_actions": [
                    "status",
                    "context",
                    "compress",
                    "telemetry",
                    "sources",
                    "aegis",
                    "selftest",
                    "serve",
                ],
            }
        except Exception as exc:  # fail-safe: nunca tumba al Master Hub
            return {"status": "error", "action": action, "error": f"{type(exc).__name__}: {exc}"}

    def _selftest(self, query: str = "") -> Dict[str, Any]:
        from core.cas_neural_space_kaiju import CANONICAL_AEGIS

        engine = self._engine()
        query = query or "estado de continuidad, memoria akáshica y telemetría del núcleo"
        started = time.perf_counter()
        bundle = engine.build_context(query, profile="deep", budget_tokens=6000)
        checks = {
            "context_non_empty": len(bundle.context_text) > 200,
            "aegis_complete": all(anchor in bundle.context_text for anchor in CANONICAL_AEGIS),
            "bundle_ok": bundle.ok,
            "within_budget": bundle.used_tokens <= bundle.budget_tokens,
            "has_citations": "[S1]" in bundle.context_text,
            "sources_ok": any(item["ok"] for item in bundle.source_report),
        }
        return {
            "status": "ok" if all(checks.values()) else "error",
            "ok": all(checks.values()),
            "checks": checks,
            "elapsed_s": round(time.perf_counter() - started, 3),
            "used_tokens": bundle.used_tokens,
            "budget_tokens": bundle.budget_tokens,
            "compression_ratio": bundle.compression_ratio,
            "chunks": len(bundle.chunks),
            "aegis": bundle.aegis,
            "sources": bundle.source_report,
        }


def get_ftl_cas_kaiju() -> FtlCasKaiju:
    return FtlCasKaiju()


if __name__ == "__main__":
    import json

    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    print(json.dumps(get_ftl_cas_kaiju().run(action), ensure_ascii=False, indent=2))
