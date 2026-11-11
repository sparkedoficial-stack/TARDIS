"""
modulos_ftl/ftl_music_maestro.py — Puente FTL al Music Maestro de TARDIS
=======================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU

Despacha individualmente el subsistema musical soberano (YouTube Music +
mpv + director de soundtrack) desde FTL, el Omni-Tool Bridge y AgentHarness.

Acciones:
    status, search, play, pause, resume, toggle, next, prev, stop, volume,
    seek, soundtrack, scenes, queue, queue_add, queue_clear, favorites,
    favorite_toggle, history, doctor, autopilot, duck, unduck

Uso directo:
    python3 -m modulos_ftl.ftl_music_maestro status
    python3 -m modulos_ftl.ftl_music_maestro search "Hans Zimmer Time"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class FTLMusicMaestro:
    """Envoltorio FTL con interfaz `run(action, **kwargs)`."""

    name = "TARDIS Music Maestro"
    domain = "music_soundtrack"
    version = "1.0"

    def run(self, action: str = "status", **kwargs: Any) -> Dict[str, Any]:
        from core.tardis_music_maestro import music_command

        action = (action or "status").lower().replace("-", "_")
        if action == "favorite_toggle":
            return music_command("favorite_toggle", track=kwargs.get("track"))
        if action == "queue_add":
            return music_command("queue_add", query=kwargs.get("query", ""))
        if action == "queue_clear":
            return music_command("queue_clear")
        return music_command(action, **kwargs)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    action = args[0] if args else "status"
    params: Dict[str, Any] = {}
    if len(args) > 1:
        params["query"] = " ".join(args[1:])
    result = FTLMusicMaestro().run(action, **params)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if isinstance(result, dict) and result.get("status") in ("ok", "building", "degraded") else 1


if __name__ == "__main__":
    raise SystemExit(main())
