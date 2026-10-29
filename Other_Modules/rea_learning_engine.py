"""
modulos_ftl/rea_learning_engine.py — Motor de Aprendizaje REA de TARDIS
=======================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

OBJETIVO SOBERANO
-----------------
TARDIS debe aprender *cómo funciona la IA de otros modelos* para aplicarlo a sí
misma. Este motor realiza ingeniería inversa **estática y no destructiva** de los
artefactos de modelos presentes en el dispositivo (GGUF, safetensors, ONNX,
configuraciones Transformers, bundles y binarios), extrae conocimiento
arquitectónico accionable y lo convierte en:

  1. Una base de conocimiento append-only (``data/rea/knowledge_base.jsonl``).
  2. Un informe de aprendizaje agregado (``data/rea/learning_report.json``).
  3. Propuestas de auto-adaptación con evidencia, riesgo y rollback
     (``data/rea/proposals.json``).
  4. Un perfil de adaptación consumible por TARDIS/FTL/Easy Touch
     (``data/rea/adaptation_profile.json``).

GARANTÍAS DE SEGURIDAD (FAIL-CLOSED)
------------------------------------
* **Nunca ejecuta** el artefacto inspeccionado: sólo lee bytes y metadatos.
* **Nunca escribe** fuera de ``data/rea`` salvo que se aplique explícitamente una
  propuesta de configuración con ``--apply-medium`` (con backup + escritura atómica).
* **Nunca descarga** modelos: el descubrimiento es local. La investigación de
  tecnologías nuevas vive en ``savage_update.py`` y sólo produce propuestas.
* Parseadores con límites duros de tamaño/profundidad para evitar bombas de
  descompresión o bucles de punteros.
* Toda acción queda auditada en ``data/rea/audit.jsonl``.

USO
---
    python3 -m modulos_ftl.rea_learning_engine scan
    python3 -m modulos_ftl.rea_learning_engine scan /ruta/modelo.gguf --no-rea
    python3 -m modulos_ftl.rea_learning_engine report
    python3 -m modulos_ftl.rea_learning_engine propose
    python3 -m modulos_ftl.rea_learning_engine apply --all-low
    python3 -m modulos_ftl.rea_learning_engine apply --ids rea-abc123 --apply-medium
    python3 -m modulos_ftl.rea_learning_engine status
    python3 -m modulos_ftl.rea_learning_engine kb --limit 20
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Rutas canónicas
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TARDIS_REA_DATA", BASE_DIR / "data" / "rea"))
KB_PATH = DATA_DIR / "knowledge_base.jsonl"
REPORT_PATH = DATA_DIR / "learning_report.json"
PROPOSALS_PATH = DATA_DIR / "proposals.json"
PROFILE_PATH = DATA_DIR / "adaptation_profile.json"
AUDIT_PATH = DATA_DIR / "audit.jsonl"
EXPERIMENTS_DIR = DATA_DIR / "experiments"
STATE_PATH = DATA_DIR / "engine_state.json"

REA_BIN = os.environ.get("REA_BIN", "/usr/local/bin/rea")

# Límites duros de seguridad
MAX_FILE_BYTES = 64 * 1024 * 1024 * 1024          # 64 GiB (sólo stat, no lectura completa)
MAX_HEADER_BYTES = 64 * 1024 * 1024               # 64 MiB de cabecera
MAX_KV_ITEMS = 100_000
MAX_ARRAY_ITEMS = 5_000_000
MAX_ARRAY_CAPTURE = 64
MAX_STRING_CHARS = 512
MAX_TENSORS = 200_000
MAX_SCAN_FILES = 20_000
MAX_SCAN_DEPTH = 8
REA_TIMEOUT_S = 90
REA_MAX_OUTPUT = 512 * 1024

MODEL_EXTENSIONS = {
    ".gguf", ".ggml", ".safetensors", ".onnx", ".pt", ".pth", ".bin",
    ".h5", ".tflite", ".mlmodel", ".mlpackage", ".ckpt", ".msgpack",
}
CONFIG_NAMES = {"config.json", "params.json", "model_index.json", "adapter_config.json"}

# Tipos de tensor GGML/GGUF
GGML_TYPES: Dict[int, str] = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 4: "Q4_2", 5: "Q4_3",
    6: "Q5_0", 7: "Q5_1", 8: "Q8_0", 9: "Q8_1", 10: "Q2_K", 11: "Q3_K",
    12: "Q4_K", 13: "Q5_K", 14: "Q6_K", 15: "Q8_K", 16: "IQ2_XXS",
    17: "IQ2_XS", 18: "IQ3_XXS", 19: "IQ1_S", 20: "IQ4_NL", 21: "IQ3_S",
    22: "IQ2_S", 23: "IQ4_XS", 24: "I8", 25: "I16", 26: "I32", 27: "I64",
    28: "F64", 29: "IQ1_M", 30: "BF16", 31: "Q4_0_4_4", 32: "Q4_0_4_8",
    33: "Q4_0_8_8", 34: "TQ1_0", 35: "TQ2_0", 36: "IQ4_NL_4_4",
}

# Tipos de valor GGUF
GGUF_UINT8, GGUF_INT8, GGUF_UINT16, GGUF_INT16 = 0, 1, 2, 3
GGUF_UINT32, GGUF_INT32, GGUF_FLOAT32, GGUF_BOOL = 4, 5, 6, 7
GGUF_STRING, GGUF_ARRAY, GGUF_UINT64, GGUF_INT64, GGUF_FLOAT64 = 8, 9, 10, 11, 12

# Tipos ONNX TensorProto
ONNX_DTYPES: Dict[int, str] = {
    0: "UNDEFINED", 1: "FLOAT", 2: "UINT8", 3: "INT8", 4: "UINT16",
    5: "INT16", 6: "INT32", 7: "INT64", 8: "STRING", 9: "BOOL",
    10: "FLOAT16", 11: "DOUBLE", 12: "UINT32", 13: "UINT64",
    14: "COMPLEX64", 15: "COMPLEX128", 16: "BFLOAT16",
}

# Familias arquitectónicas conocidas -> rasgos de diseño
ARCHITECTURE_TRAITS: Dict[str, Dict[str, Any]] = {
    "llama": {"family": "decoder-only transformer", "norm": "RMSNorm", "activation": "SwiGLU", "pos": "RoPE"},
    "mistral": {"family": "decoder-only transformer", "norm": "RMSNorm", "activation": "SwiGLU", "pos": "RoPE + sliding window"},
    "mixtral": {"family": "sparse MoE transformer", "norm": "RMSNorm", "activation": "SwiGLU", "pos": "RoPE"},
    "qwen2": {"family": "decoder-only transformer", "norm": "RMSNorm", "activation": "SwiGLU", "pos": "RoPE", "bias": "qkv"},
    "qwen3": {"family": "decoder-only transformer", "norm": "RMSNorm", "activation": "SwiGLU", "pos": "RoPE"},
    "gemma": {"family": "decoder-only transformer", "norm": "RMSNorm", "activation": "GeGLU", "pos": "RoPE"},
    "gemma2": {"family": "decoder-only transformer", "norm": "RMSNorm", "activation": "GeGLU", "pos": "RoPE + sliding window"},
    "phi3": {"family": "decoder-only transformer", "norm": "RMSNorm", "activation": "SwiGLU", "pos": "RoPE"},
    "deepseek2": {"family": "MoE transformer + MLA", "norm": "RMSNorm", "activation": "SwiGLU", "pos": "RoPE", "attention": "Multi-head Latent Attention"},
    "deepseek3": {"family": "MoE transformer + MLA", "norm": "RMSNorm", "activation": "SwiGLU", "pos": "RoPE", "attention": "MLA"},
    "gpt2": {"family": "decoder-only transformer", "norm": "LayerNorm", "activation": "GELU", "pos": "learned absolute"},
    "falcon": {"family": "decoder-only transformer", "norm": "LayerNorm", "activation": "GELU", "pos": "RoPE / ALiBi"},
    "mpt": {"family": "decoder-only transformer", "norm": "LayerNorm", "activation": "GELU", "pos": "ALiBi"},
    "bloom": {"family": "decoder-only transformer", "norm": "LayerNorm", "activation": "GELU", "pos": "ALiBi"},
    "bert": {"family": "encoder-only transformer", "norm": "LayerNorm", "activation": "GELU", "pos": "learned absolute"},
    "t5": {"family": "encoder-decoder transformer", "norm": "RMSNorm", "activation": "ReLU", "pos": "relative bias"},
    "whisper": {"family": "encoder-decoder transformer (audio)", "norm": "LayerNorm", "activation": "GELU", "pos": "sinusoidal"},
    "clip": {"family": "dual encoder (visión-texto)", "norm": "LayerNorm", "activation": "GELU", "pos": "learned absolute"},
    "vit": {"family": "vision transformer", "norm": "LayerNorm", "activation": "GELU", "pos": "learned absolute"},
}

REPORT_SCHEMA = "tardis.rea.learning/1.0"
PROPOSAL_SCHEMA = "tardis.rea.proposals/1.0"
PROFILE_SCHEMA = "tardis.rea.adaptation_profile/1.0"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, payload: Any, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=False)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _human_bytes(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(max(0, n))
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{n} B"


def _human_params(n: int) -> str:
    if n <= 0:
        return "0"
    if n >= 1_000_000_000_000:
        return f"{n / 1_000_000_000_000:.2f} T"
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f} B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f} M"
    if n >= 1_000:
        return f"{n / 1_000:.2f} K"
    return str(n)


def _quick_fingerprint(path: Path, head_bytes: int = 262_144) -> str:
    """Hash rápido y estable: tamaño + primeros 256 KiB + nombre."""
    h = hashlib.sha256()
    h.update(str(path.name).encode("utf-8", "replace"))
    try:
        st = path.stat()
        h.update(struct.pack("<Q", st.st_size))
        with open(path, "rb") as fh:
            h.update(fh.read(head_bytes))
    except OSError:
        h.update(b"unreadable")
    return h.hexdigest()


def _truncate(value: Any, limit: int = MAX_STRING_CHARS) -> Any:
    if isinstance(value, str):
        return value[:limit]
    return value


# ---------------------------------------------------------------------------
# Sniffing de formato real (integridad antes de parsear)
# ---------------------------------------------------------------------------
def sniff_format(path: Path) -> Dict[str, Any]:
    """Detecta el formato real por magic bytes. Evita parsear HTML disfrazado."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError as exc:
        return {"format": "unreadable", "error": str(exc), "size_bytes": 0}

    if size == 0:
        return {"format": "empty", "error": "archivo vacío (0 bytes)", "size_bytes": 0}
    if head.startswith(b"GGUF"):
        return {"format": "gguf", "size_bytes": size}
    # safetensors: uint64 LE header_len seguido de '{'
    if len(head) >= 9 and head[8:9] == b"{":
        header_len = struct.unpack("<Q", head[:8])[0]
        if 0 < header_len <= MAX_HEADER_BYTES:
            return {"format": "safetensors", "size_bytes": size}
    if head.startswith(b"\x7fELF"):
        return {"format": "elf", "size_bytes": size}
    if head.startswith(b"PK\x03\x04"):
        return {"format": "zip", "size_bytes": size}
    if head[:4] in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe"):
        return {"format": "macho", "size_bytes": size}
    stripped = head.lstrip()[:512].lower()
    if stripped.startswith(b"<!doctype html") or stripped.startswith(b"<html") or b"<head" in stripped:
        return {"format": "html", "error": "el archivo es una página HTML, no un artefacto de modelo", "size_bytes": size}
    if stripped.startswith(b"version https://git-lfs"):
        return {"format": "lfs_pointer", "error": "puntero Git LFS, no el contenido real", "size_bytes": size}
    # ONNX ModelProto comienza con field 1 (ir_version) wire 0 => 0x08.
    if head.startswith(b"\x08"):
        return {"format": "protobuf", "size_bytes": size}
    if stripped.startswith(b"{") or stripped.startswith(b"["):
        return {"format": "json", "size_bytes": size}
    return {"format": "unknown", "size_bytes": size}


# ---------------------------------------------------------------------------
# Parser GGUF (v2 / v3)
# ---------------------------------------------------------------------------
class _Reader:
    """Lector binario acotado con contador de bytes."""

    __slots__ = ("fh", "pos", "limit")

    def __init__(self, fh, limit: int = MAX_HEADER_BYTES):
        self.fh = fh
        self.pos = 0
        self.limit = limit

    def _need(self, n: int) -> None:
        if n < 0 or self.pos + n > self.limit:
            raise ValueError(f"lectura fuera de límite ({self.pos}+{n}>{self.limit})")

    def read(self, n: int) -> bytes:
        self._need(n)
        data = self.fh.read(n)
        if len(data) != n:
            raise EOFError(f"EOF inesperado: {len(data)}/{n}")
        self.pos += n
        return data

    def u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.read(8))[0]

    def i64(self) -> int:
        return struct.unpack("<q", self.read(8))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self.read(4))[0]

    def f64(self) -> float:
        return struct.unpack("<d", self.read(8))[0]

    def string(self, max_chars: int = MAX_STRING_CHARS) -> str:
        n = self.u64()
        if n > 16 * 1024 * 1024:
            raise ValueError(f"string GGUF demasiado grande: {n}")
        raw = self.read(n)
        return raw.decode("utf-8", "replace")[:max_chars]


def _gguf_value(reader: _Reader, vtype: int, depth: int = 0) -> Any:
    if depth > 4:
        return "<max-depth>"
    if vtype == GGUF_UINT8:
        return reader.read(1)[0]
    if vtype == GGUF_INT8:
        return struct.unpack("<b", reader.read(1))[0]
    if vtype == GGUF_UINT16:
        return struct.unpack("<H", reader.read(2))[0]
    if vtype == GGUF_INT16:
        return struct.unpack("<h", reader.read(2))[0]
    if vtype == GGUF_UINT32:
        return reader.u32()
    if vtype == GGUF_INT32:
        return reader.i32()
    if vtype == GGUF_FLOAT32:
        return round(reader.f32(), 6)
    if vtype == GGUF_BOOL:
        return bool(reader.read(1)[0])
    if vtype == GGUF_STRING:
        return reader.string()
    if vtype == GGUF_UINT64:
        return reader.u64()
    if vtype == GGUF_INT64:
        return reader.i64()
    if vtype == GGUF_FLOAT64:
        return reader.f64()
    if vtype == GGUF_ARRAY:
        itype = reader.u32()
        count = reader.u64()
        if count > MAX_ARRAY_ITEMS:
            raise ValueError(f"array GGUF demasiado grande: {count}")
        values: List[Any] = []
        for index in range(count):
            item = _gguf_value(reader, itype, depth + 1)
            if index < MAX_ARRAY_CAPTURE:
                values.append(item)
        return values
    raise ValueError(f"tipo GGUF desconocido: {vtype}")


def parse_gguf(path: Path) -> Dict[str, Any]:
    """Extrae arquitectura, hiperparámetros, tokenizer y mezcla de cuantización."""
    st = path.stat()
    result: Dict[str, Any] = {
        "format": "gguf",
        "size_bytes": st.st_size,
        "size_human": _human_bytes(st.st_size),
        "warnings": [],
    }
    with open(path, "rb") as fh:
        magic = fh.read(4)
        if magic != b"GGUF":
            raise ValueError("firma GGUF inválida")
        reader = _Reader(fh)
        reader.pos = 4
        version = reader.u32()
        tensor_count = reader.u64()
        kv_count = reader.u64()
        if tensor_count > MAX_TENSORS or kv_count > MAX_KV_ITEMS:
            raise ValueError(f"cabecera GGUF fuera de límites: tensores={tensor_count} kv={kv_count}")
        result.update({"version": version, "tensor_count": tensor_count, "kv_count": kv_count})

        metadata: Dict[str, Any] = {}
        for _ in range(kv_count):
            key = reader.string(256)
            vtype = reader.u32()
            try:
                metadata[key] = _gguf_value(reader, vtype)
            except Exception as exc:  # noqa: BLE001
                result["warnings"].append(f"metadata '{key}' ilegible: {exc}")
                break

        # Información de tensores (nombres, dims, tipo)
        tensors: List[Dict[str, Any]] = []
        type_hist: Dict[str, int] = {}
        total_params = 0
        for _ in range(min(tensor_count, MAX_TENSORS)):
            try:
                name = reader.string(256)
                n_dims = reader.u32()
                if n_dims > 8:
                    raise ValueError(f"tensor '{name}' con {n_dims} dims")
                dims = [reader.u64() for _ in range(n_dims)]
                ttype = reader.u32()
                _offset = reader.u64()
            except Exception as exc:  # noqa: BLE001
                result["warnings"].append(f"tensor ilegible tras {len(tensors)}: {exc}")
                break
            tname = GGML_TYPES.get(ttype, f"TYPE_{ttype}")
            type_hist[tname] = type_hist.get(tname, 0) + 1
            count = 1
            for d in dims:
                count *= max(1, d)
            total_params += count
            if len(tensors) < 4096:
                tensors.append({"name": name[:160], "shape": dims, "type": tname})

    arch = str(metadata.get("general.architecture", "") or "unknown").lower()
    # Normalizar nombres tipo "qwen2" / "llama"
    arch_key = arch.split(".")[0]
    traits = ARCHITECTURE_TRAITS.get(arch_key, {})
    n_layers = _safe_int(metadata.get(f"{arch}.block_count"))
    n_heads = _safe_int(metadata.get(f"{arch}.attention.head_count"))
    n_kv_heads = _safe_int(metadata.get(f"{arch}.attention.head_count_kv"))
    ctx = _safe_int(metadata.get(f"{arch}.context_length"))
    embd = _safe_int(metadata.get(f"{arch}.embedding_length"))
    ffn = _safe_int(metadata.get(f"{arch}.feed_forward_length"))
    vocab = _safe_int(metadata.get(f"{arch}.vocab_size")) or _safe_int(metadata.get("tokenizer.ggml.tokens") and len(metadata.get("tokenizer.ggml.tokens") or []))
    experts = _safe_int(metadata.get(f"{arch}.expert_count"))
    experts_used = _safe_int(metadata.get(f"{arch}.expert_used_count"))
    rope_base = metadata.get(f"{arch}.rope.freq_base")
    sliding = metadata.get(f"{arch}.attention.sliding_window")

    # Estimar parámetros si el header no los declara
    estimated = total_params
    if estimated <= 0 and n_layers and embd:
        # Aproximación decoder-only: attn + ffn + embeddings
        ffn = ffn or int(embd * 8 / 3)
        per_layer = 4 * embd * embd + 2 * embd * ffn
        estimated = n_layers * per_layer + 2 * max(vocab, 1) * embd

    result.update({
        "architecture": arch_key,
        "architecture_raw": arch,
        "traits": traits,
        "layers": n_layers,
        "heads": n_heads,
        "kv_heads": n_kv_heads,
        "gqa_ratio": round(n_heads / n_kv_heads, 3) if n_heads and n_kv_heads else None,
        "context_length": ctx,
        "embedding_length": embd,
        "feed_forward_length": ffn,
        "vocab_size": vocab,
        "experts": experts,
        "experts_used": experts_used,
        "rope_freq_base": rope_base,
        "sliding_window": sliding,
        "parameter_count": estimated,
        "parameter_count_human": _human_params(estimated),
        "quantization_mix": type_hist,
        "primary_quantization": max(type_hist, key=type_hist.get) if type_hist else None,
        "tokenizer_model": metadata.get("tokenizer.ggml.model"),
        "metadata": {k: _truncate(v) for k, v in metadata.items() if not isinstance(v, list) or len(v) <= 32},
        "tensors_sample": tensors,
        "tensor_count_read": len(tensors),
    })
    return result


# ---------------------------------------------------------------------------
# Parser safetensors
# ---------------------------------------------------------------------------
def parse_safetensors(path: Path) -> Dict[str, Any]:
    st = path.stat()
    with open(path, "rb") as fh:
        raw_len = fh.read(8)
        if len(raw_len) != 8:
            raise ValueError("cabecera safetensors truncada")
        header_len = struct.unpack("<Q", raw_len)[0]
        if header_len <= 0 or header_len > MAX_HEADER_BYTES:
            raise ValueError(f"header safetensors inválido: {header_len}")
        header = json.loads(fh.read(header_len).decode("utf-8"))

    dtype_hist: Dict[str, int] = {}
    total_params = 0
    tensors: List[Dict[str, Any]] = []
    layers: set[int] = set()
    for name, info in header.items():
        if name == "__metadata__":
            continue
        if not isinstance(info, dict):
            continue
        dtype = str(info.get("dtype", "unknown"))
        shape = info.get("shape") or []
        count = 1
        for d in shape:
            count *= max(1, _safe_int(d, 1))
        total_params += count
        dtype_hist[dtype] = dtype_hist.get(dtype, 0) + 1
        m = re.search(r"(?:layers|h|block)\.(\d+)\.", name)
        if m:
            layers.add(int(m.group(1)))
        if len(tensors) < 4096:
            tensors.append({"name": name[:160], "shape": shape[:8], "dtype": dtype})

    return {
        "format": "safetensors",
        "size_bytes": st.st_size,
        "size_human": _human_bytes(st.st_size),
        "tensor_count": len([k for k in header if k != "__metadata__"]),
        "parameter_count": total_params,
        "parameter_count_human": _human_params(total_params),
        "dtype_mix": dtype_hist,
        "primary_dtype": max(dtype_hist, key=dtype_hist.get) if dtype_hist else None,
        "detected_layers": len(layers),
        "tensors_sample": tensors,
        "metadata": header.get("__metadata__", {}) if isinstance(header.get("__metadata__"), dict) else {},
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Parser ONNX (protobuf mínimo, sin dependencias)
# ---------------------------------------------------------------------------
def _pb_varint(data: bytes, pos: int) -> Tuple[int, int]:
    shift = 0
    value = 0
    while True:
        if pos >= len(data):
            raise ValueError("varint truncado")
        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            return value, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint demasiado largo")


def _pb_fields(data: bytes) -> Iterator[Tuple[int, int, Any]]:
    pos = 0
    n = len(data)
    while pos < n:
        key, pos = _pb_varint(data, pos)
        field_no, wire = key >> 3, key & 0x07
        if field_no == 0:
            raise ValueError("campo protobuf 0")
        if wire == 0:
            value, pos = _pb_varint(data, pos)
        elif wire == 1:
            if pos + 8 > n:
                raise ValueError("fixed64 truncado")
            value = data[pos:pos + 8]
            pos += 8
        elif wire == 2:
            length, pos = _pb_varint(data, pos)
            if length < 0 or pos + length > n:
                raise ValueError("bytes protobuf truncados")
            value = data[pos:pos + length]
            pos += length
        elif wire == 5:
            if pos + 4 > n:
                raise ValueError("fixed32 truncado")
            value = data[pos:pos + 4]
            pos += 4
        else:
            raise ValueError(f"wire type no soportado: {wire}")
        yield field_no, wire, value


def parse_onnx(path: Path) -> Dict[str, Any]:
    st = path.stat()
    if st.st_size > MAX_FILE_BYTES:
        raise ValueError("ONNX excede el límite de tamaño")
    with open(path, "rb") as fh:
        data = fh.read(min(st.st_size, 512 * 1024 * 1024))

    ir_version = None
    producer = None
    producer_version = None
    graph_data: Optional[bytes] = None
    for field_no, wire, value in _pb_fields(data):
        if field_no == 1 and wire == 0:
            ir_version = value
        elif field_no == 2 and wire == 2:
            producer = bytes(value).decode("utf-8", "replace")[:120]
        elif field_no == 3 and wire == 2:
            producer_version = bytes(value).decode("utf-8", "replace")[:120]
        elif field_no == 7 and wire == 2:
            graph_data = bytes(value)
            break

    nodes = 0
    initializers = 0
    total_params = 0
    dtype_hist: Dict[str, int] = {}
    op_hist: Dict[str, int] = {}
    graph_name = None
    if graph_data:
        for field_no, wire, value in _pb_fields(graph_data):
            if field_no == 1 and wire == 2:  # NodeProto
                nodes += 1
                for nf, nw, nv in _pb_fields(bytes(value)):
                    if nf == 4 and nw == 2:
                        op = bytes(nv).decode("utf-8", "replace")[:64]
                        op_hist[op] = op_hist.get(op, 0) + 1
                        break
            elif field_no == 2 and wire == 2:
                graph_name = bytes(value).decode("utf-8", "replace")[:120]
            elif field_no == 5 and wire == 2:  # TensorProto initializer
                initializers += 1
                dims: List[int] = []
                dtype = 0
                for tf, tw, tv in _pb_fields(bytes(value)):
                    if tf == 1 and tw == 2:  # packed dims
                        p = 0
                        while p < len(tv):
                            d, p = _pb_varint(tv, p)
                            dims.append(d)
                    elif tf == 1 and tw == 0:
                        dims.append(tv)
                    elif tf == 2 and tw == 0:
                        dtype = tv
                count = 1
                for d in dims:
                    count *= max(1, d)
                total_params += count
                dname = ONNX_DTYPES.get(dtype, f"DTYPE_{dtype}")
                dtype_hist[dname] = dtype_hist.get(dname, 0) + 1

    return {
        "format": "onnx",
        "size_bytes": st.st_size,
        "size_human": _human_bytes(st.st_size),
        "ir_version": ir_version,
        "producer": producer,
        "producer_version": producer_version,
        "graph_name": graph_name,
        "node_count": nodes,
        "initializer_count": initializers,
        "parameter_count": total_params,
        "parameter_count_human": _human_params(total_params),
        "dtype_mix": dtype_hist,
        "primary_dtype": max(dtype_hist, key=dtype_hist.get) if dtype_hist else None,
        "op_mix": dict(sorted(op_hist.items(), key=lambda kv: kv[1], reverse=True)[:24]),
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Config Transformers
# ---------------------------------------------------------------------------
def parse_config(path: Path) -> Dict[str, Any]:
    payload = _read_json(path, default={})
    if not isinstance(payload, dict):
        return {"format": "config", "warnings": ["config no es un objeto JSON"]}

    archs = payload.get("architectures") or []
    model_type = str(payload.get("model_type", "") or "").lower()
    arch_key = model_type or (str(archs[0]).lower() if archs else "unknown")
    arch_key = re.sub(r"for.*$", "", arch_key) or "unknown"
    traits = ARCHITECTURE_TRAITS.get(arch_key, {})

    hidden = _safe_int(payload.get("hidden_size") or payload.get("n_embd") or payload.get("d_model"))
    layers = _safe_int(payload.get("num_hidden_layers") or payload.get("n_layer") or payload.get("num_layers"))
    heads = _safe_int(payload.get("num_attention_heads") or payload.get("n_head"))
    kv_heads = _safe_int(payload.get("num_key_value_heads") or heads)
    inter = _safe_int(payload.get("intermediate_size") or payload.get("n_inner"))
    vocab = _safe_int(payload.get("vocab_size"))
    max_pos = _safe_int(payload.get("max_position_embeddings") or payload.get("n_positions") or payload.get("seq_length"))
    rope_theta = payload.get("rope_theta") or payload.get("rope_scaling")
    quant_cfg = payload.get("quantization_config") or {}
    moe = _safe_int(payload.get("num_local_experts") or payload.get("num_experts") or payload.get("n_routed_experts"))

    return {
        "format": "config",
        "size_bytes": path.stat().st_size,
        "model_type": model_type,
        "architectures": archs,
        "architecture": arch_key,
        "traits": traits,
        "hidden_size": hidden,
        "layers": layers,
        "heads": heads,
        "kv_heads": kv_heads,
        "gqa_ratio": round(heads / kv_heads, 3) if heads and kv_heads else None,
        "intermediate_size": inter,
        "vocab_size": vocab,
        "max_position_embeddings": max_pos,
        "rope_theta": rope_theta,
        "experts": moe,
        "torch_dtype": payload.get("torch_dtype"),
        "quantization_config": quant_cfg if isinstance(quant_cfg, dict) else {},
        "tie_word_embeddings": payload.get("tie_word_embeddings"),
        "sliding_window": payload.get("sliding_window"),
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Sonda REA (CLI externa, opcional)
# ---------------------------------------------------------------------------
def rea_available() -> bool:
    return os.path.exists(REA_BIN) or bool(_which("rea"))


def _which(name: str) -> Optional[str]:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def rea_probe(path: Path, command: str = "inspect-artifact", timeout: int = REA_TIMEOUT_S) -> Dict[str, Any]:
    """Invoca REA en modo lectura y devuelve JSON acotado. Nunca ejecuta el artefacto."""
    binary = REA_BIN if os.path.exists(REA_BIN) else (_which("rea") or "")
    if not binary:
        return {"ok": False, "error": "rea no instalado"}
    env = dict(os.environ)
    env.update({"NO_COLOR": "1", "FORCE_COLOR": "0", "CI": "1", "TERM": "dumb"})
    cmd = [binary, command, str(path), "--format", "json"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout tras {timeout}s", "command": command}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "command": command}

    stdout = (proc.stdout or "")[:REA_MAX_OUTPUT]
    stderr = (proc.stderr or "")[:4000]
    payload: Any = None
    # El CLI puede anteponer warnings; buscar el primer bloque JSON válido.
    for start in (0, stdout.find("{"), stdout.find("[")):
        if start < 0:
            continue
        try:
            payload = json.loads(stdout[start:])
            break
        except Exception:
            continue
    return {
        "ok": proc.returncode == 0 and payload is not None,
        "command": command,
        "returncode": proc.returncode,
        "data": payload,
        "stderr": stderr.strip()[:1000] if proc.returncode != 0 else "",
    }


# ---------------------------------------------------------------------------
# Descubrimiento de artefactos
# ---------------------------------------------------------------------------
DEFAULT_ROOTS = [
    BASE_DIR / "models",
    Path.home() / "models",
    Path.home() / ".cache" / "huggingface" / "hub",
    Path.home() / ".cache" / "lm-studio" / "models",
    Path.home() / ".ollama" / "models",
    Path.home() / ".cache" / "llama.cpp",
    Path("/usr/share/ollama/.ollama/models"),
    Path("/opt/models"),
]

# Origen lógico de artefactos descubiertos fuera de una ruta con extensión.
ARTIFACT_ORIGINS: Dict[str, Dict[str, Any]] = {}

OLLAMA_MANIFEST_ROOTS = [
    Path.home() / ".ollama" / "models" / "manifests",
    Path("/usr/share/ollama/.ollama/models/manifests"),
]


def discover_ollama_blobs() -> List[Path]:
    """Resuelve manifiestos Ollama -> blobs GGUF reales (sin extensión)."""
    found: List[Path] = []
    for root in OLLAMA_MANIFEST_ROOTS:
        if not root.exists():
            continue
        blobs_dir = root.parent / "blobs"
        if not blobs_dir.exists():
            continue
        for manifest in root.rglob("*"):
            if not manifest.is_file():
                continue
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception:
                continue
            layers = payload.get("layers") or []
            model_name = manifest.parent.name + ":" + manifest.name
            for layer in layers:
                media = str(layer.get("mediaType") or "")
                if not (media.endswith("image.model") or media.endswith("image.projector")):
                    continue
                digest = str(layer.get("digest") or "")
                if not digest.startswith("sha256:"):
                    continue
                blob = blobs_dir / ("sha256-" + digest.split(":", 1)[1])
                if not blob.exists():
                    continue
                try:
                    with open(blob, "rb") as fh:
                        if fh.read(4) != b"GGUF":
                            continue
                except OSError:
                    continue
                key = str(blob.resolve())
                ARTIFACT_ORIGINS[key] = {
                    "origin": "ollama",
                    "model": model_name,
                    "manifest": str(manifest),
                    "media_type": media,
                }
                found.append(blob)
    return found


def discover_artifacts(roots: Optional[Sequence[Path]] = None) -> List[Path]:
    """Descubre artefactos de modelo locales, sin seguir enlaces circulares."""
    roots = [Path(r).expanduser() for r in (roots or DEFAULT_ROOTS)]
    found: List[Path] = []
    seen_inodes: set[Tuple[int, int]] = set()
    visited_dirs: set[str] = set()
    count = 0

    for root in roots:
        if not root.exists():
            continue
        try:
            real_root = str(root.resolve())
        except OSError:
            continue
        if real_root in visited_dirs:
            continue
        visited_dirs.add(real_root)
        stack: List[Tuple[Path, int]] = [(root, 0)]
        while stack:
            current, depth = stack.pop()
            if depth > MAX_SCAN_DEPTH or count >= MAX_SCAN_FILES:
                continue
            try:
                entries = list(os.scandir(current))
            except (OSError, PermissionError):
                continue
            for entry in entries:
                if count >= MAX_SCAN_FILES:
                    break
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append((Path(entry.path), depth + 1))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    st = entry.stat(follow_symlinks=False)
                    inode = (st.st_dev, st.st_ino)
                    if inode in seen_inodes:
                        continue
                    seen_inodes.add(inode)
                    count += 1
                    p = Path(entry.path)
                    suffix = p.suffix.lower()
                    if suffix in MODEL_EXTENSIONS or p.name in CONFIG_NAMES:
                        found.append(p)
                except OSError:
                    continue
    # Orden estable y deduplicado
    unique = {str(p.resolve()): p for p in found}
    for blob in discover_ollama_blobs():
        unique.setdefault(str(blob.resolve()), blob)
    return sorted(unique.values(), key=lambda p: str(p))


# ---------------------------------------------------------------------------
# Motor de aprendizaje
# ---------------------------------------------------------------------------
@dataclass
class Fingerprint:
    path: str
    format: str
    fingerprint: str
    size_bytes: int
    size_human: str
    data: Dict[str, Any] = field(default_factory=dict)
    rea: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)
    learned_at: str = field(default_factory=_now)


class LearningEngine:
    """Orquesta descubrimiento, parsing, conocimiento y propuestas."""

    def __init__(self, use_rea: bool = True, verbose: bool = False):
        _ensure_dirs()
        self.use_rea = use_rea
        self.verbose = verbose

    # -- logging ---------------------------------------------------------
    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[rea-learn] {msg}", file=sys.stderr, flush=True)

    def _audit(self, action: str, payload: Dict[str, Any]) -> None:
        _append_jsonl(AUDIT_PATH, {"at": _now(), "action": action, **payload})

    # -- parsing ---------------------------------------------------------
    def inspect_path(self, path: Path) -> Fingerprint:
        suffix = path.suffix.lower()
        errors: List[str] = []
        data: Dict[str, Any] = {}
        fmt = suffix.lstrip(".") or path.name

        sniff = sniff_format(path)
        real = str(sniff.get("format") or "unknown")
        if sniff.get("error"):
            errors.append(f"integridad: {sniff['error']}")
        # Un archivo vacío o disfrazado no debe intentar parsearse como su extensión.
        corrupt = real in ("empty", "html", "lfs_pointer", "unreadable")

        try:
            if corrupt:
                data = {
                    "format": real,
                    "size_bytes": int(sniff.get("size_bytes", 0)),
                    "size_human": _human_bytes(int(sniff.get("size_bytes", 0))),
                    "warnings": errors[:],
                    "integrity": "corrupt",
                }
                fmt = real
            elif real == "gguf" or suffix in (".gguf", ".ggml"):
                data = parse_gguf(path)
                fmt = "gguf"
            elif real == "safetensors" or suffix == ".safetensors":
                data = parse_safetensors(path)
                fmt = "safetensors"
            elif suffix == ".onnx":
                if real != "protobuf":
                    raise ValueError(f"firma ONNX inválida (detectado: {real})")
                data = parse_onnx(path)
                fmt = "onnx"
            elif path.name in CONFIG_NAMES:
                data = parse_config(path)
                fmt = "config"
            else:
                # Binarios opacos: sólo metadatos + sonda REA
                st = path.stat()
                data = {
                    "format": "binary",
                    "size_bytes": st.st_size,
                    "size_human": _human_bytes(st.st_size),
                    "warnings": ["formato no reconocido; se usa sonda REA"],
                }
                fmt = "binary"
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
            try:
                st = path.stat()
                size = st.st_size
            except OSError:
                size = 0
            data = {"format": fmt, "size_bytes": size, "size_human": _human_bytes(size), "warnings": errors}

        origin = ARTIFACT_ORIGINS.get(str(path.resolve()))
        if origin:
            data["origin"] = origin

        rea_payload = None
        if self.use_rea and fmt in ("binary", "onnx"):
            probe = rea_probe(path, "inspect-artifact")
            if probe.get("ok"):
                rea_payload = probe.get("data")
            elif probe.get("error"):
                errors.append(f"rea: {probe['error']}")

        return Fingerprint(
            path=str(path),
            format=fmt,
            fingerprint=_quick_fingerprint(path),
            size_bytes=int(data.get("size_bytes", 0)),
            size_human=str(data.get("size_human", "")),
            data=data,
            rea=rea_payload,
            errors=errors,
        )

    # -- insights --------------------------------------------------------
    def derive_insights(self, fp: Fingerprint) -> List[Dict[str, Any]]:
        d = fp.data or {}
        insights: List[Dict[str, Any]] = []

        def add(kind: str, key: str, value: Any, confidence: str = "high", note: str = "") -> None:
            insights.append({
                "kind": kind, "key": key, "value": value,
                "confidence": confidence, "note": note,
                "source": fp.path, "format": fp.format,
            })

        arch = str(d.get("architecture") or d.get("model_type") or "").lower()
        traits = d.get("traits") or ARCHITECTURE_TRAITS.get(arch, {})
        if arch:
            add("architecture", "family", traits.get("family", "unknown"), "medium", f"architecture={arch}")
        for trait in ("norm", "activation", "pos", "attention", "bias"):
            if traits.get(trait):
                add("design", trait, traits[trait], "high")

        params = _safe_int(d.get("parameter_count"))
        if params:
            add("scale", "parameters", params, "high", _human_params(params))
        quant = d.get("primary_quantization") or d.get("primary_dtype")
        if quant:
            add("efficiency", "precision", quant, "high", json.dumps(d.get("quantization_mix") or d.get("dtype_mix") or {}))
        ctx = _safe_int(d.get("context_length") or d.get("max_position_embeddings"))
        if ctx:
            add("capability", "context_window", ctx, "high")
        vocab = _safe_int(d.get("vocab_size"))
        if vocab:
            add("tokenizer", "vocab_size", vocab, "high")
        gqa = d.get("gqa_ratio")
        if gqa and float(gqa) > 1.0:
            add("efficiency", "grouped_query_attention", float(gqa), "high",
                f"{d.get('heads')} heads / {d.get('kv_heads')} kv heads")
        experts = _safe_int(d.get("experts"))
        if experts:
            add("efficiency", "mixture_of_experts", experts, "high",
                f"top-k={d.get('experts_used') or 'n/d'}")
        rope = d.get("rope_freq_base") or d.get("rope_theta")
        if rope:
            try:
                add("capability", "rope_freq_base", float(rope), "high")
            except (TypeError, ValueError):
                add("capability", "rope_scaling", rope, "medium")
        sliding = d.get("sliding_window")
        if sliding:
            add("efficiency", "sliding_window_attention", sliding, "high")
        layers = _safe_int(d.get("layers") or d.get("detected_layers"))
        if layers:
            add("scale", "layers", layers, "high")
        hidden = _safe_int(d.get("hidden_size") or d.get("embedding_length"))
        if hidden:
            add("scale", "hidden_size", hidden, "high")
        ops = d.get("op_mix")
        if ops:
            add("compute", "operator_mix", ops, "medium")
        meta = d.get("metadata")
        if isinstance(meta, dict):
            for key in ("general.name", "general.basename", "general.organization", "general.license"):
                if meta.get(key):
                    add("provenance", key.split(".")[-1], _truncate(str(meta[key])), "medium")
        return insights

    # -- scan ------------------------------------------------------------
    def scan(self, paths: Optional[Sequence[Path]] = None, roots: Optional[Sequence[Path]] = None,
             max_files: Optional[int] = None) -> Dict[str, Any]:
        targets: List[Path] = []
        if paths:
            for raw in paths:
                p = Path(raw).expanduser()
                if p.is_dir():
                    targets.extend(discover_artifacts([p]))
                elif p.is_file():
                    targets.append(p)
        else:
            targets = discover_artifacts(roots)
        # Deduplicar y limitar
        seen: set[str] = set()
        unique: List[Path] = []
        for p in targets:
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            unique.append(p)
        if max_files:
            unique = unique[:max_files]

        self._log(f"artefactos detectados: {len(unique)}")
        fingerprints: List[Fingerprint] = []
        skipped: List[Dict[str, str]] = []
        for idx, p in enumerate(unique, 1):
            self._log(f"[{idx}/{len(unique)}] {p}")
            # Los configs sueltos sólo interesan si acompañan a un modelo o son únicos.
            if p.name in CONFIG_NAMES:
                try:
                    if p.stat().st_size < 8:
                        skipped.append({"path": str(p), "reason": "config vacío"})
                        continue
                except OSError as exc:
                    skipped.append({"path": str(p), "reason": str(exc)})
                    continue
            fp = self.inspect_path(p)
            fingerprints.append(fp)
            record = {
                "at": _now(),
                "fingerprint": fp.fingerprint,
                "path": fp.path,
                "format": fp.format,
                "size_bytes": fp.size_bytes,
                "summary": self._summarize(fp),
                "insights": self.derive_insights(fp),
                "errors": fp.errors,
            }
            _append_jsonl(KB_PATH, record)

        self._audit("scan", {"artifacts": len(fingerprints), "skipped": len(skipped)})
        state = _read_json(STATE_PATH, default={}) or {}
        state.update({
            "last_scan_at": _now(),
            "artifacts_total": len(fingerprints),
            "last_scan_paths": [fp.path for fp in fingerprints][:200],
            "engine_version": "26.4.0",
        })
        _atomic_write(STATE_PATH, state)
        return {
            "ok": True,
            "scanned": len(fingerprints),
            "skipped": skipped,
            "fingerprints": [asdict(fp) for fp in fingerprints],
        }

    def _summarize(self, fp: Fingerprint) -> Dict[str, Any]:
        d = fp.data or {}
        origin = d.get("origin") or {}
        return {
            "format": fp.format,
            "architecture": d.get("architecture") or d.get("model_type"),
            "parameters": d.get("parameter_count"),
            "parameters_human": d.get("parameter_count_human"),
            "context_length": d.get("context_length") or d.get("max_position_embeddings"),
            "quantization": d.get("primary_quantization") or d.get("primary_dtype"),
            "layers": d.get("layers"),
            "size_human": fp.size_human,
            "origin": origin.get("origin"),
            "model": origin.get("model"),
            "errors": fp.errors[:4],
        }

    # -- knowledge base --------------------------------------------------
    def load_kb(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        if not KB_PATH.exists():
            return records
        try:
            with open(KB_PATH, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        continue
        except OSError:
            pass
        return records

    def build_report(self) -> Dict[str, Any]:
        kb = self.load_kb()
        # Última observación por fingerprint
        latest: Dict[str, Dict[str, Any]] = {}
        for rec in kb:
            fp = rec.get("fingerprint")
            if fp:
                latest[fp] = rec

        artifacts = list(latest.values())
        architectures: Dict[str, int] = {}
        quants: Dict[str, int] = {}
        formats: Dict[str, int] = {}
        insight_index: Dict[str, Dict[str, Any]] = {}
        total_params = 0
        for rec in artifacts:
            s = rec.get("summary") or {}
            arch = s.get("architecture") or "unknown"
            architectures[arch] = architectures.get(arch, 0) + 1
            q = s.get("quantization") or "unknown"
            quants[q] = quants.get(q, 0) + 1
            formats[rec.get("format", "?")] = formats.get(rec.get("format", "?"), 0) + 1
            total_params += _safe_int(s.get("parameters"))
            for ins in rec.get("insights") or []:
                key = f"{ins.get('kind')}:{ins.get('key')}:{ins.get('value')}"
                if key not in insight_index:
                    insight_index[key] = {**ins, "occurrences": 0, "artifacts": []}
                insight_index[key]["occurrences"] += 1
                if rec.get("path") not in insight_index[key]["artifacts"]:
                    insight_index[key]["artifacts"].append(rec.get("path"))

        report = {
            "schema": REPORT_SCHEMA,
            "generated_at": _now(),
            "engine_version": "26.4.0",
            "artifacts_analyzed": len(artifacts),
            "formats": formats,
            "architectures": architectures,
            "quantizations": quants,
            "total_parameters": total_params,
            "total_parameters_human": _human_params(total_params),
            "insights": sorted(insight_index.values(), key=lambda i: i["occurrences"], reverse=True),
            "artifacts": [
                {
                    "path": rec.get("path"),
                    "format": rec.get("format"),
                    "fingerprint": rec.get("fingerprint"),
                    "learned_at": rec.get("at"),
                    **(rec.get("summary") or {}),
                }
                for rec in sorted(artifacts, key=lambda r: r.get("path") or "")
            ],
            "kb_records": len(kb),
            "coverage": {
                "has_local_models": bool(artifacts),
                "architectures_known": sum(1 for a in architectures if a in ARCHITECTURE_TRAITS),
                "architectures_unknown": sum(1 for a in architectures if a not in ARCHITECTURE_TRAITS and a != "unknown"),
            },
            "notes": [
                "El análisis es estático: no se ejecuta ningún artefacto.",
                "Las propuestas se generan a partir de rasgos arquitectónicos observados.",
            ],
        }
        _atomic_write(REPORT_PATH, report)
        return report

    # -- propuestas ------------------------------------------------------
    def build_proposals(self) -> Dict[str, Any]:
        report = self.build_report()
        artifacts = report.get("artifacts", [])
        proposals: Dict[str, Dict[str, Any]] = {}

        def add(title: str, target: str, risk: str, kind: str, change: Dict[str, Any],
                evidence: List[str], rationale: str, validation: str, rollback: str) -> None:
            pid = "rea-" + hashlib.sha1(
                json.dumps([target, kind, change], sort_keys=True).encode("utf-8")
            ).hexdigest()[:12]
            if pid in proposals:
                proposals[pid]["evidence"] = sorted(set(proposals[pid]["evidence"] + evidence))
                return
            proposals[pid] = {
                "id": pid, "title": title, "target": target, "risk": risk, "kind": kind,
                "change": change, "evidence": evidence, "rationale": rationale,
                "validation": validation, "rollback": rollback,
                "status": "proposed", "created_at": _now(),
            }

        # 1) Perfil de adaptación base (siempre de riesgo bajo)
        add(
            "Publicar perfil de adaptación REA para TARDIS/FTL",
            "tardis", "low", "profile",
            {"file": str(PROFILE_PATH), "key": "profile", "value": "generated"},
            [a.get("path") for a in artifacts][:8] or ["sin artefactos locales"],
            "Consolida el conocimiento arquitectónico observado en un perfil que el router y Easy Touch pueden consumir.",
            "JSON válido y esquema tardis.rea.adaptation_profile/1.0",
            "Regenerar el perfil desde la base de conocimiento.",
        )

        # 2) Ajustes derivados de artefactos
        for a in artifacts:
            path = a.get("path") or ""
            arch = (a.get("architecture") or "").lower()
            ctx = _safe_int(a.get("context_length"))
            params = _safe_int(a.get("parameters"))
            quant = a.get("quantization")
            layers = _safe_int(a.get("layers"))

            if ctx >= 32768:
                add(
                    f"Perfil de contexto largo ({ctx} tokens) para modelos {arch or 'locales'}",
                    "tardis", "low", "experiment",
                    {"file": str(EXPERIMENTS_DIR / "long_context.json"), "key": "context_profile", "value": {"context_length": ctx, "source": path}},
                    [path],
                    f"El artefacto declara una ventana de {ctx} tokens; TARDIS puede adoptar chunking y presupuesto de prompt equivalentes.",
                    "Medir latencia y calidad en una muestra de 20 prompts antes de elevar el contexto por defecto.",
                    "Volver a ctx_size=4096 en temporal_brain_config.json.",
                )
            if quant and any(q in str(quant).upper() for q in ("Q4", "Q5", "Q8", "INT8", "F16", "BF16")):
                add(
                    f"Política de precisión inspirada en {quant}",
                    "ftl", "low", "experiment",
                    {"file": str(EXPERIMENTS_DIR / "precision_policy.json"), "key": "precision", "value": {"observed": quant, "source": path}},
                    [path],
                    "Ajustar el presupuesto de VRAM/quantización del router según la precisión observada en modelos locales.",
                    "Comparar tokens/s y perplejidad en el mismo prompt.",
                    "Descartar el experimento; no altera configuración activa.",
                )
            if layers and layers >= 32:
                add(
                    f"Estrategia de offload por capas para {layers} capas",
                    "ftl", "low", "experiment",
                    {"file": str(EXPERIMENTS_DIR / "layer_offload.json"), "key": "offload", "value": {"layers": layers, "vram_gb": 4, "source": path}},
                    [path],
                    "Con 4 GB de VRAM, un modelo de muchas capas requiere offload parcial; planificar por capas evita OOM.",
                    "Verificar que llama.cpp/ollama acepten n_gpu_layers calculado.",
                    "Mantener gpu_layers=0 en temporal_brain_config.json.",
                )
            if params >= 7_000_000_000:
                add(
                    f"Ruteo de modelos grandes ({_human_params(params)}) a la malla local",
                    "tardis", "low", "experiment",
                    {"file": str(EXPERIMENTS_DIR / "large_model_routing.json"), "key": "routing", "value": {"min_params": params, "target": "local-mesh", "source": path}},
                    [path],
                    "Los modelos de gran escala no caben en 4 GB de VRAM; derivarlos a la malla o a la nube evita degradación.",
                    "Comprobar latencia del endpoint imac.local:11434.",
                    "Reactivar la ruta por defecto en coding_router.json.",
                )

        # 3) Colectivo: si hay GQA/MoE en varios artefactos
        gqa_hits = [i for i in report.get("insights", []) if i.get("key") == "grouped_query_attention"]
        if gqa_hits:
            add(
                "Habilitar caché KV con GQA en el motor temporal",
                "tardis", "medium", "config",
                {"file": str(BASE_DIR / "temporal_brain_config.json"), "key": "cache_type_k", "value": "q8_0"},
                [h["artifacts"][0] for h in gqa_hits if h.get("artifacts")][:4],
                "GQA reduce el número de cabezas KV; cuantizar la caché KV a q8_0 libera VRAM sin cambiar la arquitectura.",
                "Ejecutar 10 inferencias y comparar perplejidad; revertir si supera +2%.",
                "Restaurar cache_type_k=f16 desde el backup automático.",
            )
        moe_hits = [i for i in report.get("insights", []) if i.get("key") == "mixture_of_experts"]
        if moe_hits:
            add(
                "Ruteo consciente de MoE (top-k) para modelos dispersos",
                "tardis", "low", "experiment",
                {"file": str(EXPERIMENTS_DIR / "moe_routing.json"), "key": "moe", "value": {"observed": [h.get("value") for h in moe_hits]}},
                [h["artifacts"][0] for h in moe_hits if h.get("artifacts")][:4],
                "Los modelos MoE activan sólo una fracción de parámetros; el router debe estimar costo por token activo, no por tamaño total.",
                "Comparar tokens/s y VRAM pico con un MoE local.",
                "Descartar el experimento.",
            )
        sliding_hits = [i for i in report.get("insights", []) if i.get("key") == "sliding_window_attention"]
        if sliding_hits:
            add(
                "Chunking con ventana deslizante para contexto efectivo",
                "ftl", "low", "experiment",
                {"file": str(EXPERIMENTS_DIR / "sliding_window.json"), "key": "chunking", "value": {"windows": [h.get("value") for h in sliding_hits]}},
                [h["artifacts"][0] for h in sliding_hits if h.get("artifacts")][:4],
                "Las arquitecturas con sliding window degradan fuera de su ventana; el chunking debe alinearse al tamaño declarado.",
                "Validar recuperación de un documento de 64k tokens.",
                "Volver al chunking por defecto.",
            )

        payload = {
            "schema": PROPOSAL_SCHEMA,
            "generated_at": _now(),
            "based_on_report": str(REPORT_PATH),
            "artifacts": len(artifacts),
            "proposals": sorted(proposals.values(), key=lambda p: ({"low": 0, "medium": 1, "high": 2}[p["risk"]], p["id"])),
        }
        # Preservar el estado de propuestas ya aplicadas/fallidas entre regeneraciones.
        previous = {
            p.get("id"): p for p in (_read_json(PROPOSALS_PATH, default={}) or {}).get("proposals", [])
            if isinstance(p, dict) and p.get("id")
        }
        for proposal in payload["proposals"]:
            old = previous.get(proposal["id"])
            if old and old.get("status") in ("applied", "failed"):
                proposal["status"] = old["status"]
                for key in ("applied_at", "result", "error"):
                    if key in old:
                        proposal[key] = old[key]
        _atomic_write(PROPOSALS_PATH, payload)
        self._audit("propose", {"proposals": len(payload["proposals"])})
        return payload

    # -- aplicación ------------------------------------------------------
    def apply(self, ids: Optional[Sequence[str]] = None, all_low: bool = False,
              apply_medium: bool = False) -> Dict[str, Any]:
        payload = _read_json(PROPOSALS_PATH, default=None)
        if not payload:
            payload = self.build_proposals()
        proposals = payload.get("proposals", [])
        selected: List[Dict[str, Any]] = []
        for p in proposals:
            if ids and p["id"] not in ids:
                continue
            if all_low and p["risk"] != "low":
                continue
            if not ids and not all_low:
                continue
            if p["risk"] == "medium" and not apply_medium:
                continue
            if p["risk"] == "high":
                continue
            selected.append(p)

        applied: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        for p in selected:
            if p.get("status") == "applied":
                skipped.append({"id": p["id"], "reason": "ya aplicada"})
                continue
            change = p.get("change") or {}
            try:
                if p["kind"] == "profile":
                    self._write_profile()
                    result = {"file": str(PROFILE_PATH)}
                elif p["kind"] == "experiment":
                    target = Path(change.get("file") or (EXPERIMENTS_DIR / f"{p['id']}.json"))
                    _atomic_write(target, {"proposal_id": p["id"], "created_at": _now(), **change})
                    result = {"file": str(target)}
                elif p["kind"] == "config":
                    result = self._apply_config_change(p)
                else:
                    skipped.append({"id": p["id"], "reason": f"kind no aplicable: {p['kind']}"})
                    continue
                p["status"] = "applied"
                p["applied_at"] = _now()
                p["result"] = result
                applied.append({"id": p["id"], "title": p["title"], "result": result})
                self._audit("apply", {"id": p["id"], "risk": p["risk"], "result": result})
            except Exception as exc:  # noqa: BLE001
                p["status"] = "failed"
                p["error"] = f"{type(exc).__name__}: {exc}"
                skipped.append({"id": p["id"], "reason": p["error"]})
                self._audit("apply_failed", {"id": p["id"], "error": p["error"]})

        payload["applied_at"] = _now()
        _atomic_write(PROPOSALS_PATH, payload)
        return {"ok": True, "applied": applied, "skipped": skipped, "selected": len(selected)}

    def _write_profile(self) -> None:
        report = self.build_report()
        profile = {
            "schema": PROFILE_SCHEMA,
            "generated_at": _now(),
            "source_report": str(REPORT_PATH),
            "architectures": report.get("architectures", {}),
            "quantizations": report.get("quantizations", {}),
            "total_parameters": report.get("total_parameters", 0),
            "capabilities": {
                "long_context": any(
                    _safe_int(a.get("context_length")) >= 32768 for a in report.get("artifacts", [])
                ),
                "gqa": any(i.get("key") == "grouped_query_attention" for i in report.get("insights", [])),
                "moe": any(i.get("key") == "mixture_of_experts" for i in report.get("insights", [])),
                "sliding_window": any(i.get("key") == "sliding_window_attention" for i in report.get("insights", [])),
            },
            "routing_hints": {
                "prefer_local_for": ["privacy", "offline", "bulk"],
                "prefer_cloud_for": ["apex_reasoning", "long_context_overflow", "vision"],
                "vram_budget_gb": 4,
            },
            "consumers": ["tardis.router", "ftl.executor", "easy_touch"],
        }
        _atomic_write(PROFILE_PATH, profile)

    def _apply_config_change(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        change = proposal.get("change") or {}
        file_path = Path(change.get("file") or "")
        key = change.get("key")
        value = change.get("value")
        if not file_path or not key:
            raise ValueError("cambio de configuración incompleto")
        # Sólo JSON dentro del árbol del proyecto o ~/.ftl
        allowed_roots = [BASE_DIR.resolve(), (Path.home() / ".ftl").resolve()]
        resolved = file_path.resolve()
        if not any(str(resolved).startswith(str(root)) for root in allowed_roots):
            raise PermissionError(f"ruta no permitida: {resolved}")
        if resolved.suffix.lower() != ".json":
            raise PermissionError("sólo se aplican cambios sobre archivos JSON")
        payload = _read_json(resolved, default=None)
        if not isinstance(payload, dict):
            raise ValueError("configuración destino no es un objeto JSON")
        if payload.get(key) == value:
            return {"file": str(resolved), "key": key, "value": value, "changed": False}
        backup = resolved.with_suffix(resolved.suffix + f".bak.rea.{int(time.time())}")
        backup.write_bytes(resolved.read_bytes())
        payload[key] = value
        _atomic_write(resolved, payload)
        return {"file": str(resolved), "key": key, "value": value, "changed": True, "backup": str(backup)}

    # -- estado ----------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        state = _read_json(STATE_PATH, default={}) or {}
        report = _read_json(REPORT_PATH, default={}) or {}
        proposals = _read_json(PROPOSALS_PATH, default={}) or {}
        return {
            "ok": True,
            "engine": "REA Learning Engine",
            "version": "26.4.0",
            "rea_available": rea_available(),
            "rea_bin": REA_BIN if os.path.exists(REA_BIN) else _which("rea"),
            "data_dir": str(DATA_DIR),
            "knowledge_base": {"path": str(KB_PATH), "records": len(self.load_kb()) if KB_PATH.exists() else 0},
            "last_scan_at": state.get("last_scan_at"),
            "artifacts_total": state.get("artifacts_total", 0),
            "report": {
                "path": str(REPORT_PATH),
                "generated_at": report.get("generated_at"),
                "artifacts": report.get("artifacts_analyzed", 0),
                "architectures": report.get("architectures", {}),
            },
            "proposals": {
                "path": str(PROPOSALS_PATH),
                "total": len(proposals.get("proposals", [])),
                "by_risk": _count_by(proposals.get("proposals", []), "risk"),
                "by_status": _count_by(proposals.get("proposals", []), "status"),
            },
        }


def _count_by(items: Iterable[Dict[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for item in items:
        value = str(item.get(key, "?"))
        out[value] = out.get(value, 0) + 1
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rea-learn",
        description="Motor de aprendizaje REA de TARDIS: ingeniería inversa estática de modelos locales.",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    p_scan = sub.add_parser("scan", help="Descubrir y analizar artefactos locales")
    p_scan.add_argument("paths", nargs="*", help="Rutas o directorios explícitos")
    p_scan.add_argument("--root", action="append", default=[], help="Raíz adicional de búsqueda")
    p_scan.add_argument("--no-rea", action="store_true", help="No invocar el CLI REA")
    p_scan.add_argument("--max-files", type=int, default=0, help="Límite de artefactos")
    p_scan.add_argument("--json", action="store_true", help="Salida JSON completa")

    p_report = sub.add_parser("report", help="Generar informe de aprendizaje agregado")
    p_report.add_argument("--json", action="store_true")

    p_prop = sub.add_parser("propose", help="Generar propuestas de auto-adaptación")
    p_prop.add_argument("--json", action="store_true")

    p_apply = sub.add_parser("apply", help="Aplicar propuestas de bajo riesgo")
    p_apply.add_argument("--ids", nargs="*", default=[], help="IDs específicos")
    p_apply.add_argument("--all-low", action="store_true", help="Aplicar todas las de riesgo bajo")
    p_apply.add_argument("--apply-medium", action="store_true", help="Permitir cambios de riesgo medio (con backup)")

    sub.add_parser("status", help="Estado del motor")
    p_kb = sub.add_parser("kb", help="Consultar la base de conocimiento")
    p_kb.add_argument("--limit", type=int, default=20)
    p_kb.add_argument("--path", default="", help="Filtrar por subcadena de ruta")

    args = parser.parse_args(argv)
    cmd = args.command or "status"
    engine = LearningEngine(use_rea=not getattr(args, "no_rea", False), verbose=True)

    if cmd == "scan":
        roots = [Path(r) for r in getattr(args, "root", [])] or None
        result = engine.scan(paths=getattr(args, "paths", []) or None, roots=roots,
                             max_files=getattr(args, "max_files", 0) or None)
        if getattr(args, "json", False):
            _print_json(result)
        else:
            print(f"✔ Artefactos analizados: {result['scanned']}")
            for fp in result["fingerprints"]:
                s = engine._summarize(Fingerprint(**{**fp}))
                print(f"  • {fp['path']}")
                print(f"    {s['format']} | {s['architecture'] or 'n/d'} | {s['parameters_human'] or 'n/d'} params | ctx={s['context_length'] or 'n/d'} | {s['quantization'] or 'n/d'}")
                if s["errors"]:
                    print(f"    ⚠ {s['errors']}")
        return 0

    if cmd == "report":
        report = engine.build_report()
        if getattr(args, "json", False):
            _print_json(report)
        else:
            print(f"✔ Informe: {REPORT_PATH}")
            print(f"  Artefactos: {report['artifacts_analyzed']} | Parámetros totales: {report['total_parameters_human']}")
            print(f"  Arquitecturas: {report['architectures']}")
            print(f"  Cuantizaciones: {report['quantizations']}")
            print(f"  Insights: {len(report['insights'])}")
        return 0

    if cmd == "propose":
        payload = engine.build_proposals()
        if getattr(args, "json", False):
            _print_json(payload)
        else:
            print(f"✔ Propuestas: {PROPOSALS_PATH} ({len(payload['proposals'])})")
            for p in payload["proposals"]:
                print(f"  [{p['risk']:6}] {p['id']} · {p['title']}")
        return 0

    if cmd == "apply":
        result = engine.apply(ids=args.ids, all_low=args.all_low, apply_medium=args.apply_medium)
        _print_json(result)
        return 0

    if cmd == "kb":
        records = engine.load_kb()
        if args.path:
            records = [r for r in records if args.path in str(r.get("path", ""))]
        for rec in records[-max(1, args.limit):]:
            s = rec.get("summary") or {}
            print(f"{rec.get('at')} | {rec.get('format')} | {s.get('architecture') or 'n/d'} | "
                  f"{s.get('parameters_human') or 'n/d'} | {rec.get('path')}")
        print(f"\nTotal registros: {len(records)}")
        return 0

    _print_json(engine.status())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
