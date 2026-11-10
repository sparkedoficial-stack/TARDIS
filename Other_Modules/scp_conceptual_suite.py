#!/usr/bin/env python3
"""Suite Computacional de Objetos Conceptuales SCP.

Traduce cinco conceptos de ficción especulativa (registrados en la conversación
local ``offline_chats.db`` #2286) a implementaciones algorítmicas reales,
deterministas y verificables en software:

1. SCP-001 ("La Biblioteca del Fin del Mundo") -> ``BabelInfiniteLibrary``
   Biyección criptográfica reversible (red Feistel balanceada de 4 rondas sobre
   bloques de 1920 bits / páginas de 320 símbolos en alfabeto de 64 caracteres).
   Localiza en O(L) la coordenada exacta de cualquier página posible y la
   reconstruye sin almacenamiento masivo.
2. SCP-002 ("La Máquina del Tiempo") -> ``BranchingTimeMachine``
   Motor de navegación sobre instantáneas históricas (SQLite / historial local)
   donde cada salto o modificación contrafactual bifurca una rama paralela
   inmutable en un grafo acíclico dirigido (DAG).
3. SCP-003 ("El Código del Universo") -> ``UniverseCodeSimulator``
   Simulador discreto de campo + autómata celular gobernado por un genoma
   numérico de 24 dígitos. Permite mutar un único dígito y cuantificar la
   transición de fase, entropía de Shannon y divergencia estructural resultante.
4. SCP-004 ("La Cámara de la Verdad") -> ``TruthInspectionCamera``
   Inspector forense determinista para archivos, imágenes o texto: huellas
   SHA-256/BLAKE2b, entropía de bytes, validación de cabeceras mágicas frente a
   extensión, resolución de imagen (PNG/JPEG) y registro en rama temporal.
5. SCP-005 ("La Máquina de la Creación") -> ``ProceduralCreationEngine``
   Generador procedural que sintetiza especificaciones digitales estructuradas
   (JSON) y geometría vectorial determinista (SVG) para artefactos o entidades
   simuladas, bifurcando una rama en el registro temporal en cada creación.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import struct
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "scp_suite.db"
DEFAULT_CREATIONS_DIR = DATA_DIR / "scp_creations"
OFFLINE_CHATS_DB = DATA_DIR / "offline_chats.db"

# Exactamente 64 símbolos únicos (6 bits por símbolo)
BABEL_ALPHABET: str = (
    "abcdefghijklmnopqrstuvwxyz"
    "áéíóúüñ"
    "REDACTED_PHONE"
    " "
    ".,;:!?-'\"()/\n_+=*#%&"
)
assert len(BABEL_ALPHABET) == 64 and len(set(BABEL_ALPHABET)) == 64, (
    f"BABEL_ALPHABET debe tener exactamente 64 símbolos únicos (actual={len(BABEL_ALPHABET)})"
)

CHAR_TO_INDEX: Dict[str, int] = {ch: idx for idx, ch in enumerate(BABEL_ALPHABET)}
BABEL_PAGE_LEN: int = 320  # 320 * 6 bits = 1920 bits = 240 bytes exactos
BABEL_BLOCK_BYTES: int = 240
BABEL_HALF_BYTES: int = 120

DEFAULT_UNIVERSE_CODE: str = "137035999084271828182845"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shannon_entropy_bytes(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    total = len(data)
    entropy = 0.0
    for c in counts:
        if c:
            p = c / total
            entropy -= p * math.log2(p)
    return round(entropy, 6)


@dataclass
class TimelineBranch:
    branch_id: str
    parent_branch_id: Optional[str]
    origin_subsystem: str
    created_at: str
    divergence_summary: str
    state_hash: str
    state_payload: Dict[str, Any]


class TemporalBranchLedger:
    """DAG persistente en SQLite para ramas temporales inmutables."""

    MAINLINE_ID = "branch_000000000000"

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scp_timelines (
                    branch_id TEXT PRIMARY KEY,
                    parent_branch_id TEXT,
                    origin_subsystem TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    divergence_summary TEXT NOT NULL,
                    state_hash TEXT NOT NULL,
                    state_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scp_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    branch_id TEXT NOT NULL,
                    subsystem TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            cur = conn.execute(
                "SELECT branch_id FROM scp_timelines WHERE branch_id = ?",
                (self.MAINLINE_ID,),
            )
            if cur.fetchone() is None:
                genesis_payload = {"genesis": True, "description": "Línea base de referencia"}
                genesis_json = json.dumps(genesis_payload, ensure_ascii=False, sort_keys=True)
                state_hash = hashlib.sha256(genesis_json.encode("utf-8")).hexdigest()[:16]
                conn.execute(
                    """
                    INSERT INTO scp_timelines (
                        branch_id, parent_branch_id, origin_subsystem,
                        created_at, divergence_summary, state_hash, state_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.MAINLINE_ID,
                        None,
                        "GENESIS",
                        _utc_iso(),
                        "Inicialización de la línea temporal base",
                        state_hash,
                        genesis_json,
                    ),
                )
            conn.commit()

    def fork_branch(
        self,
        origin_subsystem: str,
        divergence_summary: str,
        state_payload: Dict[str, Any],
        parent_branch_id: str = MAINLINE_ID,
    ) -> TimelineBranch:
        now = _utc_iso()
        state_json = json.dumps(state_payload, ensure_ascii=False, sort_keys=True)
        state_hash = hashlib.sha256(state_json.encode("utf-8")).hexdigest()
        seed = f"{parent_branch_id}|{origin_subsystem}|{now}|{state_hash}|{ os.urandom(4).hex() }"
        branch_id = "branch_" + hashlib.blake2b(seed.encode("utf-8"), digest_size=6).hexdigest()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scp_timelines (
                    branch_id, parent_branch_id, origin_subsystem,
                    created_at, divergence_summary, state_hash, state_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    branch_id,
                    parent_branch_id,
                    origin_subsystem,
                    now,
                    divergence_summary,
                    state_hash[:16],
                    state_json,
                ),
            )
            conn.execute(
                """
                INSERT INTO scp_events (
                    branch_id, subsystem, event_type, created_at, summary, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    branch_id,
                    origin_subsystem,
                    "BRANCH_FORK",
                    now,
                    divergence_summary,
                    state_json,
                ),
            )
            conn.commit()

        return TimelineBranch(
            branch_id=branch_id,
            parent_branch_id=parent_branch_id,
            origin_subsystem=origin_subsystem,
            created_at=now,
            divergence_summary=divergence_summary,
            state_hash=state_hash[:16],
            state_payload=state_payload,
        )

    def record_event(
        self,
        subsystem: str,
        event_type: str,
        summary: str,
        payload: Dict[str, Any],
        branch_id: str = MAINLINE_ID,
    ) -> int:
        now = _utc_iso()
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO scp_events (
                    branch_id, subsystem, event_type, created_at, summary, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (branch_id, subsystem, event_type, now, summary, payload_json),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_branch(self, branch_id: str) -> Optional[TimelineBranch]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM scp_timelines WHERE branch_id = ?", (branch_id,)
            ).fetchone()
            if row is None:
                return None
            return TimelineBranch(
                branch_id=row["branch_id"],
                parent_branch_id=row["parent_branch_id"],
                origin_subsystem=row["origin_subsystem"],
                created_at=row["created_at"],
                divergence_summary=row["divergence_summary"],
                state_hash=row["state_hash"],
                state_payload=json.loads(row["state_json"]),
            )

    def trace_lineage(self, branch_id: str) -> List[Dict[str, Any]]:
        chain: List[Dict[str, Any]] = []
        current_id: Optional[str] = branch_id
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            b = self.get_branch(current_id)
            if b is None:
                break
            chain.append(
                {
                    "branch_id": b.branch_id,
                    "parent_branch_id": b.parent_branch_id,
                    "origin_subsystem": b.origin_subsystem,
                    "created_at": b.created_at,
                    "divergence_summary": b.divergence_summary,
                    "state_hash": b.state_hash,
                }
            )
            current_id = b.parent_branch_id
        chain.reverse()
        return chain

    def list_branches(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scp_timelines ORDER BY rowid DESC LIMIT ?", (limit,)
            ).fetchall()
            return [
                {
                    "branch_id": r["branch_id"],
                    "parent_branch_id": r["parent_branch_id"],
                    "origin_subsystem": r["origin_subsystem"],
                    "created_at": r["created_at"],
                    "divergence_summary": r["divergence_summary"],
                    "state_hash": r["state_hash"],
                }
                for r in rows
            ]

    def count_stats(self) -> Dict[str, int]:
        with self._connect() as conn:
            branches = conn.execute("SELECT COUNT(*) FROM scp_timelines").fetchone()[0]
            events = conn.execute("SELECT COUNT(*) FROM scp_events").fetchone()[0]
            return {"total_branches": int(branches), "total_events": int(events)}


class BabelInfiniteLibrary:
    """SCP-001: Biblioteca determinista biyectiva sobre el espacio de páginas de 320 símbolos."""

    FEISTEL_ROUNDS = 4

    def __init__(self, ledger: TemporalBranchLedger, secret_domain: str = "SCP001-BABEL-V1"):
        self.ledger = ledger
        self.secret_domain = secret_domain.encode("utf-8")

    @staticmethod
    def normalize_text(text: str) -> str:
        lowered = text.lower()
        normalized_chars: List[str] = []
        for ch in lowered:
            if ch in CHAR_TO_INDEX:
                normalized_chars.append(ch)
            elif ch == "\t":
                normalized_chars.append(" ")
            else:
                normalized_chars.append("?")
            if len(normalized_chars) >= BABEL_PAGE_LEN:
                break
        if len(normalized_chars) < BABEL_PAGE_LEN:
            normalized_chars.extend([" "] * (BABEL_PAGE_LEN - len(normalized_chars)))
        return "".join(normalized_chars)

    @staticmethod
    def _pack_symbols(page_text: str) -> bytes:
        assert len(page_text) == BABEL_PAGE_LEN
        bit_acc = 0
        for ch in page_text:
            bit_acc = (bit_acc << 6) | CHAR_TO_INDEX[ch]
        return bit_acc.to_bytes(BABEL_BLOCK_BYTES, byteorder="big")

    @staticmethod
    def _unpack_symbols(raw_bytes: bytes) -> str:
        assert len(raw_bytes) == BABEL_BLOCK_BYTES
        bit_acc = int.from_bytes(raw_bytes, byteorder="big")
        indices = [0] * BABEL_PAGE_LEN
        mask = 0x3F
        for pos in range(BABEL_PAGE_LEN - 1, -1, -1):
            indices[pos] = bit_acc & mask
            bit_acc >>= 6
        return "".join(BABEL_ALPHABET[i] for i in indices)

    def _round_prf(self, round_idx: int, half_block: bytes) -> bytes:
        h = hashlib.shake_256()
        h.update(self.secret_domain)
        h.update(bytes([round_idx]))
        h.update(half_block)
        return h.digest(BABEL_HALF_BYTES)

    @staticmethod
    def _xor_bytes(a: bytes, b: bytes) -> bytes:
        return bytes(x ^ y for x, y in zip(a, b))

    def _feistel_encrypt(self, block: bytes) -> bytes:
        left = block[:BABEL_HALF_BYTES]
        right = block[BABEL_HALF_BYTES:]
        for r in range(self.FEISTEL_ROUNDS):
            pad = self._round_prf(r, right)
            left, right = right, self._xor_bytes(left, pad)
        return left + right

    def _feistel_decrypt(self, block: bytes) -> bytes:
        left = block[:BABEL_HALF_BYTES]
        right = block[BABEL_HALF_BYTES:]
        for r in range(self.FEISTEL_ROUNDS - 1, -1, -1):
            pad = self._round_prf(r, left)
            left, right = self._xor_bytes(right, pad), left
        return left + right

    @staticmethod
    def _bytes_to_address(coord_bytes: bytes) -> str:
        chamber_hex = coord_bytes[:238].hex()
        shelf_bits = int.from_bytes(coord_bytes[238:240], byteorder="big")
        wall = ((shelf_bits >> 14) & 0x03) + 1       # 1..4
        shelf = ((shelf_bits >> 11) & 0x07) + 1      # 1..8
        volume = ((shelf_bits >> 6) & 0x1F) + 1      # 1..32
        page = (shelf_bits & 0x3F) + 1               # 1..64
        return f"HEX-{chamber_hex}:W{wall}:S{shelf}:V{volume:02d}:P{page:02d}"

    @staticmethod
    def _address_to_bytes(address: str) -> bytes:
        parts = address.strip().split(":")
        if len(parts) != 5 or not parts[0].startswith("HEX-"):
            raise ValueError("Formato de dirección inválido. Esperado HEX-<476hex>:W<1..4>:S<1..8>:V<01..32>:P<01..64>")
        chamber_hex = parts[0][4:]
        if len(chamber_hex) != 476:
            raise ValueError(f"El identificador de hexágono debe tener 476 dígitos hex (recibido={len(chamber_hex)})")
        chamber_bytes = bytes.fromhex(chamber_hex)
        wall = int(parts[1][1:]) - 1
        shelf = int(parts[2][1:]) - 1
        volume = int(parts[3][1:]) - 1
        page = int(parts[4][1:]) - 1
        if not (0 <= wall < 4 and 0 <= shelf < 8 and 0 <= volume < 32 and 0 <= page < 64):
            raise ValueError("Coordenadas de muro/estante/volumen/página fuera de rango.")
        shelf_bits = (wall << 14) | (shelf << 11) | (volume << 6) | page
        return chamber_bytes + shelf_bits.to_bytes(2, byteorder="big")

    def locate_text(self, query_text: str, record_in_ledger: bool = True) -> Dict[str, Any]:
        normalized = self.normalize_text(query_text)
        packed = self._pack_symbols(normalized)
        coord_bytes = self._feistel_encrypt(packed)
        address = self._bytes_to_address(coord_bytes)
        short_id = f"{address[:20]}...{address[-18:]}"
        if record_in_ledger:
            self.ledger.record_event(
                subsystem="SCP-001-BIBLIOTECA",
                event_type="LOCATE_PAGE",
                summary=f"Localización determinista en {short_id}",
                payload={"query_preview": normalized.rstrip()[:120], "short_address": short_id},
            )
        return {
            "scp_id": "SCP-001",
            "address": address,
            "short_address": short_id,
            "normalized_page": normalized,
            "page_length": BABEL_PAGE_LEN,
            "cardinality_bits": BABEL_PAGE_LEN * 6,
        }

    def read_address(self, address: str, record_in_ledger: bool = True) -> Dict[str, Any]:
        coord_bytes = self._address_to_bytes(address)
        unpacked_block = self._feistel_decrypt(coord_bytes)
        page_text = self._unpack_symbols(unpacked_block)
        short_id = f"{address[:20]}...{address[-18:]}"
        if record_in_ledger:
            self.ledger.record_event(
                subsystem="SCP-001-BIBLIOTECA",
                event_type="READ_PAGE",
                summary=f"Lectura de página en {short_id}",
                payload={"short_address": short_id, "preview": page_text.rstrip()[:120]},
            )
        return {
            "scp_id": "SCP-001",
            "address": address,
            "short_address": short_id,
            "page_text": page_text,
            "trimmed_text": page_text.rstrip(),
        }


class BranchingTimeMachine:
    """SCP-002: Navegación de instantáneas históricas con bifurcación DAG inmutable."""

    def __init__(self, ledger: TemporalBranchLedger, chats_db_path: Path = OFFLINE_CHATS_DB):
        self.ledger = ledger
        self.chats_db_path = Path(chats_db_path)

    def _query_historical_context(self, target_iso_or_query: str) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {
            "requested_anchor": target_iso_or_query,
            "matched_records": [],
            "source": "internal_ledger_only",
        }
        if self.chats_db_path.is_file():
            try:
                conn = sqlite3.connect(str(self.chats_db_path))
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT rowid, * FROM offline_chat_turns
                    WHERE CAST(rowid AS TEXT) = ?
                       OR substr(CAST(created_at AS TEXT), 1, 16) LIKE ?
                    ORDER BY rowid DESC LIMIT 3
                    """,
                    (target_iso_or_query.strip(), f"%{target_iso_or_query.strip()[:16]}%"),
                )
                rows = cur.fetchall()
                snapshot["source"] = "offline_chats.db"
                for r in rows:
                    snapshot["matched_records"].append(
                        {
                            "turn_id": r[0],
                            "timestamp": str(r[3]) if len(r) > 3 else "",
                            "prompt_excerpt": str(r[6])[:160] if len(r) > 6 else "",
                        }
                    )
                conn.close()
            except sqlite3.OperationalError:
                # Fallback independiente del esquema exacto de columnas
                try:
                    conn = sqlite3.connect(str(self.chats_db_path))
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT * FROM offline_chat_turns ORDER BY rowid DESC LIMIT 5"
                    )
                    rows = cur.fetchall()
                    snapshot["source"] = "offline_chats.db"
                    q_low = target_iso_or_query.strip().lower()
                    for r in rows:
                        row_text = " | ".join(str(x) for x in r[:7])
                        if not q_low or q_low in row_text.lower() or len(snapshot["matched_records"]) < 2:
                            snapshot["matched_records"].append(
                                {
                                    "turn_id": r[0],
                                    "timestamp": str(r[2]) if len(r) > 2 else "",
                                    "prompt_excerpt": str(r[5])[:160] if len(r) > 5 else "",
                                }
                            )
                    conn.close()
                except Exception:
                    pass
        return snapshot

    def jump_and_branch(
        self,
        target_anchor: str,
        counterfactual_note: str = "Observación histórica sin alteración",
        parent_branch_id: str = TemporalBranchLedger.MAINLINE_ID,
    ) -> Dict[str, Any]:
        historical_snapshot = self._query_historical_context(target_anchor)
        payload = {
            "target_anchor": target_anchor,
            "counterfactual_note": counterfactual_note,
            "historical_snapshot": historical_snapshot,
        }
        branch = self.ledger.fork_branch(
            origin_subsystem="SCP-002-MAQUINA-TIEMPO",
            divergence_summary=f"Salto a '{target_anchor}' -> {counterfactual_note}",
            state_payload=payload,
            parent_branch_id=parent_branch_id,
        )
        return {
            "scp_id": "SCP-002",
            "new_branch_id": branch.branch_id,
            "parent_branch_id": branch.parent_branch_id,
            "created_at": branch.created_at,
            "state_hash": branch.state_hash,
            "historical_snapshot": historical_snapshot,
            "lineage_depth": len(self.ledger.trace_lineage(branch.branch_id)),
        }


class UniverseCodeSimulator:
    """SCP-003: Simulador de universo discreto parametrizado por un código de 24 dígitos."""

    CODE_LENGTH = 24

    def __init__(self, ledger: TemporalBranchLedger):
        self.ledger = ledger

    @classmethod
    def validate_code(cls, code: str) -> str:
        cleaned = code.strip()
        if len(cleaned) != cls.CODE_LENGTH or not cleaned.isdigit():
            raise ValueError(
                f"El código universal debe contener exactamente {cls.CODE_LENGTH} dígitos numéricos (0-9)."
            )
        return cleaned

    @classmethod
    def decode_parameters(cls, code: str) -> Dict[str, Any]:
        code = cls.validate_code(code)
        rule_number = int(code[0:3]) % 256
        coupling = (int(code[3:7]) / 10000.0) * 0.85 + 0.05
        nonlinearity = (int(code[7:11]) / 10000.0) * 3.9 + 0.1
        threshold = (int(code[11:15]) / 10000.0) * 0.75 + 0.12
        damping = (int(code[15:19]) / 10000.0) * 0.35
        seed_phase = int(code[19:24])
        return {
            "ca_rule": rule_number,
            "coupling_constant": round(coupling, 6),
            "nonlinearity_r": round(nonlinearity, 6),
            "activation_threshold": round(threshold, 6),
            "vacuum_damping": round(damping, 6),
            "initial_seed_phase": seed_phase,
        }

    def simulate(self, code: str = DEFAULT_UNIVERSE_CODE, width: int = 64, steps: int = 48) -> Dict[str, Any]:
        params = self.decode_parameters(code)
        rule = params["ca_rule"]
        coupling = params["coupling_constant"]
        r_param = params["nonlinearity_r"]
        threshold = params["activation_threshold"]
        damping = params["vacuum_damping"]
        seed = params["initial_seed_phase"]

        # Estado inicial determinista del campo continuo y discreto
        field = [
            ((math.sin((i + 1) * (seed % 97 + 3) * 0.173) + 1.0) * 0.5)
            for i in range(width)
        ]
        cells = [1 if v >= threshold else 0 for v in field]

        history_cells: List[List[int]] = [cells[:]]
        step_changes: List[float] = []

        for _ in range(steps - 1):
            next_field = [0.0] * width
            next_cells = [0] * width
            changes = 0
            for i in range(width):
                left_idx = (i - 1) % width
                right_idx = (i + 1) % width
                # Regla discreta de 3 vecinos
                pattern = (cells[left_idx] << 2) | (cells[i] << 1) | cells[right_idx]
                ca_bit = (rule >> pattern) & 1

                # Evolución de red de mapas acoplados (CML) + retroalimentación discreta
                local_map = r_param * field[i] * (1.0 - field[i])
                neighbor_avg = 0.5 * (field[left_idx] + field[right_idx])
                val = (1.0 - coupling) * local_map + coupling * neighbor_avg
                val = val * (1.0 - damping) + 0.18 * ca_bit
                val = max(0.0, min(1.0, val))
                next_field[i] = val
                bit = 1 if (val >= threshold) ^ (ca_bit == 1 and val >= threshold * 0.65) else 0
                next_cells[i] = bit
                if bit != cells[i]:
                    changes += 1

            step_changes.append(changes / width)
            field = next_field
            cells = next_cells
            history_cells.append(cells[:])

        flat_bits = bytes(b for row in history_cells for b in row)
        ones_ratio = sum(flat_bits) / len(flat_bits)
        # Entropía binaria de ocupación + bloques de 8 celdas
        if 0.0 < ones_ratio < 1.0:
            bit_entropy = -(
                ones_ratio * math.log2(ones_ratio)
                + (1.0 - ones_ratio) * math.log2(1.0 - ones_ratio)
            )
        else:
            bit_entropy = 0.0

        packed_blocks = bytearray()
        for row in history_cells:
            for j in range(0, width - 7, 8):
                byte_val = 0
                for k in range(8):
                    byte_val = (byte_val << 1) | row[j + k]
                packed_blocks.append(byte_val)
        block_entropy = _shannon_entropy_bytes(bytes(packed_blocks))
        volatility = sum(step_changes) / max(len(step_changes), 1)
        symmetry = sum(
            1
            for row in history_cells
            for i in range(width // 2)
            if row[i] == row[width - 1 - i]
        ) / (len(history_cells) * (width // 2))

        if ones_ratio < 0.03 or ones_ratio > 0.97:
            phase = "vacuum_collapse"
        elif volatility < 0.08 or block_entropy < 1.8:
            phase = "crystalline_order"
        elif 2.2 <= block_entropy <= 5.6 and 0.08 <= volatility <= 0.42:
            phase = "complex_criticality"
        else:
            phase = "chaotic_turbulence"

        preview_rows = [
            "".join("█" if c else "·" for c in row[:48])
            for row in history_cells[:: max(1, len(history_cells) // 8)][:8]
        ]

        return {
            "scp_id": "SCP-003",
            "code": code,
            "parameters": params,
            "metrics": {
                "matter_density": round(ones_ratio, 6),
                "binary_entropy_bits": round(bit_entropy, 6),
                "block_entropy_bits": round(block_entropy, 6),
                "temporal_volatility": round(volatility, 6),
                "spatial_symmetry": round(symmetry, 6),
                "cosmological_phase": phase,
            },
            "spacetime_digest": hashlib.sha256(bytes(packed_blocks)).hexdigest()[:16],
            "spacetime_preview": "\n".join(preview_rows),
            "_raw_packed": bytes(packed_blocks),
        }

    def mutate_single_digit(
        self,
        base_code: str,
        digit_index: int,
        new_digit: str,
        parent_branch_id: str = TemporalBranchLedger.MAINLINE_ID,
    ) -> Dict[str, Any]:
        base_code = self.validate_code(base_code)
        if not (0 <= digit_index < self.CODE_LENGTH):
            raise ValueError(f"digit_index debe estar entre 0 y {self.CODE_LENGTH - 1}")
        if len(new_digit) != 1 or not new_digit.isdigit():
            raise ValueError("new_digit debe ser un único dígito '0'-'9'")
        if base_code[digit_index] == new_digit:
            raise ValueError("new_digit debe ser distinto al dígito original para producir una mutación")

        mutated_code = base_code[:digit_index] + new_digit + base_code[digit_index + 1 :]
        sim_a = self.simulate(base_code)
        sim_b = self.simulate(mutated_code)

        raw_a = sim_a.pop("_raw_packed")
        raw_b = sim_b.pop("_raw_packed")
        diff_bits = sum((a ^ b).bit_count() for a, b in zip(raw_a, raw_b))
        total_bits = len(raw_a) * 8
        hamming_divergence = round(diff_bits / max(total_bits, 1), 6)

        divergence_report = {
            "mutated_position": digit_index,
            "old_digit": base_code[digit_index],
            "new_digit": new_digit,
            "hamming_spacetime_divergence": hamming_divergence,
            "entropy_delta_bits": round(
                sim_b["metrics"]["block_entropy_bits"] - sim_a["metrics"]["block_entropy_bits"],
                6,
            ),
            "density_delta": round(
                sim_b["metrics"]["matter_density"] - sim_a["metrics"]["matter_density"],
                6,
            ),
            "phase_transition": f"{sim_a['metrics']['cosmological_phase']} -> {sim_b['metrics']['cosmological_phase']}",
            "phase_changed": sim_a["metrics"]["cosmological_phase"] != sim_b["metrics"]["cosmological_phase"],
        }

        branch = self.ledger.fork_branch(
            origin_subsystem="SCP-003-CODIGO-UNIVERSO",
            divergence_summary=(
                f"Mutación de 1 dígito en pos[{digit_index}] ({base_code[digit_index]}->{new_digit}): "
                f"divergencia={hamming_divergence:.2%}, transición={divergence_report['phase_transition']}"
            ),
            state_payload={
                "base_code": base_code,
                "mutated_code": mutated_code,
                "divergence": divergence_report,
            },
            parent_branch_id=parent_branch_id,
        )

        return {
            "scp_id": "SCP-003",
            "branch_id": branch.branch_id,
            "base_universe": sim_a,
            "mutated_universe": sim_b,
            "divergence": divergence_report,
        }


class TruthInspectionCamera:
    """SCP-004: Análisis forense determinista de estructura, entropía y firmas mágicas."""

    MAGIC_SIGNATURES: List[Tuple[bytes, str, Tuple[str, ...]]] = [
        (b"\x89PNG\r\n\x1a\n", "image/png", (".png",)),
        (b"\xff\xd8\xff", "image/jpeg", (".jpg", ".jpeg")),
        (b"SQLite format 3\x00", "application/vnd.sqlite3", (".db", ".sqlite", ".sqlite3")),
        (b"%PDF-", "application/pdf", (".pdf",)),
        (b"\x7fELF", "application/x-elf", ("", ".so", ".bin")),
        (b"PK\x03\x04", "application/zip", (".zip", ".jar", ".apk", ".ipa", ".docx")),
    ]

    def __init__(self, ledger: TemporalBranchLedger):
        self.ledger = ledger

    @staticmethod
    def _parse_image_dimensions(data: bytes, mime: str) -> Optional[Dict[str, int]]:
        if mime == "image/png" and len(data) >= 24 and data[12:16] == b"IHDR":
            width, height = struct.unpack(">II", data[16:24])
            return {"width": int(width), "height": int(height)}
        if mime == "image/jpeg" and len(data) > 4:
            idx = 2
            n = len(data)
            while idx + 9 < n:
                if data[idx] != 0xFF:
                    idx += 1
                    continue
                marker = data[idx + 1]
                while marker == 0xFF and idx + 2 < n:
                    idx += 1
                    marker = data[idx + 1]
                if marker in (0xD8, 0xD9):
                    idx += 2
                    continue
                if idx + 4 > n:
                    break
                seg_len = struct.unpack(">H", data[idx + 2 : idx + 4])[0]
                if seg_len < 2 or idx + 2 + seg_len > n:
                    break
                if marker in (0xC0, 0xC1, 0xC2) and idx + 9 <= n:
                    height, width = struct.unpack(">HH", data[idx + 5 : idx + 9])
                    return {"width": int(width), "height": int(height)}
                idx += 2 + seg_len
        return None

    def _detect_mime(self, data: bytes) -> str:
        for magic, mime, _ in self.MAGIC_SIGNATURES:
            if data.startswith(magic):
                return mime
        if len(data) >= 12 and data[4:8] == b"ftyp":
            return "video/mp4"
        try:
            text = data.decode("utf-8")
            stripped = text.strip()
            if stripped and stripped[0] in "{[":
                try:
                    json.loads(stripped)
                    return "application/json"
                except Exception:
                    pass
            if stripped.startswith("<svg") or ("<svg" in stripped[:300]):
                return "image/svg+xml"
            return "text/plain; charset=utf-8"
        except UnicodeDecodeError:
            return "application/octet-stream"

    @staticmethod
    def _classify_entropy(entropy: float) -> str:
        if entropy < 3.2:
            return "structured_repetitive"
        if entropy < 5.6:
            return "natural_language_or_source_code"
        if entropy < 7.4:
            return "packed_binary_or_media"
        return "compressed_or_cryptographic_high_entropy"

    def inspect(
        self,
        target: str | Path | bytes,
        parent_branch_id: str = TemporalBranchLedger.MAINLINE_ID,
    ) -> Dict[str, Any]:
        is_file = False
        file_meta: Dict[str, Any] = {}
        if isinstance(target, bytes):
            raw_bytes = target
            label = f"bytes[{len(raw_bytes)}]"
        else:
            candidate_path = Path(str(target)).expanduser()
            if candidate_path.is_file():
                is_file = True
                raw_bytes = candidate_path.read_bytes()
                stat = candidate_path.stat()
                label = str(candidate_path.resolve())
                file_meta = {
                    "extension": candidate_path.suffix.lower(),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "permissions_octal": oct(stat.st_mode & 0o777),
                }
            else:
                raw_bytes = str(target).encode("utf-8")
                label = f"inline_text[{len(raw_bytes)}B]"

        sha256_hex = hashlib.sha256(raw_bytes).hexdigest()
        blake2b_hex = hashlib.blake2b(raw_bytes, digest_size=16).hexdigest()
        entropy = _shannon_entropy_bytes(raw_bytes)
        detected_mime = self._detect_mime(raw_bytes)
        dimensions = self._parse_image_dimensions(raw_bytes, detected_mime)

        extension_consistent: Optional[bool] = None
        if is_file and file_meta.get("extension"):
            ext = file_meta["extension"]
            for _, mime, valid_exts in self.MAGIC_SIGNATURES:
                if detected_mime == mime:
                    extension_consistent = ext in valid_exts
                    break
            if extension_consistent is None:
                if detected_mime == "application/json":
                    extension_consistent = ext in (".json", ".jsonl")
                elif detected_mime == "image/svg+xml":
                    extension_consistent = ext == ".svg"
                elif detected_mime.startswith("text/"):
                    extension_consistent = ext in (".txt", ".md", ".py", ".sh", ".csv", ".log", ".yaml", ".yml", ".toml")

        report = {
            "target_label": label,
            "is_file": is_file,
            "size_bytes": len(raw_bytes),
            "sha256": sha256_hex,
            "blake2b_128": blake2b_hex,
            "detected_mime": detected_mime,
            "shannon_entropy_bits_per_byte": entropy,
            "entropy_profile": self._classify_entropy(entropy),
            "extension_matches_magic_header": extension_consistent,
            "image_dimensions": dimensions,
            "file_metadata": file_meta,
        }

        branch = self.ledger.fork_branch(
            origin_subsystem="SCP-004-CAMara-VERDAD".upper(),
            divergence_summary=f"Inspección forense de {Path(label).name if is_file else label} ({detected_mime}, {len(raw_bytes)} B)",
            state_payload={"sha256": sha256_hex, "detected_mime": detected_mime, "size_bytes": len(raw_bytes)},
            parent_branch_id=parent_branch_id,
        )

        return {
            "scp_id": "SCP-004",
            "branch_id": branch.branch_id,
            "verification_report": report,
        }


class ProceduralCreationEngine:
    """SCP-005: Síntesis procedural determinista de artefactos/entidades digitales (JSON + SVG)."""

    def __init__(
        self,
        ledger: TemporalBranchLedger,
        output_dir: Path = DEFAULT_CREATIONS_DIR,
    ):
        self.ledger = ledger
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _render_procedural_svg(name: str, category: str, digest: bytes) -> str:
        hue_primary = int.from_bytes(digest[0:2], "big") % 360
        hue_secondary = (hue_primary + 137) % 360
        symmetry_lobes = (digest[2] % 9) + 4
        rings = (digest[3] % 4) + 3
        node_count = (digest[4] % 18) + 12

        cx, cy = 256.0, 256.0
        svg_elements: List[str] = []

        # Anillos orbitales armónicos
        for r_idx in range(1, rings + 1):
            radius = 42 * r_idx
            dash = f"{(digest[5 + r_idx] % 12) + 4},{(digest[9 + r_idx] % 8) + 3}"
            svg_elements.append(
                f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" '
                f'stroke="hsl({hue_secondary}, 80%, 60%)" stroke-opacity="0.45" '
                f'stroke-width="1.4" stroke-dasharray="{dash}" />'
            )

        # Curva roseta paramétrica determinista
        points: List[str] = []
        steps = 180
        amp = 155.0
        for step in range(steps + 1):
            theta = (2.0 * math.pi * step) / steps
            r = amp * (0.58 + 0.42 * math.cos(symmetry_lobes * theta))
            px = cx + r * math.cos(theta)
            py = cy + r * math.sin(theta)
            points.append(f"{px:.2f},{py:.2f}")
        svg_elements.append(
            f'<polyline points="{" ".join(points)}" fill="hsl({hue_primary}, 75%, 52%)" '
            f'fill-opacity="0.18" stroke="hsl({hue_primary}, 90%, 66%)" stroke-width="2.0" />'
        )

        # Nodos en espiral de ángulo áureo
        golden_angle = math.pi * (3.0 - math.sqrt(5.0))
        for n in range(node_count):
            dist = 24.0 * math.sqrt(n + 1)
            ang = n * golden_angle
            nx = cx + dist * math.cos(ang)
            ny = cy + dist * math.sin(ang)
            nr = 2.8 + (digest[(8 + n) % len(digest)] % 5) * 0.9
            svg_elements.append(
                f'<circle cx="{nx:.2f}" cy="{ny:.2f}" r="{nr:.2f}" '
                f'fill="hsl({(hue_primary + n * 11) % 360}, 92%, 72%)" />'
            )

        safe_title = (
            name.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")[:48]
        )
        safe_cat = category.upper().replace("<", "").replace(">", "")[:24]

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">\n'
            '  <rect width="512" height="512" fill="#0b0f19" />\n'
            f'  {"".join(svg_elements)}\n'
            f'  <text x="24" y="472" fill="#e2e8f0" font-family="monospace" font-size="14">{safe_title}</text>\n'
            f'  <text x="24" y="492" fill="#94a3b8" font-family="monospace" font-size="11">'
            f'SCP-005 :: {safe_cat} :: LOBES={symmetry_lobes} :: NODES={node_count}</text>\n'
            "</svg>\n"
        )

    def create(
        self,
        concept_name: str,
        category: str = "artifact",
        attributes: Optional[Dict[str, Any]] = None,
        parent_branch_id: str = TemporalBranchLedger.MAINLINE_ID,
    ) -> Dict[str, Any]:
        clean_name = concept_name.strip() or "Artefacto Sin Nombre"
        attrs = attributes or {}
        canonical_seed = json.dumps(
            {"name": clean_name, "category": category, "attributes": attrs},
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(canonical_seed.encode("utf-8")).digest()
        creation_id = f"scp005_{digest.hex()[:12]}"

        blueprint = {
            "creation_id": creation_id,
            "name": clean_name,
            "category": category,
            "created_at": _utc_iso(),
            "deterministic_seed_sha256": digest.hex(),
            "structural_parameters": {
                "symmetry_order": int((digest[2] % 9) + 4),
                "orbital_layers": int((digest[3] % 4) + 3),
                "active_nodes": int((digest[4] % 18) + 12),
                "stability_index": round(0.55 + (digest[6] / 255.0) * 0.44, 4),
                "harmonic_frequency_hz": round(110.0 + (int.from_bytes(digest[10:12], "big") % 770), 2),
            },
            "custom_attributes": attrs,
        }

        svg_content = self._render_procedural_svg(clean_name, category, digest)
        json_path = self.output_dir / f"{creation_id}.json"
        svg_path = self.output_dir / f"{creation_id}.svg"

        branch = self.ledger.fork_branch(
            origin_subsystem="SCP-005-MAQUINA-CREACION",
            divergence_summary=f"Síntesis digital '{clean_name}' ({category}) -> {creation_id}",
            state_payload={
                "creation_id": creation_id,
                "name": clean_name,
                "category": category,
                "json_path": str(json_path),
                "svg_path": str(svg_path),
            },
            parent_branch_id=parent_branch_id,
        )

        blueprint["timeline_branch_id"] = branch.branch_id
        json_path.write_text(json.dumps(blueprint, indent=2, ensure_ascii=False), encoding="utf-8")
        svg_path.write_text(svg_content, encoding="utf-8")

        return {
            "scp_id": "SCP-005",
            "creation_id": creation_id,
            "branch_id": branch.branch_id,
            "blueprint": blueprint,
            "files": {
                "json_blueprint": str(json_path),
                "svg_geometry": str(svg_path),
            },
        }


class SCPConceptualSuite:
    """Fachada unificada de los 5 subsistemas computacionales SCP."""

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        creations_dir: Path = DEFAULT_CREATIONS_DIR,
    ):
        self.ledger = TemporalBranchLedger(db_path=db_path)
        self.library = BabelInfiniteLibrary(self.ledger)
        self.time_machine = BranchingTimeMachine(self.ledger)
        self.universe = UniverseCodeSimulator(self.ledger)
        self.truth_camera = TruthInspectionCamera(self.ledger)
        self.creator = ProceduralCreationEngine(self.ledger, output_dir=creations_dir)

    @staticmethod
    def capability_mapping() -> List[Dict[str, str]]:
        return [
            {
                "scp_concept": "SCP-001 – La Biblioteca del Fin del Mundo",
                "fictional_claim": "Biblioteca infinita con todos los libros posibles y acceso al pasado/futuro.",
                "real_software_implementation": (
                    "Biyección reversible Feistel de 4 rondas sobre páginas de 320 caracteres (1920 bits): "
                    "localiza y reconstruye cualquier texto posible en O(L) sin almacenamiento infinito."
                ),
                "physical_constraint": "No predice el futuro real ni altera eventos físicos.",
            },
            {
                "scp_concept": "SCP-002 – La Máquina del Tiempo",
                "fictional_claim": "Viaje temporal que crea una realidad paralela en cada uso.",
                "real_software_implementation": (
                    "Navegador de instantáneas históricas en SQLite donde cada consulta o escenario "
                    "contrafactual bifurca una rama hija inmutable en un DAG con linaje verificable."
                ),
                "physical_constraint": "Opera sobre estados e historiales digitales, no sobre el tiempo físico.",
            },
            {
                "scp_concept": "SCP-003 – El Código del Universo",
                "fictional_claim": "Código matemático donde alterar un dígito cambia la estructura del universo.",
                "real_software_implementation": (
                    "Simulador híbrido de autómata celular y red de mapas acoplados parametrizado por 24 dígitos, "
                    "con análisis cuantitativo de mutación de 1 dígito (entropía, densidad y fase)."
                ),
                "physical_constraint": "Modela universos discretos simulados, no constantes físicas reales.",
            },
            {
                "scp_concept": "SCP-004 – La Cámara de la Verdad",
                "fictional_claim": "Cámara que revela la verdad absoluta de cualquier objeto y ramifica la realidad.",
                "real_software_implementation": (
                    "Inspector forense determinista de bytes/archivos/imágenes (SHA-256, BLAKE2b, entropía de Shannon, "
                    "cabeceras mágicas vs. extensión y dimensiones PNG/JPEG) con registro en rama temporal."
                ),
                "physical_constraint": "Verifica propiedades criptográficas y estructurales de datos digitales.",
            },
            {
                "scp_concept": "SCP-005 – La Máquina de la Creación",
                "fictional_claim": "Máquina que materializa cualquier objeto o ser deseado creando una rama paralela.",
                "real_software_implementation": (
                    "Motor procedural determinista que sintetiza planos JSON estructurados y geometría vectorial SVG "
                    "de artefactos o entidades digitales, registrando su propia rama en el DAG temporal."
                ),
                "physical_constraint": "Genera artefactos digitales y simulaciones, no materia física.",
            },
        ]

    def get_status(self) -> Dict[str, Any]:
        stats = self.ledger.count_stats()
        creations = sorted(self.creator.output_dir.glob("*.json"))
        return {
            "db_path": str(self.ledger.db_path),
            "creations_dir": str(self.creator.output_dir),
            "total_branches": stats["total_branches"],
            "total_events": stats["total_events"],
            "generated_creations_count": len(creations),
            "recent_branches": self.ledger.list_branches(limit=6),
        }

    def run_full_demonstration(self) -> Dict[str, Any]:
        # 1. Biblioteca biyectiva
        sample_quote = "explorar las estructuras matematicas del espacio de estados posibles."
        loc = self.library.locate_text(sample_quote)
        recovered = self.library.read_address(loc["address"])

        # 2. Máquina del tiempo (consulta turno #2286 donde se definieron los SCP)
        jump = self.time_machine.jump_and_branch(
            target_anchor="2286",
            counterfactual_note="Materialización algorítmica de los 5 conceptos SCP en módulos de software",
        )

        # 3. Código del universo + mutación de 1 solo dígito
        mutation = self.universe.mutate_single_digit(
            base_code=DEFAULT_UNIVERSE_CODE,
            digit_index=2,
            new_digit="9",
            parent_branch_id=jump["new_branch_id"],
        )

        # 4. Síntesis de artefacto digital (SCP-005) encadenada a la rama anterior
        creation = self.creator.create(
            concept_name="Astrolabio de Fase Cuántica",
            category="construct",
            attributes={"purpose": "Visualización armónica de estados discretos", "tier": "alpha"},
            parent_branch_id=mutation["branch_id"],
        )

        # 5. Cámara de la verdad inspeccionando el SVG recién creado (y captura C310 si existe)
        svg_inspection = self.truth_camera.inspect(
            creation["files"]["svg_geometry"],
            parent_branch_id=creation["branch_id"],
        )

        return {
            "scp_001_library": {
                "short_address": loc["short_address"],
                "exact_roundtrip_verified": recovered["trimmed_text"] == sample_quote,
                "recovered_text": recovered["trimmed_text"],
            },
            "scp_002_time_machine": jump,
            "scp_003_universe_code": {
                "branch_id": mutation["branch_id"],
                "divergence": mutation["divergence"],
                "base_phase": mutation["base_universe"]["metrics"]["cosmological_phase"],
                "mutated_phase": mutation["mutated_universe"]["metrics"]["cosmological_phase"],
            },
            "scp_004_truth_camera": svg_inspection,
            "scp_005_creation_engine": creation,
            "lineage_chain": self.ledger.trace_lineage(svg_inspection["branch_id"]),
        }


_SUITE_SINGLETON: Optional[SCPConceptualSuite] = None


def get_scp_suite() -> SCPConceptualSuite:
    global _SUITE_SINGLETON
    if _SUITE_SINGLETON is None:
        _SUITE_SINGLETON = SCPConceptualSuite()
    return _SUITE_SINGLETON


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Suite Computacional de Objetos Conceptuales SCP")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Muestra el estado del DAG temporal y artefactos generados")
    sub.add_parser("demo", help="Ejecuta una demostración encadenada de los 5 subsistemas SCP")
    sub.add_parser("mapping", help="Muestra el análisis comparativo ficción vs. implementación real")

    p_lib = sub.add_parser("locate", help="Localiza un texto en la Biblioteca Biyectiva (SCP-001)")
    p_lib.add_argument("text", help="Texto de hasta 320 caracteres")

    p_read = sub.add_parser("read", help="Lee una dirección exacta de la Biblioteca Biyectiva (SCP-001)")
    p_read.add_argument("address", help="Dirección completa HEX-...:W...:S...:V...:P...")

    p_jump = sub.add_parser("jump", help="Salta a un ancla histórica y bifurca una rama (SCP-002)")
    p_jump.add_argument("anchor", help="ID de turno o prefijo de fecha ISO")
    p_jump.add_argument("--note", default="Exploración contrafactual", help="Nota de bifurcación")

    p_univ = sub.add_parser("mutate", help="Muta un dígito del Código del Universo de 24 dígitos (SCP-003)")
    p_univ.add_argument("--code", default=DEFAULT_UNIVERSE_CODE, help="Código de 24 dígitos")
    p_univ.add_argument("--pos", type=int, default=2, help="Índice del dígito a mutar (0-23)")
    p_univ.add_argument("--digit", default="9", help="Nuevo dígito (0-9)")

    p_cam = sub.add_parser("inspect", help="Inspecciona un archivo o cadena con la Cámara de la Verdad (SCP-004)")
    p_cam.add_argument("target", help="Ruta de archivo o texto")

    p_cre = sub.add_parser("create", help="Sintetiza un artefacto JSON+SVG en una nueva rama (SCP-005)")
    p_cre.add_argument("name", help="Nombre del artefacto o entidad digital")
    p_cre.add_argument("--category", default="artifact", help="Categoría (artifact, entity, construct)")

    args = parser.parse_args(argv)
    suite = get_scp_suite()

    if args.cmd in (None, "status"):
        print(json.dumps(suite.get_status(), indent=2, ensure_ascii=False))
    elif args.cmd == "mapping":
        print(json.dumps(suite.capability_mapping(), indent=2, ensure_ascii=False))
    elif args.cmd == "demo":
        print(json.dumps(suite.run_full_demonstration(), indent=2, ensure_ascii=False))
    elif args.cmd == "locate":
        print(json.dumps(suite.library.locate_text(args.text), indent=2, ensure_ascii=False))
    elif args.cmd == "read":
        print(json.dumps(suite.library.read_address(args.address), indent=2, ensure_ascii=False))
    elif args.cmd == "jump":
        print(json.dumps(suite.time_machine.jump_and_branch(args.anchor, args.note), indent=2, ensure_ascii=False))
    elif args.cmd == "mutate":
        print(
            json.dumps(
                suite.universe.mutate_single_digit(args.code, args.pos, args.digit),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.cmd == "inspect":
        print(json.dumps(suite.truth_camera.inspect(args.target), indent=2, ensure_ascii=False))
    elif args.cmd == "create":
        print(json.dumps(suite.creator.create(args.name, args.category), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
