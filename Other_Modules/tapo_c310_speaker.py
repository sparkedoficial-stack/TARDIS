#!/usr/bin/env python3
"""
core/tapo_c310_speaker.py - Emisor Vocal Bidireccional TARDIS para TP-Link Tapo C310
====================================================================================
Implementa el canal de retorno de audio (two-way talkback :8800 multipart/mixed + MPEG-TS
StreamTypePCMATapo 0x90 @ 8000 Hz G.711 A-law) con reloj PTS exacto a 90 kHz (1800 ticks
por trama de 20 ms / 160 bytes = 1 paquete TS de 188 bytes por fragmento) y cola de
silencio de drenaje (1.55 s) para evitar cortes al final de la locución en el buffer DSP
de la cámara.

Incluye síntesis neuronal TARDIS (es-MX-DaliaNeural vía edge-tts), ecualización y
compresión dinámica optimizada para altavoz exterior IP, caché atómica en disco para
latencia <100 ms sin dependencia de red en alertas repetidas y exclusión mutua inter-proceso.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import logging
import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from pytapo import Tapo
from pytapo.media_stream._utils import (
    generate_nonce,
    parse_http_headers,
    parse_http_response,
)

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

DEFAULT_CONFIG_PATH = BASE_DIR / "tapo_c310_config.json"
TTS_CACHE_DIR = BASE_DIR / "data" / "tapo_c310_detections" / "tts_cache"
SPEAKER_LOCK_FILE = Path("/tmp/tardis_tapo_c310_speaker.lock")

DEFAULT_VOICE = "es-MX-DaliaNeural"
DEFAULT_WARNING_MESSAGE = (
    "Estás bajo vigilancia del sistema tardis, dios digital del universo, al momento de acercarte a la propiedad capturaremos tus datos biométricos"
)

# Tabla CRC-32 reflejada empleada por el demuxer MPEG-TS del firmware Tapo (streamd)
_MPEGTS_CRC_TABLE = (
    0x00000000, 0xB71DC104, 0x6E3B8209, 0xD926430D, 0xDC760413, 0x6B6BC517,
    0xB24D861A, 0x0550471E, 0xB8ED0826, 0x0FF0C922, 0xD6D68A2F, 0x61CB4B2B,
    0x649B0C35, 0xD386CD31, 0x0AA08E3C, 0xBDBD4F38, 0x70DB114C, 0xC7C6D048,
    0x1EE09345, 0xA9FD5241, 0xACAD155F, 0x1BB0D45B, 0xC2969756, 0x758B5652,
    0xC836196A, 0x7F2BD86E, 0xA60D9B63, 0x11105A67, 0x14401D79, 0xA35DDC7D,
    0x7A7B9F70, 0xCD665E74, 0xE0B62398, 0x57ABE29C, 0x8E8DA191, 0x39906095,
    0x3CC0278B, 0x8BDDE68F, 0x52FBA582, 0xE5E66486, 0x585B2BBE, 0xEF46EABA,
    0x3660A9B7, 0x817D68B3, 0x842D2FAD, 0x3330EEA9, 0xEA16ADA4, 0x5D0B6CA0,
    0x906D32D4, 0x2770F3D0, 0xFE56B0DD, 0x494B71D9, 0x4C1B36C7, 0xFB06F7C3,
    0x2220B4CE, 0x953D75CA, 0x28803AF2, 0x9F9DFBF6, 0x46BBB8FB, 0xF1A679FF,
    0xF4F63EE1, 0x43EBFFE5, 0x9ACDBCE8, 0x2DD07DEC, 0x77708634, 0xC06D4730,
    0x194B043D, 0xAE56C539, 0xAB068227, 0x1C1B4323, 0xC53D002E, 0x7220C12A,
    0xCF9D8E12, 0x78804F16, 0xA1A60C1B, 0x16BBCD1F, 0x13EB8A01, 0xA4F64B05,
    0x7DD00808, 0xCACDC90C, 0x07AB9778, 0xB0B6567C, 0x69901571, 0xDE8DD475,
    0xDBDD936B, 0x6CC0526F, 0xB5E61162, 0x02FBD066, 0xBF469F5E, 0x085B5E5A,
    0xD17D1D57, 0x6660DC53, 0x63309B4D, 0xD42D5A49, 0x0D0B1944, 0xBA16D840,
    0x97C6A5AC, 0x20DB64A8, 0xF9FD27A5, 0x4EE0E6A1, 0x4BB0A1BF, 0xFCAD60BB,
    0x258B23B6, 0x9296E2B2, 0x2F2BAD8A, 0x98366C8E, 0x41102F83, 0xF60DEE87,
    0xF35DA999, 0x4440689D, 0x9D662B90, 0x2A7BEA94, 0xE71DB4E0, 0x500075E4,
    0x892636E9, 0x3E3BF7ED, 0x3B6BB0F3, 0x8C7671F7, 0x555032FA, 0xE24DF3FE,
    0x5FF0BCC6, 0xE8ED7DC2, 0x31CB3ECF, 0x86D6FFCB, 0x8386B8D5, 0x349B79D1,
    0xEDBD3ADC, 0x5AA0FBD8, 0xEEE00C69, 0x59FDCD6D, 0x80DB8E60, 0x37C64F64,
    0x3296087A, 0x858BC97E, 0x5CAD8A73, 0xEBB04B77, 0x560D044F, 0xE110C54B,
    0x38368646, 0x8F2B4742, 0x8A7B005C, 0x3D66C158, 0xE4408255, 0x535D4351,
    0x9E3B1D25, 0x2926DC21, 0xF0009F2C, 0x471D5E28, 0x424D1936, 0xF550D832,
    0x2C769B3F, 0x9B6B5A3B, 0x26D61503, 0x91CBD407, 0x48ED970A, 0xFFF0560E,
    0xFAA01110, 0x4DBDD014, 0x949B9319, 0x2386521D, 0x0E562FF1, 0xB94BEEF5,
    0x606DADF8, 0xD7706CFC, 0xD2202BE2, 0x653DEAE6, 0xBC1BA9EB, 0x0B0668EF,
    0xB6BB27D7, 0x01A6E6D3, 0xD880A5DE, 0x6F9D64DA, 0x6ACD23C4, 0xDDD0E2C0,
    0x04F6A1CD, 0xB3EB60C9, 0x7E8D3EBD, 0xC990FFB9, 0x10B6BCB4, 0xA7AB7DB0,
    0xA2FB3AAE, 0x15E6FBAA, 0xCCC0B8A7, 0x7BDD79A3, 0xC660369B, 0x717DF79F,
    0xA85BB492, 0x1F467596, 0x1A163288, 0xAD0BF38C, 0x742DB081, 0xC3307185,
    0x99908A5D, 0x2E8D4B59, 0xF7AB0854, 0x40B6C950, 0x45E68E4E, 0xF2FB4F4A,
    0x2BDD0C47, 0x9CC0CD43, 0x217D827B, 0x9660437F, 0x4F460072, 0xF85BC176,
    0xFD0B8668, 0x4A16476C, 0x93300461, 0x242DC565, 0xE94B9B11, 0x5E565A15,
    0x87701918, 0x306DD81C, 0x353D9F02, 0x82205E06, 0x5B061D0B, 0xEC1BDC0F,
    0x51A69337, 0xE6BB5233, 0x3F9D113E, 0x8880D03A, 0x8DD09724, 0x3ACD5620,
    0xE3EB152D, 0x54F6D429, 0x7926A9C5, 0xCE3B68C1, 0x171D2BCC, 0xA000EAC8,
    0xA550ADD6, 0x124D6CD2, 0xCB6B2FDF, 0x7C76EEDB, 0xC1CBA1E3, 0x76D660E7,
    0xAFF023EA, 0x18EDE2EE, 0x1DBDA5F0, 0xAAA064F4, 0x738627F9, 0xC49BE6FD,
    0x09FDB889, 0xBEE0798D, 0x67C63A80, 0xD0DBFB84, 0xD58BBC9A, 0x62967D9E,
    0xBBB03E93, 0x0CADFF97, 0xB110B0AF, 0x060D71AB, 0xDF2B32A6, 0x6836F3A2,
    0x6D66B4BC, 0xDA7B75B8, 0x035D36B5, 0xB440F7B1,
)

logger = logging.getLogger("TARDIS.TapoC310Speaker")
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


def _mpegts_crc32_le(data: bytes) -> bytes:
    crc = 0xFFFFFFFF
    for b in data:
        crc = _MPEGTS_CRC_TABLE[(b ^ (crc & 0xFF)) & 0xFF] ^ (crc >> 8)
    return struct.pack("<I", crc & 0xFFFFFFFF)


class TapoMpegTsMuxer:
    """Muxer MPEG-TS ligero compatible con streamd :8800 de cámaras TP-Link Tapo."""

    PACKET_SIZE = 188
    PAT_PID = 0x0000
    PMT_PID = 0x1000
    PES_PID = 0x0100
    STREAM_TYPE_PCMA_TAPO = 0x90  # G.711 A-law @ 8000 Hz mono

    def __init__(self, stream_type: int = STREAM_TYPE_PCMA_TAPO) -> None:
        self.stream_type = int(stream_type)
        self.continuity_counter = 0
        self.pts_90k = 90000  # Inicia en 1.0 s sobre reloj de 90 kHz

    def get_header(self) -> bytes:
        """Retorna las tablas PAT + PMT (376 bytes = 2 celdas TS de 188 bytes)."""
        pat = bytearray([0x47, 0x40, 0x00, 0x10, 0x00])
        pat_psi = bytearray(
            [
                0x00,
                0xB0,
                0x0D,
                0x00,
                0x01,
                0xC1,
                0x00,
                0x00,
                0x00,
                0x01,
                0xE0 | ((self.PMT_PID >> 8) & 0x1F),
                self.PMT_PID & 0xFF,
            ]
        )
        pat.extend(pat_psi)
        pat.extend(_mpegts_crc32_le(pat_psi))
        pat.extend(b"\x00" * (self.PACKET_SIZE - len(pat)))

        pmt = bytearray(
            [
                0x47,
                0x40 | ((self.PMT_PID >> 8) & 0x1F),
                self.PMT_PID & 0xFF,
                0x10,
                0x00,
            ]
        )
        pmt_psi = bytearray(
            [
                0x02,
                0xB0,
                0x12,
                0x00,
                0x01,
                0xC1,
                0x00,
                0x00,
                0xFF,
                0xFF,
                0xF0,
                0x00,
                self.stream_type,
                0xE0 | ((self.PES_PID >> 8) & 0x1F),
                self.PES_PID & 0xFF,
                0xF0,
                0x00,
            ]
        )
        pmt.extend(pmt_psi)
        pmt.extend(_mpegts_crc32_le(pmt_psi))
        pmt.extend(b"\x00" * (self.PACKET_SIZE - len(pmt)))
        return bytes(pat + pmt)

    @staticmethod
    def _encode_pts(pts: int) -> bytes:
        pts &= (1 << 33) - 1
        return bytes(
            [
                0x21 | ((pts >> 29) & 0x0E),
                (pts >> 22) & 0xFF,
                0x01 | ((pts >> 14) & 0xFE),
                (pts >> 7) & 0xFF,
                0x01 | ((pts << 1) & 0xFE),
            ]
        )

    def encode_pcma_20ms_frame(self, pcma_160b: bytes, pts_step_90k: int = 1800) -> bytes:
        """
        Empaqueta una trama de 20 ms (160 bytes PCMA @ 8 kHz) en una única celda TS de 188 bytes
        avanzando el reloj PTS exactamente 1800 ticks (90 kHz * 0.020 s).
        """
        pes_len = 3 + 5 + len(pcma_160b)
        pes_hdr = bytearray(
            [
                0x00,
                0x00,
                0x01,
                0xC0,
                (pes_len >> 8) & 0xFF,
                pes_len & 0xFF,
                0x80,
                0x80,
                0x05,
            ]
        )
        pes_hdr.extend(self._encode_pts(self.pts_90k))
        self.pts_90k = (self.pts_90k + pts_step_90k) & ((1 << 33) - 1)

        rem = memoryview(bytes(pes_hdr) + pcma_160b)
        out = bytearray()
        first = True
        while len(rem) > 0:
            pid_word = (0x4000 | self.PES_PID) if first else self.PES_PID
            first = False
            cc = self.continuity_counter & 0x0F
            self.continuity_counter = (self.continuity_counter + 1) & 0x0F

            pkt = bytearray([0x47, (pid_word >> 8) & 0xFF, pid_word & 0xFF])
            if len(rem) < 184:
                pkt.append(0x30 | cc)
                ad_size = 184 - 1 - len(rem)
                pkt.append(ad_size)
                if ad_size > 0:
                    pkt.extend(b"\x00" * ad_size)
                pkt.extend(rem)
                rem = rem[len(rem) :]
            else:
                pkt.append(0x10 | cc)
                pkt.extend(rem[:184])
                rem = rem[184:]
            out.extend(pkt)
        return bytes(out)


class TapoC310Speaker:
    """Controlador asíncrono de síntesis y emisión de voz sobre el altavoz de Tapo C310."""

    SAMPLE_RATE = 8000
    FRAME_BYTES = 160  # 20 ms @ 8000 Hz (1 paquete TS de 188 bytes por fragmento HTTP)
    FRAME_DURATION_SEC = 0.020
    PTS_STEP_90K = 1800  # 90000 Hz * 0.020 s
    ALAW_SILENCE_BYTE = b"\xd5"
    TAIL_PAD_SEC = 1.55  # Drenaje completo del buffer hardware de la cámara antes de cerrar socket

    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
        self.config_path = config_path
        self.config = self._load_json(config_path)
        TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        self.host: str = str(self.config.get("host", "REDACTED_IP")).strip()
        self.port: int = int(self.config.get("media_port", 8800))
        self.tapo_user: str = str(self.config.get("tapo_user", "admin"))
        self.account_email: str = str(self.config.get("account_email", ""))
        self.password: str = str(self.config.get("password", ""))
        self.voice: str = str(self.config.get("speaker_voice", DEFAULT_VOICE))
        self.rate: str = str(self.config.get("speaker_rate", "+0%"))
        self.pitch: str = str(self.config.get("speaker_pitch", "+0Hz"))
        self.volume: int = max(1, min(100, int(self.config.get("speaker_volume", 100))))
        self.default_message: str = str(
            self.config.get("new_person_voice_message", DEFAULT_WARNING_MESSAGE)
        ).strip() or DEFAULT_WARNING_MESSAGE

        self._async_lock = asyncio.Lock()
        self._volume_verified = False

    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def reload_config(self) -> None:
        cfg = self._load_json(self.config_path)
        if not cfg:
            return
        self.config = cfg
        self.host = str(cfg.get("host", self.host)).strip()
        self.voice = str(cfg.get("speaker_voice", self.voice))
        self.rate = str(cfg.get("speaker_rate", self.rate))
        self.pitch = str(cfg.get("speaker_pitch", self.pitch))
        self.volume = max(1, min(100, int(cfg.get("speaker_volume", self.volume))))
        self.default_message = (
            str(cfg.get("new_person_voice_message", self.default_message)).strip()
            or DEFAULT_WARNING_MESSAGE
        )

    def _ensure_speaker_unmuted_sync(self) -> None:
        """Garantiza por API :443 que el altavoz físico de la C310 esté sin mute y al volumen objetivo."""
        candidates = []
        if self.account_email:
            candidates.append(self.account_email)
        if self.tapo_user and self.tapo_user not in candidates:
            candidates.append(self.tapo_user)
        if "admin" not in candidates:
            candidates.append("admin")

        for user in candidates:
            try:
                tapo = Tapo(self.host, user, self.password, cloudPassword=self.password)
                acfg = tapo.getAudioConfig()
                spk = acfg.get("audio_config", {}).get("speaker", {})
                cur_vol = str(spk.get("volume", ""))
                cur_mute = str(spk.get("mute", "off")).lower()
                if cur_mute == "on" or cur_vol != str(self.volume):
                    tapo.executeFunction(
                        "setSpeakerVolume",
                        {
                            "method": "set",
                            "audio_config": {
                                "speaker": {
                                    "volume": str(self.volume),
                                    "mute": "off",
                                }
                            },
                        },
                    )
                self._volume_verified = True
                return
            except Exception as exc:
                logger.debug(f"Ajuste de volumen en {self.host} con {user} omitido: {exc}")

    def _cache_paths_for(self, text: str, voice: str, rate: str, pitch: str) -> Tuple[Path, Path]:
        key_raw = json.dumps(
            {
                "v": 2,
                "text": text.strip(),
                "voice": voice,
                "rate": rate,
                "pitch": pitch,
                "pad": self.TAIL_PAD_SEC,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        digest = hashlib.sha256(key_raw.encode("utf-8")).hexdigest()[:24]
        return TTS_CACHE_DIR / f"{digest}.alaw", TTS_CACHE_DIR / f"{digest}.json"

    async def synthesize_pcma_cached(
        self,
        text: str,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
    ) -> Tuple[bytes, bool]:
        """
        Sintetiza `text` a G.711 A-law 8000 Hz mono masterizado para altavoz exterior,
        incluyendo 1.55 s de cola de silencio para evitar truncamiento en cámara.
        Retorna (pcma_bytes, from_cache).
        """
        clean_text = " ".join(text.strip().split())
        if not clean_text:
            raise ValueError("El texto a pronunciar por la cámara está vacío.")

        v_id = voice or self.voice
        v_rate = rate or self.rate
        v_pitch = pitch or self.pitch
        alaw_cache, meta_cache = self._cache_paths_for(clean_text, v_id, v_rate, v_pitch)

        if alaw_cache.is_file() and alaw_cache.stat().st_size > self.FRAME_BYTES * 5:
            return alaw_cache.read_bytes(), True

        import edge_tts

        with tempfile.TemporaryDirectory(prefix="tardis_c310_tts_") as tmpdir:
            mp3_tmp = Path(tmpdir) / "speech.mp3"
            alaw_tmp = Path(tmpdir) / "speech.alaw"

            comm = edge_tts.Communicate(clean_text, v_id, rate=v_rate, pitch=v_pitch)
            await asyncio.wait_for(comm.save(str(mp3_tmp)), timeout=20.0)

            af_chain = (
                "highpass=f=210,"
                "lowpass=f=3650,"
                "acompressor=threshold=-18dB:ratio=3.2:attack=5:release=80:makeup=5.5dB,"
                "alimiter=limit=0.96,"
                f"apad=pad_dur={self.TAIL_PAD_SEC:.2f}"
            )

            loop = asyncio.get_running_loop()

            def _transcode() -> bytes:
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-i",
                        str(mp3_tmp),
                        "-af",
                        af_chain,
                        "-ac",
                        "1",
                        "-ar",
                        str(self.SAMPLE_RATE),
                        "-f",
                        "alaw",
                        str(alaw_tmp),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    check=True,
                )
                raw = alaw_tmp.read_bytes()
                rem = len(raw) % self.FRAME_BYTES
                if rem:
                    raw += self.ALAW_SILENCE_BYTE * (self.FRAME_BYTES - rem)
                return raw

            pcma_bytes = await loop.run_in_executor(None, _transcode)

        # Escritura atómica en caché persistente
        tmp_dest = alaw_cache.with_suffix(".alaw.tmp")
        tmp_dest.write_bytes(pcma_bytes)
        os.replace(tmp_dest, alaw_cache)
        try:
            meta_cache.write_text(
                json.dumps(
                    {
                        "text": clean_text,
                        "voice": v_id,
                        "rate": v_rate,
                        "pitch": v_pitch,
                        "bytes": len(pcma_bytes),
                        "duration_sec": round(len(pcma_bytes) / self.SAMPLE_RATE, 2),
                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

        return pcma_bytes, False

    async def prewarm_default_phrase(self) -> Dict[str, Any]:
        """Pre-sintetiza y verifica la frase perimetral por defecto en disco."""
        self.reload_config()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._ensure_speaker_unmuted_sync)
        pcma, cached = await self.synthesize_pcma_cached(self.default_message)
        return {
            "ok": True,
            "cached": cached,
            "message": self.default_message,
            "voice": self.voice,
            "bytes": len(pcma),
            "duration_sec": round(len(pcma) / self.SAMPLE_RATE, 2),
        }

    async def _open_talk_channel(
        self, force_md5: bool = False
    ) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter, str]:
        """Negocia HTTP Digest + sesión JSON `talk` (`mode=aec`) sobre el puerto :8800."""
        boundary = "--client-stream-boundary--"
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout=6.0
        )

        async def _send_post(auth_header: Optional[str]) -> None:
            lines = [
                "POST /stream HTTP/1.1",
                f"Host: {self.host}:{self.port}",
                f"Content-Type: multipart/mixed; boundary={boundary}",
                "Connection: keep-alive",
                "Content-Length: -1",
            ]
            if auth_header:
                lines.append(f"Authorization: {auth_header}")
            writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
            await writer.drain()

        try:
            await _send_post(None)
            raw_chal = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
            res_line, hdr_block = raw_chal.split(b"\r\n", 1)
            _, _, _ = parse_http_response(res_line)
            hdrs = parse_http_headers(hdr_block)
            www_auth = hdrs.get("WWW-Authenticate", "")
            if not www_auth:
                raise RuntimeError("Cámara no entregó cabecera WWW-Authenticate en :8800")

            auth_map = {
                k.strip().replace('"', ""): v.strip().replace('"', "")
                for k, v in (
                    part.split("=", 1) for part in www_auth.split(" ", 1)[1].split(",")
                )
            }

            use_sha256 = (auth_map.get("encrypt_type") == "3") and not force_md5
            if use_sha256:
                pwd_hash = hashlib.sha256(self.password.encode("utf-8")).hexdigest().upper()
            else:
                pwd_hash = hashlib.md5(self.password.encode("utf-8")).hexdigest().upper()

            username = "admin"
            realm = auth_map["realm"]
            nonce = auth_map["nonce"]
            qop = auth_map.get("qop", "auth")
            opaque = auth_map.get("opaque", "")
            nc = "00000001"
            cnonce = generate_nonce(16).decode("ascii")

            ha1 = hashlib.md5(f"{username}:{realm}:{pwd_hash}".encode("ascii")).hexdigest()
            ha2 = hashlib.md5(b"POST:/stream").hexdigest()
            digest_resp = hashlib.md5(
                f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode("ascii")
            ).hexdigest()

            auth_str = (
                f'Digest username="{username}", realm="{realm}", nonce="{nonce}", '
                f'uri="/stream", algorithm=MD5, qop={qop}, nc={nc}, cnonce="{cnonce}", '
                f'response="{digest_resp}", opaque="{opaque}"'
            )

            await _send_post(auth_str)
            raw_ok = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
            res_line2, _ = raw_ok.split(b"\r\n", 1)
            _, status2, _ = parse_http_response(res_line2)
            if status2 == 401 and use_sha256:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                return await self._open_talk_channel(force_md5=True)
            if status2 != 200:
                raise RuntimeError(f"Autenticación talk :8800 rechazada con HTTP {status2}")

            talk_req = b'{"params":{"talk":{"mode":"aec"},"method":"get"},"seq":3,"type":"request"}'
            req_part = (
                f"----client-stream-boundary--\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(talk_req)}\r\n\r\n"
            ).encode("ascii") + talk_req + b"\r\n"
            writer.write(req_part)
            await writer.drain()

            await asyncio.wait_for(reader.readuntil(b"--device-stream-boundary--"), timeout=5.0)
            part_hdr_raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
            part_hdrs = parse_http_headers(part_hdr_raw)
            clen = int(part_hdrs["Content-Length"])
            body = await asyncio.wait_for(reader.readexactly(clen), timeout=5.0)
            resp_json = json.loads(body.decode("utf-8"))

            params = resp_json.get("params", {})
            err_code = int(params.get("error_code", -1))
            session_id = str(params.get("session_id", "")).strip()
            if err_code != 0 or not session_id:
                raise RuntimeError(f"Cámara rechazó sesión talk: {resp_json}")

            return reader, writer, session_id
        except Exception:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            raise

    @staticmethod
    async def _write_audio_part(
        writer: asyncio.StreamWriter, session_id: str, ts_payload: bytes
    ) -> None:
        header = (
            f"----client-stream-boundary--\r\n"
            f"Content-Type: audio/mp2t\r\n"
            f"X-If-Encrypt: 0\r\n"
            f"X-Session-Id: {session_id}\r\n"
            f"Content-Length: {len(ts_payload)}\r\n\r\n"
        ).encode("ascii")
        writer.write(header + ts_payload + b"\r\n")
        await writer.drain()

    async def _stream_pcma_to_camera(self, pcma_bytes: bytes) -> Dict[str, Any]:
        """Transmite el flujo PCMA @ 8 kHz sincronizado con reloj monotónico."""
        last_exc: Optional[Exception] = None
        for attempt in range(1, 4):
            reader: Optional[asyncio.StreamReader] = None
            writer: Optional[asyncio.StreamWriter] = None
            try:
                reader, writer, session_id = await self._open_talk_channel()
                muxer = TapoMpegTsMuxer(TapoMpegTsMuxer.STREAM_TYPE_PCMA_TAPO)
                await self._write_audio_part(writer, session_id, muxer.get_header())

                total_frames = len(pcma_bytes) // self.FRAME_BYTES
                t_start = time.perf_counter()
                for idx in range(total_frames):
                    off = idx * self.FRAME_BYTES
                    frame = pcma_bytes[off : off + self.FRAME_BYTES]
                    ts_cell = muxer.encode_pcma_20ms_frame(frame, self.PTS_STEP_90K)
                    await self._write_audio_part(writer, session_id, ts_cell)

                    target_time = t_start + (idx + 1) * self.FRAME_DURATION_SEC
                    sleep_sec = target_time - time.perf_counter()
                    if sleep_sec > 0.002:
                        await asyncio.sleep(sleep_sec)

                elapsed = time.perf_counter() - t_start
                return {
                    "ok": True,
                    "session_id": session_id,
                    "frames_sent": total_frames,
                    "stream_seconds": round(elapsed, 2),
                    "attempt": attempt,
                }
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    f"Intento {attempt}/3 de emisión en altavoz Tapo {self.host} falló: {exc}"
                )
                await asyncio.sleep(0.6 * attempt)
            finally:
                if writer is not None:
                    try:
                        writer.close()
                        await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
                    except Exception:
                        pass

        return {"ok": False, "error": str(last_exc)}

    async def speak(
        self,
        text: Optional[str] = None,
        voice: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Sintetiza (o recupera de caché) `text` y lo reproduce por la bocina física de la Tapo C310.
        Serializa llamadas concurrentes tanto intra-proceso como inter-proceso.
        """
        self.reload_config()
        if not self.config.get("speaker_enabled", True):
            return {"ok": False, "skipped": True, "reason": "speaker_enabled=false"}

        phrase = (text or self.default_message).strip()
        if not phrase:
            phrase = DEFAULT_WARNING_MESSAGE

        async with self._async_lock:
            loop = asyncio.get_running_loop()
            if not self._volume_verified:
                await loop.run_in_executor(None, self._ensure_speaker_unmuted_sync)

            t0 = time.perf_counter()
            pcma_bytes, from_cache = await self.synthesize_pcma_cached(phrase, voice=voice)
            synth_ms = (time.perf_counter() - t0) * 1000.0

            # Lock inter-proceso para evitar colisión si CLI/Telegram y Sentinel hablan a la vez
            lock_fd = os.open(str(SPEAKER_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o666)
            try:
                await loop.run_in_executor(None, fcntl.flock, lock_fd, fcntl.LOCK_EX)
                tx_res = await self._stream_pcma_to_camera(pcma_bytes)
            finally:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except Exception:
                    pass
                os.close(lock_fd)

            tx_res.update(
                {
                    "host": self.host,
                    "text": phrase,
                    "voice": voice or self.voice,
                    "from_cache": from_cache,
                    "synth_ms": round(synth_ms, 1),
                    "audio_duration_sec": round(
                        max(0.0, (len(pcma_bytes) / self.SAMPLE_RATE) - self.TAIL_PAD_SEC), 2
                    ),
                }
            )
            if tx_res.get("ok"):
                logger.info(
                    f"[ALTAVOZ C310] Emitido en {self.host} (session={tx_res.get('session_id')}, "
                    f"cache={from_cache}, voz={tx_res['audio_duration_sec']}s): {phrase!r}"
                )
            return tx_res


def speak_on_c310_sync(text: Optional[str] = None, voice: Optional[str] = None) -> Dict[str, Any]:
    """Helper síncrono seguro para invocar desde hilos o puentes como TelegramBridge."""
    speaker = TapoC310Speaker()
    return asyncio.run(speaker.speak(text=text, voice=voice))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TARDIS Speaker · Emisión de Voz Bidireccional para TP-Link Tapo C310"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "--say",
        type=str,
        default=None,
        help="Texto personalizado que TARDIS pronunciará desde la bocina de la cámara",
    )
    parser.add_argument(
        "--alert-default",
        action="store_true",
        help="Reproducir el aviso oficial de vigilancia TARDIS",
    )
    parser.add_argument(
        "--prewarm",
        action="store_true",
        help="Pre-sintetizar en caché el aviso oficial y verificar volumen del altavoz",
    )
    parser.add_argument("--voice", type=str, default=None, help="Voz neural edge-tts opcional")
    args = parser.parse_args()

    speaker = TapoC310Speaker(config_path=args.config)
    if args.prewarm:
        res = asyncio.run(speaker.prewarm_default_phrase())
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1

    target_text = args.say if args.say else speaker.default_message
    res = asyncio.run(speaker.speak(text=target_text, voice=args.voice))
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
