# Copyright 2026 The HuggingFace Team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Dequantizing GGUF blocks with torch ops.

Inspired by ComfyUI-GGUF (c) City96, Apache-2.0: https://github.com/city96/ComfyUI-GGUF
"""

import torch


# ggml type ids, as numbered by `enum ggml_type` in ggml.h
GGML_Q4_0, GGML_Q4_1, GGML_Q8_0 = 2, 3, 8
GGML_Q2_K, GGML_Q3_K, GGML_Q4_K, GGML_Q5_K, GGML_Q6_K = 10, 11, 12, 13, 14
GGML_IQ2_XXS, GGML_IQ2_XS, GGML_IQ3_XXS, GGML_IQ1_S = 16, 17, 18, 19
GGML_IQ4_NL, GGML_IQ3_S, GGML_IQ2_S, GGML_IQ4_XS, GGML_IQ1_M = 20, 21, 22, 23, 29

# ggml type id -> (elements per block, bytes per block)
GGML_BLOCK = {
    GGML_Q4_0: (32, 18),
    GGML_Q4_1: (32, 20),
    GGML_Q8_0: (32, 34),
    GGML_Q2_K: (256, 84),
    GGML_Q3_K: (256, 110),
    GGML_Q4_K: (256, 144),
    GGML_Q5_K: (256, 176),
    GGML_Q6_K: (256, 210),
    GGML_IQ2_XXS: (256, 66),
    GGML_IQ2_XS: (256, 74),
    GGML_IQ3_XXS: (256, 98),
    GGML_IQ1_S: (256, 50),
    GGML_IQ4_NL: (32, 18),
    GGML_IQ3_S: (256, 110),
    GGML_IQ2_S: (256, 82),
    GGML_IQ4_XS: (256, 136),
    GGML_IQ1_M: (256, 56),
}


def row_bytes(ggml_type: int, in_features: int) -> int:
    block_elems, block_bytes = GGML_BLOCK[ggml_type]
    return in_features // block_elems * block_bytes


# ggml type id -> its name, for messages
GGML_NAME = {
    GGML_Q4_0: "Q4_0",
    GGML_Q4_1: "Q4_1",
    GGML_Q8_0: "Q8_0",
    GGML_Q2_K: "Q2_K",
    GGML_Q3_K: "Q3_K",
    GGML_Q4_K: "Q4_K",
    GGML_Q5_K: "Q5_K",
    GGML_Q6_K: "Q6_K",
    GGML_IQ2_XXS: "IQ2_XXS",
    GGML_IQ2_XS: "IQ2_XS",
    GGML_IQ3_XXS: "IQ3_XXS",
    GGML_IQ1_S: "IQ1_S",
    GGML_IQ4_NL: "IQ4_NL",
    GGML_IQ3_S: "IQ3_S",
    GGML_IQ2_S: "IQ2_S",
    GGML_IQ4_XS: "IQ4_XS",
    GGML_IQ1_M: "IQ1_M",
}

# The 16 levels an IQ4 nibble indexes, shared by IQ4_NL and IQ4_XS (ggml's `kvalues_iq4nl`).
_IQ4_LEVELS = (-127, -104, -83, -65, -49, -35, -22, -10, 1, 13, 25, 38, 53, 69, 89, 113)


def dequantize(data: torch.Tensor, ggml_type: int, dtype: torch.dtype = torch.float32) -> torch.Tensor:
    """Flat `uint8` GGUF bytes -> flat values of `dtype`."""
    if ggml_type not in GGML_BLOCK:
        supported = ", ".join(f"{name} ({type_id})" for type_id, name in sorted(GGML_NAME.items()))
        raise ValueError(f"ggml type {ggml_type} is not supported yet. Supported quantized types: {supported}.")
    block_elems, block_bytes = GGML_BLOCK[ggml_type]
    blocks = data.reshape(-1, block_bytes)
    values = _DEQUANT[ggml_type](blocks, dtype)
    return values.reshape(-1)[: blocks.shape[0] * block_elems]


def _half(blocks: torch.Tensor, start: int, dtype: torch.dtype = torch.float32) -> torch.Tensor:
    """Read one fp16 scalar per block, as `(nb, 1)` of `dtype`."""
    return blocks[:, start : start + 2].view(torch.float16).to(dtype)


def _k_scales(scales: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Unpack the 12 bytes of 6-bit scales/mins shared by Q4_K and Q5_K (ggml's get_scale_min_k4)."""
    # stays in `uint8`: the six-bit fields never overflow it, and promoting first costs a copy
    scale = torch.cat([scales[:, :4] & 63, (scales[:, 8:12] & 0xF) | ((scales[:, 0:4] >> 6) << 4)], dim=1)
    minimum = torch.cat([scales[:, 4:8] & 63, (scales[:, 8:12] >> 4) | ((scales[:, 4:8] >> 6) << 4)], dim=1)
    return scale.float(), minimum.float()


def _shifted(data: torch.Tensor, shifts: tuple[int, ...], width: int) -> torch.Tensor:
    """`data` read as fields of `len(shifts)` per byte: (nb, n, 1, width) >> shifts -> (nb, -1, width)."""
    shift = torch.tensor(shifts, device=data.device, dtype=torch.uint8).reshape(1, 1, -1, 1)
    return (data.reshape(data.shape[0], -1, 1, width) >> shift).reshape(data.shape[0], -1, width)


def _iq4_levels(nibbles: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    """Nibbles -> the levels they index."""
    # built in the target dtype: gathering int8 and casting afterwards materializes the result twice
    levels = torch.tensor(_IQ4_LEVELS, device=nibbles.device, dtype=dtype)
    return levels[nibbles.long()]


def _dequant_q8_0(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    return _half(blocks, 0, dtype) * blocks[:, 2:34].view(torch.int8)


def _dequant_q4_k(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    d, dmin = _half(blocks, 0), _half(blocks, 2)
    scale, minimum = _k_scales(blocks[:, 4:16])
    q = _shifted(blocks[:, 16:144], (0, 4), 32) & 0xF
    return (d * scale).to(dtype)[..., None] * q - (dmin * minimum).to(dtype)[..., None]


def _dequant_q5_k(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    d, dmin = _half(blocks, 0), _half(blocks, 2)
    scale, minimum = _k_scales(blocks[:, 4:16])
    # the fifth bit of each value lives in its own plane, one bit per byte
    low = _shifted(blocks[:, 48:176], (0, 4), 32) & 0xF
    high = _shifted(blocks[:, 16:48], tuple(range(8)), 32) & 1
    q = low | (high << 4)
    return (d * scale).to(dtype)[..., None] * q - (dmin * minimum).to(dtype)[..., None]


def _dequant_q6_k(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    nb = blocks.shape[0]
    ql, qh, scales = blocks[:, 0:128], blocks[:, 128:192], blocks[:, 192:208]
    # 16 values share a scale, and the six bits of a quant are split four low and two high
    scale = (_half(blocks, 208) * scales.view(torch.int8).float()).to(dtype).reshape(nb, 16, 1)
    low = (_shifted(ql, (0, 4), 64) & 0xF).reshape(nb, -1, 32)
    high = (_shifted(qh, (0, 2, 4, 6), 32) & 3).reshape(nb, -1, 32)
    quants = (low | (high << 4)).to(torch.int8) - 32
    return (scale * quants.reshape(nb, 16, -1)).reshape(nb, -1)


def _dequant_q4_0(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    nibbles = _shifted(blocks[:, 2:18], (0, 4), 16).reshape(-1, 32) & 0xF
    return _half(blocks, 0, dtype) * (nibbles.to(torch.int8) - 8)


def _dequant_q4_1(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    nibbles = _shifted(blocks[:, 4:20], (0, 4), 16).reshape(-1, 32) & 0xF
    return _half(blocks, 0, dtype) * nibbles + _half(blocks, 2, dtype)


def _dequant_q2_k(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    scales, qs = blocks[:, 0:16], blocks[:, 16:80]
    d, dmin = _half(blocks, 80, dtype), _half(blocks, 82, dtype)
    # one byte per group of 16: a four-bit scale low, a four-bit minimum high
    dl = (d * (scales & 0xF).to(dtype)).reshape(-1, 16, 1)
    ml = (dmin * (scales >> 4).to(dtype)).reshape(-1, 16, 1)
    q = _shifted(qs, (0, 2, 4, 6), 32).reshape(-1, 16, 16) & 3
    return (dl * q - ml).reshape(blocks.shape[0], -1)


def _dequant_q3_k(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    d = _half(blocks, 108)
    hmask, qs, scales = blocks[:, 0:32], blocks[:, 32:96], blocks[:, 96:108]
    # 16 six-bit scales, low nibbles in the first 8 bytes and high pairs in the last 4
    low = _shifted(scales[:, :8], (0, 4), 8).reshape(-1, 16)
    high = _shifted(scales[:, 8:12], (0, 2, 4, 6), 4).reshape(-1, 16)
    scale = (((low & 0xF) | ((high & 3) << 4)).to(torch.int8).float() - 32).to(dtype)

    ql = _shifted(qs, (0, 2, 4, 6), 32).reshape(-1, 16, 16) & 3
    # the high bit is an inverted borrow: the offset applies where the mask bit is clear
    qh = (_shifted(hmask, tuple(range(8)), 32).reshape(-1, 16, 16) & 1) ^ 1
    q = ql.to(torch.int8) - (qh << 2).to(torch.int8)
    return ((d.to(dtype) * scale)[..., None] * q).reshape(blocks.shape[0], -1)


def _dequant_iq4_nl(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    nibbles = _shifted(blocks[:, 2:18], (0, 4), 16).reshape(-1, 32) & 0xF
    return _half(blocks, 0, dtype) * _iq4_levels(nibbles, dtype)


def _dequant_iq4_xs(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    d = _half(blocks, 0)
    scales_h = blocks[:, 2:4].view(torch.int16).to(torch.int32) & 0xFFFF
    # eight six-bit scales: four bytes of low nibbles here, low then high *within* each byte, with
    # their top two bits spread across one uint16
    shift = torch.tensor((0, 4), device=blocks.device, dtype=torch.uint8).reshape(1, 1, 2)
    low = (blocks[:, 4:8].reshape(-1, 4, 1) >> shift).reshape(-1, 8) & 0xF
    shift = torch.arange(0, 16, 2, device=blocks.device, dtype=torch.int32).reshape(1, 8)
    high = ((scales_h >> shift) & 3).to(torch.uint8)
    scale = ((low | (high << 4)).to(torch.int8).float() - 32).to(dtype)

    nibbles = _shifted(blocks[:, 8:136], (0, 4), 16).reshape(-1, 8, 32) & 0xF
    return ((d.to(dtype) * scale)[..., None] * _iq4_levels(nibbles, dtype)).reshape(blocks.shape[0], -1)


# The fixed codebooks the IQ types index. An IQ block stores indices rather than values: each names a
# point in a table of 4- or 8-value vectors shared by every file of that type. Transcribed from ggml's
# `ggml-common.h` in the same packing -- `GRID_SPECS[name]` is `(levels, shape, hex)`, two hexadecimal
# digits per byte and `8 // ceil(log2(len(levels)))` indices per byte. IQ1_S and IQ1_M share a table.
# ggml's `ksigns_iq2xs`: a seven-bit index -> the eight sign bits it stands for.
KSIGNS = bytes.fromhex(
    "REDACTED_MISTRAL"
    "REDACTED_MISTRAL"
    "REDACTED_MISTRAL"
    "REDACTED_MISTRAL"
)


GRID_SPECS = {
    "IQ2_XXS": (
        (8, 25, 43),
        (256, 8),
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL",
    ),
    "IQ2_XS": (
        (8, 25, 43),
        (512, 8),
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL",
    ),
    "IQ2_S": (
        (8, 25, 43),
        (1024, 8),
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL",
    ),
    "IQ3_XXS": (
        (4, 12, 20, 28, 36, 44, 52, 62),
        (256, 4),
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL",
    ),
    "IQ3_S": (
        (1, 3, 5, 7, 9, 11, 13, 15),
        (512, 4),
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL",
    ),
    "IQ1": (
        (-1, 0, 1),
        (2048, 8),
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL"
        b"REDACTED_MISTRAL",
    ),
}


# The offset an IQ1 index carries, ggml's `IQ1S_DELTA` and `IQ1M_DELTA`.
_IQ1_DELTA = 0.125

_GRIDS: dict[tuple[str, torch.device], torch.Tensor] = {}
_SIGN_TABLES: dict[torch.device, torch.Tensor] = {}


def _grid(name: str, device: torch.device) -> torch.Tensor:
    """One of `GRID_SPECS`, unpacked to its `(points, width)` of levels."""
    if (name, device) not in _GRIDS:
        levels, shape, packed = GRID_SPECS[name]
        bits = (len(levels) - 1).bit_length()
        per_byte = 8 // bits
        digits = torch.tensor(list(packed), dtype=torch.uint8, device=device).reshape(-1, 2)
        nibbles = torch.where(digits > 0x40, digits + 9, digits) & 0x0F
        byte = (nibbles[:, 0] << 4) | nibbles[:, 1]
        shift = torch.tensor(tuple(range(0, 8, 8 // per_byte)), dtype=torch.uint8, device=device)
        index = ((byte.reshape(-1, 1) >> shift.reshape(1, per_byte)) & ((1 << bits) - 1)).reshape(-1)
        _GRIDS[(name, device)] = torch.tensor(levels, dtype=torch.float32, device=device)[index.long()].reshape(shape)
    return _GRIDS[(name, device)]


def _bits(packed: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    """Bytes -> the eight signs each stands for, as `(..., 8)` of 1 or -1."""
    bit = torch.arange(8, device=packed.device, dtype=torch.uint8)
    return torch.where((packed.unsqueeze(-1) >> bit) & 1 == 0, 1.0, -1.0).to(dtype)


def _signs_of(index: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    """Seven-bit sign indices -> the signs `ksigns_iq2xs` maps them to."""
    if index.device not in _SIGN_TABLES:
        _SIGN_TABLES[index.device] = torch.tensor(list(KSIGNS), dtype=torch.uint8, device=index.device)
    return _bits(_SIGN_TABLES[index.device][index.long()], dtype)


def _words(data: torch.Tensor, width: int) -> torch.Tensor:
    """`(nb, n * width)` bytes -> `(nb, n)`, each `width` bytes read little-endian."""
    parts = data.reshape(data.shape[0], -1, width).long()
    out = parts[..., 0]
    for byte in range(1, width):
        out = out | (parts[..., byte] << (8 * byte))
    return out


def _shift_of(values: torch.Tensor, shifts: tuple[int, ...]) -> torch.Tensor:
    """`(nb, n)` -> `(nb, n * len(shifts))`, each value read at each shift."""
    shift = torch.tensor(shifts, device=values.device, dtype=values.dtype).reshape(1, 1, -1)
    return (values.unsqueeze(-1) >> shift).reshape(values.shape[0], -1)


def _dequant_iq2_xxs(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    d = _half(blocks, 0)
    words = _words(blocks[:, 2:66], 4).reshape(blocks.shape[0], -1, 2)
    aux, meta = words[..., 0], words[..., 1]
    db = (d * (0.5 + (meta >> 28).float()) * 0.25).to(dtype).reshape(blocks.shape[0], -1, 1, 1)
    sign = _signs_of(_shift_of(meta, (0, 7, 14, 21)) & 0x7F, dtype).reshape(blocks.shape[0], -1, 4, 8)
    points = _grid("IQ2_XXS", blocks.device)[(_shift_of(aux, (0, 8, 16, 24)) & 0xFF).long()]
    return (db * points.to(dtype).reshape(blocks.shape[0], -1, 4, 8) * sign).reshape(blocks.shape[0], -1)


def _dequant_iq2_xs(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    nb = blocks.shape[0]
    d = _half(blocks, 0)
    qs = _words(blocks[:, 2:66], 2)
    scale = (_shift_of(blocks[:, 66:74].long(), (0, 4)) & 0xF).float()
    db = (d * (0.5 + scale) * 0.25).to(dtype).reshape(nb, -1, 1, 1)
    sign = _signs_of(qs >> 9, dtype).reshape(nb, -1, 2, 8)
    points = _grid("IQ2_XS", blocks.device)[(qs & 511).long()].to(dtype).reshape(nb, -1, 2, 8)
    return (db * points * sign).reshape(nb, -1)


def _dequant_iq2_s(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    nb = blocks.shape[0]
    d = _half(blocks, 0)
    scale = (_shift_of(blocks[:, 74:82].long(), (0, 4)) & 0xF).float()
    db = (d * (0.5 + scale) * 0.25).to(dtype).reshape(nb, -1, 1, 1)
    sign = _bits(blocks[:, 34:66], dtype).reshape(nb, -1, 2, 8)
    high = _shift_of(blocks[:, 66:74].long(), (0, 2, 4, 6)) & 3
    points = _grid("IQ2_S", blocks.device)[(blocks[:, 2:34].long() | (high << 8)).long()]
    return (db * points.to(dtype).reshape(nb, -1, 2, 8) * sign).reshape(nb, -1)


def _dequant_iq3_xxs(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    nb = blocks.shape[0]
    d = _half(blocks, 0)
    meta = _words(blocks[:, 66:98], 4)
    db = (d * (0.5 + (meta >> 28).float()) * 0.5).to(dtype).reshape(nb, -1, 1, 1)
    sign = _signs_of(_shift_of(meta, (0, 7, 14, 21)) & 0x7F, dtype).reshape(nb, -1, 4, 8)
    points = _grid("IQ3_XXS", blocks.device)[blocks[:, 2:66].long()].to(dtype).reshape(nb, -1, 4, 8)
    return (db * points * sign).reshape(nb, -1)


def _dequant_iq1_s(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    nb = blocks.shape[0]
    d = _half(blocks, 0)
    qh = _words(blocks[:, 34:50], 2)
    dl = (d * (2 * ((qh >> 12) & 7) + 1).float()).to(dtype).reshape(nb, -1, 1, 1)
    delta = torch.where(qh & 0x8000 == 0, _IQ1_DELTA, -_IQ1_DELTA).to(dtype).reshape(nb, -1, 1, 1)
    index = blocks[:, 2:34].long() | ((_shift_of(qh, (0, 3, 6, 9)) & 7) << 8)
    points = _grid("IQ1", blocks.device)[index].to(dtype).reshape(nb, -1, 4, 8)
    return (dl * (points + delta)).reshape(nb, -1)


def _dequant_iq1_m(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    nb = blocks.shape[0]
    packed = _words(blocks[:, 48:56], 2)
    # the fp16 scale is spread across the top nibble of all four scale words
    bits = (packed & 0xF000) >> torch.tensor([12, 8, 4, 0], device=blocks.device).reshape(1, 4)
    d = bits[:, 0] | bits[:, 1] | bits[:, 2] | bits[:, 3]
    d = d.to(torch.int16).view(torch.float16).float().reshape(nb, 1)
    scale = (_shift_of(packed, (0, 3, 6, 9)) & 7).float()
    dl = (d * (2 * scale + 1)).to(dtype).reshape(nb, -1, 2, 1, 1)

    qh = _shift_of(blocks[:, 32:48].long(), (0, 4))
    index = blocks[:, 0:32].long() | ((qh & 7) << 8)
    delta = torch.where(qh & 8 == 0, _IQ1_DELTA, -_IQ1_DELTA).to(dtype).reshape(nb, -1, 2, 2, 1)
    points = _grid("IQ1", blocks.device)[index].to(dtype).reshape(nb, -1, 2, 2, 8)
    return (dl * (points + delta)).reshape(nb, -1)


def _dequant_iq3_s(blocks: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    nb = blocks.shape[0]
    d = _half(blocks, 0)
    qs, qh, signs, scales = blocks[:, 2:66], blocks[:, 66:74], blocks[:, 74:106], blocks[:, 106:110]

    # four bytes hold eight four-bit scales, low then high nibble within each byte
    shift4 = torch.tensor((0, 4), device=blocks.device, dtype=torch.uint8).reshape(1, 1, 2)
    scale = ((scales.reshape(nb, -1, 1) >> shift4) & 0xF).reshape(nb, -1).float()
    db = (d * (1 + 2 * scale)).to(dtype).reshape(nb, -1, 1, 1)

    bit = torch.arange(8, device=blocks.device, dtype=torch.uint8).reshape(1, 1, 8)
    sign = torch.where((signs.reshape(nb, -1, 1) >> bit) & 1 == 0, 1.0, -1.0).to(dtype).reshape(nb, -1, 4, 8)

    high = ((qh.reshape(nb, -1, 1) >> bit) & 1).reshape(nb, -1).int()
    index = qs.int() | (high << 8)
    points = _grid("IQ3_S", blocks.device)[index.reshape(-1).long()].to(dtype).reshape(nb, -1, 4, 8)
    return (db * points * sign).reshape(nb, -1)


_DEQUANT = {
    GGML_Q4_0: _dequant_q4_0,
    GGML_Q4_1: _dequant_q4_1,
    GGML_Q8_0: _dequant_q8_0,
    GGML_Q2_K: _dequant_q2_k,
    GGML_Q3_K: _dequant_q3_k,
    GGML_Q4_K: _dequant_q4_k,
    GGML_Q5_K: _dequant_q5_k,
    GGML_Q6_K: _dequant_q6_k,
    GGML_IQ2_XXS: _dequant_iq2_xxs,
    GGML_IQ2_XS: _dequant_iq2_xs,
    GGML_IQ3_XXS: _dequant_iq3_xxs,
    GGML_IQ1_S: _dequant_iq1_s,
    GGML_IQ4_NL: _dequant_iq4_nl,
    GGML_IQ3_S: _dequant_iq3_s,
    GGML_IQ2_S: _dequant_iq2_s,
    GGML_IQ1_M: _dequant_iq1_m,
    GGML_IQ4_XS: _dequant_iq4_xs,
}
