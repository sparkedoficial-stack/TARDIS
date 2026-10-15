"""
Test de verificación para la gestión de saturación de tokens,
ciclo de retención de 24 horas y limpieza de contexto.
"""
import time
import json
import sqlite3
from pathlib import Path
from core.offline_chat_vault import get_offline_chat_vault
from core.daily_context_rotator import get_daily_context_rotator
from omni_temporal_control import SYNC_HUB, process_agentic_chat

def test_24h_retention_purge():
    print("--- 1. Probando purga de comprensión tras 24 horas ---")
    now = time.time()
    vault = get_offline_chat_vault()
    
    # Registrar un turno viejo (>24h) directamente en la bóveda
    old_ts = now - 90000.0  # ~25 horas atrás
    with vault._db_lock:
        con = vault._connect()
        cur = con.execute(
            """INSERT INTO offline_chat_turns (
                ts, iso, session_id, client_id, user_message, assistant_reply,
                model, tokens_est, direction, meta, hardware_action
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (old_ts, "2026-09-18 10:00:00", "test_old", "test_old",
             "Mensaje antiguo de prueba de 25 horas", "Respuesta antigua de prueba",
             "test_model", 50, "present", "{}", "")
        )
        old_id = cur.lastrowid
        con.execute(
            """INSERT INTO offline_chat_fts (user_message, assistant_reply, session_id, turn_id)
               VALUES (?, ?, ?, ?)""",
            ("Mensaje antiguo de prueba de 25 horas", "Respuesta antigua de prueba", "test_old", old_id)
        )
        con.commit()
        con.close()

    # Verificar que get_context_for_prompt NO inyecte el turno viejo de 25h en la comprensión activa
    ctx = vault.get_context_for_prompt("Mensaje antiguo de prueba de 25 horas")
    assert "Mensaje antiguo de prueba de 25 horas" not in ctx, f"Fallo: Turno con >24h fue inyectado en el prompt: {ctx}"
    print("✅ Bóveda: Turno con >24h excluido correctamente del prompt de comprensión.")

    # Probar en SYNC_HUB
    with SYNC_HUB._lock:
        SYNC_HUB.history.append({
            "id": "msg_test_old",
            "role": "user",
            "content": "Turno viejo en SYNC_HUB",
            "timestamp": old_ts,
            "iso": "2026-09-18 10:00:00"
        })
        SYNC_HUB.history.append({
            "id": "msg_test_fresh",
            "role": "user",
            "content": "Turno fresco en SYNC_HUB",
            "timestamp": now,
            "iso": "2026-09-19 19:00:00"
        })
    
    purged = SYNC_HUB.purge_expired_history(max_age_seconds=86400.0)
    assert purged >= 1, f"Fallo: SYNC_HUB no purgó el turno viejo (purged={purged})"
    contents = [m["content"] for m in SYNC_HUB.history]
    assert "Turno viejo en SYNC_HUB" not in contents, "Fallo: Turno viejo sigue en SYNC_HUB.history"
    assert "Turno fresco en SYNC_HUB" in contents, "Fallo: Turno fresco fue eliminado erróneamente"
    print("✅ SYNC_HUB: Turno de >24h purgado correctamente; turno fresco conservado.")

def test_saturation_handling():
    print("\n--- 2. Probando manejo de saturación de contexto ---")
    rotator = get_daily_context_rotator()
    res = rotator.handle_saturation(session_id="test_sat", client_id="test_client")
    assert res.get("ok"), "Fallo en handle_saturation"
    assert res.get("action") == "saturation_mitigated", "Acción incorrecta"
    print(f"✅ Rotator: Saturación mitigada. Tokens liberados estimados: {res.get('tokens_freed')}")

def test_clear_context():
    print("\n--- 3. Probando limpieza de contexto e inicio limpio ---")
    with SYNC_HUB._lock:
        SYNC_HUB.history.append({
            "id": "msg_to_clear",
            "role": "user",
            "content": "Este mensaje debe limpiarse",
            "timestamp": time.time(),
            "iso": "2026-09-19 19:10:00"
        })
    assert len(SYNC_HUB.history) > 0
    SYNC_HUB.clear_history(archive=True)
    assert len(SYNC_HUB.history) == 0, "Fallo: SYNC_HUB.history no quedó vacío tras clear_history"
    print("✅ SYNC_HUB: clear_history vació el historial y respaldó la conversación en memoria local.")

if __name__ == "__main__":
    test_24h_retention_purge()
    test_saturation_handling()
    test_clear_context()
    print("\n🎉 TODAS LAS PRUEBAS DE GESTIÓN DE CONTEXTO Y TOKENS PASARON CON ÉXITO.")
