#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""que_cuente_las_5729.py
--------------------------------------------------------------------------
Herramienta dinámica de TARDIS · GODWORKS SYSTEM v26.4.
Arquitecto: El Arquitecto (₪).

Meta: contar las palabras de un texto.

Contrato de integración (core/tardis_dynamic_function_engine.py):
    * Clase principal ....... QueCuenteLas5729
    * Método exigido ....... QueCuenteLas5729.run(*args, **kwargs) -> dict
    * Punto de entrada ...... run(args) / t_que_cuente_las_5729(args)
    * Metadatos ............. TOOL_METADATA
    * Smoke test ............ ejecutar: python que_cuente_las_5729.py --self-test

Retorno normalizado:
    {"ok": True,  "result": {...}, "details": {...}}
    {"ok": False, "error": "<motivo>", "result": None, "details": {...}}

Capacidades:
    * Conteo total y de palabras únicas (casefold Unicode, acentos opcionales).
    * Frecuencias completas, ranking top-N y porcentajes.
    * Estadísticas: caracteres, oraciones, párrafos, longitud media, lectura.
    * Filtros: stopwords (ES/EN), longitud mínima, sólo letras, compuestos.
    * Entradas: str, bytes, Path, archivo, stream, secuencia o diccionario.
    * Búsqueda dirigida de una palabra objetivo y posiciones opcionales.

Sin dependencias externas: sólo biblioteca estándar.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "QueCuenteLas5729",
    "contar_palabras",
    "run",
    "t_que_cuente_las_5729",
    "que_cuente_las_5729",
    "TOOL_METADATA",
    "__version__",
]

__version__ = "1.0.0"

TOOL_METADATA = {
    "name": "que_cuente_las_5729",
    "description": (
        "Cuenta las palabras de un texto y entrega frecuencias, ranking top-N, "
        "palabras únicas, oraciones, párrafos y métricas de lectura, con filtros "
        "de stopwords, acentos, mayúsculas y longitud mínima."
    ),
    "version": __version__,
    "parameters": {
        "texto": {
            "type": "string",
            "description": "Texto a analizar (también admite archivo, bytes o secuencia).",
        },
        "archivo": {
            "type": "string",
            "description": "Ruta del archivo de texto a analizar (alternativa a `texto`).",
        },
        "top": {
            "type": "integer",
            "description": "Número de palabras del ranking (1-1000, por defecto 10).",
        },
        "quitar_stopwords": {
            "type": "boolean",
            "description": "Excluye palabras vacías del conteo (ES/EN).",
        },
        "case_sensitive": {
            "type": "boolean",
            "description": "Distingue mayúsculas y minúsculas (por defecto False).",
        },
        "normalizar_acentos": {
            "type": "boolean",
            "description": "Unifica palabras acentuadas con su forma sin acentos.",
        },
        "idioma": {
            "type": "string",
            "enum": ["auto", "es", "en"],
            "description": "Lista de stopwords a aplicar (auto = español + inglés).",
        },
        "min_longitud": {
            "type": "integer",
            "description": "Longitud mínima de palabra para contarla (por defecto 1).",
        },
        "incluir_posiciones": {
            "type": "boolean",
            "description": "Añade los índices de aparición de cada palabra.",
        },
        "palabra": {
            "type": "string",
            "description": "Palabra objetivo cuya frecuencia exacta se desea consultar.",
        },
    },
    "returns": {
        "type": "object",
        "required": ["ok", "result", "details"],
        "properties": {
            "ok": {"type": "boolean"},
            "result": {"type": "object"},
            "details": {"type": "object"},
            "error": {"type": "string"},
        },
    },
}

# ---------------------------------------------------------------------------
# Patrones y constantes
# ---------------------------------------------------------------------------

# Token: letras/dígitos Unicode con apóstrofes o guiones internos.
_PATRON_TOKEN = re.compile(r"[^\W_]+(?:[’'\-][^\W_]+)*", re.UNICODE)
_PATRON_FIN_ORACION = re.compile(r"[.!?…]+")
_PATRON_PARRAFO = re.compile(r"(?:\r?\n)[ \t]*(?:\r?\n)")
_PATRON_COMPUESTO = re.compile(r"[’'\-]")

_CLAVES_TEXTO = (
    "texto", "text", "input", "query", "contenido", "content", "documento",
    "document", "doc", "cuerpo", "body", "mensaje", "message", "prompt",
    "peticion", "petición", "cadena", "string", "valor", "value", "meta", "goal",
)
_CLAVES_ARCHIVO = (
    "archivo", "fichero", "file", "path", "ruta", "filename", "nombre_archivo",
    "filepath", "file_path",
)
_CLAVES_ANIDADAS = (
    "args", "kwargs", "params", "parametros", "parámetros", "payload",
    "options", "opciones", "config", "configuracion", "configuración",
)
_CLAVES_CONTENEDOR = ("data", "datos")

_CLAVES_BOOLEANAS_VERDADERO = frozenset(
    {"1", "true", "si", "sí", "yes", "y", "on", "verdadero", "activo", "enabled"}
)
_CLAVES_BOOLEANAS_FALSO = frozenset(
    {"0", "false", "no", "n", "off", "falso", "inactivo", "disabled", ""}
)

_PALABRAS_VACIAS_ES = frozenset("""
a al algo algunas alguno algunos ante antes aquel aquella aquellas aquello
aquellos aqui aquí asi así aun aún cada como cómo con contra cual cuál cuales
cuáles cuando cuándo de del desde donde dónde dos el ella ellas ello ellos en
entre era eran eres es esa esas ese eso esos esta está están estas este esto
estos estoy fue fueron ha habia había han hasta hay la las le les lo los mas
más me mi mis mucho muy nada ni no nos nosotros o os otra otro para pero poco
por porque que qué quien quién quienes se sea sean segun según ser si sí sin
sobre son su sus tambien también tan te tiene tienen todo todos tu tú tus un
una unas uno unos y ya
""".split())

_PALABRAS_VACIAS_EN = frozenset("""
a about above after again against all am an and any are as at be because been
before being below between both but by can cannot could did do does doing down
during each few for from further had has have having he her here hers herself
him himself his how i if in into is it its itself just me more most my myself
no nor not of off on once only or other our ours ourselves out over own same
she should so some such than that the their theirs them themselves then there
these they this those through to too under until up very was we were what when
where which while who whom why will with would you your yours yourself
yourselves
""".split())


class QueCuenteLas5729:
    """Cuenta palabras y produce métricas lingüísticas de un texto."""

    NOMBRE = "que_cuente_las_5729"
    VERSION = __version__
    LIMITE_CARACTERES = 2_000_000
    LIMITE_POSICIONES = 200

    # -- API principal ------------------------------------------------------

    def run(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Ejecuta el conteo de palabras y devuelve un diccionario normalizado.

        Acepta un texto posicional, un diccionario de argumentos (contrato del
        motor dinámico), un archivo, bytes, un stream o una secuencia de textos.
        Nunca propaga excepciones: los fallos se reportan en ``ok``/``error``.
        """
        inicio = time.perf_counter()
        advertencias: List[str] = []

        try:
            texto, origen, opciones = self._preparar(args, kwargs, advertencias)
            resultado = self._analizar(texto, opciones, origen, advertencias)
        except Exception as exc:  # noqa: BLE001 - frontera de robustez
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "result": None,
                "details": {
                    "modulo": self.NOMBRE,
                    "clase": type(self).__name__,
                    "version": self.VERSION,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "advertencias": advertencias,
                    "duracion_ms": round((time.perf_counter() - inicio) * 1000, 3),
                },
            }

        resultado["details"]["duracion_ms"] = round(
            (time.perf_counter() - inicio) * 1000, 3
        )
        return resultado

    def __call__(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self.run(*args, **kwargs)

    @classmethod
    def describe(cls) -> Dict[str, Any]:
        """Devuelve los metadatos públicos de la herramienta."""
        return dict(TOOL_METADATA)

    # -- Normalización de la entrada ---------------------------------------

    def _preparar(
        self,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        advertencias: List[str],
    ) -> Tuple[str, str, Dict[str, Any]]:
        """Extrae texto, origen y opciones desde los argumentos recibidos."""
        plano: Dict[str, Any] = self._aplanar(kwargs)
        posicionales: List[Any] = []

        for arg in args:
            if isinstance(arg, Mapping):
                for clave, valor in self._aplanar(arg).items():
                    plano.setdefault(clave, valor)
            else:
                posicionales.append(arg)

        texto = self._extraer_texto_plano(plano)
        archivo = self._extraer_archivo_plano(plano)
        opciones = self._construir_opciones(plano, advertencias)
        encoding = opciones["encoding"]
        origen = "texto"

        if texto is not None and archivo is not None:
            advertencias.append(
                "Se recibieron `texto` y `archivo`; se priorizó el texto explícito."
            )

        if texto is None and archivo is not None:
            texto = self._leer_archivo(archivo, encoding, opciones["max_caracteres"])
            origen = "archivo"

        for valor in posicionales:
            if texto is not None:
                advertencias.append("Se ignoraron argumentos posicionales adicionales.")
                break

            if isinstance(valor, Path):
                texto = self._leer_archivo(
                    str(valor), encoding, opciones["max_caracteres"]
                )
                origen = "archivo"
            elif isinstance(valor, (bytes, bytearray, memoryview)):
                texto = bytes(valor).decode(encoding, errors="replace")
                origen = "binario"
            elif hasattr(valor, "read") and callable(getattr(valor, "read")):
                leido = valor.read()
                if isinstance(leido, (bytes, bytearray)):
                    texto = bytes(leido).decode(encoding, errors="replace")
                else:
                    texto = str(leido)
                origen = "stream"
            elif isinstance(valor, str):
                if opciones["leer_rutas"] and self._parece_ruta(valor):
                    texto = self._leer_archivo(
                        valor, encoding, opciones["max_caracteres"]
                    )
                    origen = "archivo"
                else:
                    texto = valor
                    origen = "texto"
            elif isinstance(valor, Sequence):
                partes = [str(p) for p in valor if isinstance(p, (str, int, float))]
                if not partes:
                    raise ValueError(
                        "La secuencia recibida no contiene elementos textuales."
                    )
                texto = "\n".join(partes)
                origen = "secuencia"
            else:
                raise TypeError(
                    f"Tipo de entrada no soportado: {type(valor).__name__}. "
                    "Use str, bytes, Path, archivo, stream o secuencia de textos."
                )

        if texto is None:
            raise ValueError(
                "No se proporcionó texto. Envíe una cadena, un archivo o "
                "`{\"texto\": \"...\"}`."
            )

        return texto, origen, opciones

    def _aplanar(self, datos: Any, profundidad: int = 0) -> Dict[str, Any]:
        """Aplana diccionarios anidados de argumentos en claves canónicas."""
        plano: Dict[str, Any] = {}
        if not isinstance(datos, Mapping) or profundidad > 3:
            return plano

        for clave, valor in datos.items():
            clave_norm = str(clave).strip().lower().replace("-", "_")
            if isinstance(valor, Mapping) and (
                clave_norm in _CLAVES_ANIDADAS
                or clave_norm in _CLAVES_CONTENEDOR
            ):
                for subclave, subvalor in self._aplanar(
                    valor, profundidad + 1
                ).items():
                    plano.setdefault(subclave, subvalor)
                continue
            plano.setdefault(clave_norm, valor)
        return plano

    def _extraer_texto_plano(self, plano: Dict[str, Any]) -> Optional[str]:
        for clave in _CLAVES_TEXTO:
            if clave in plano and plano[clave] is not None:
                valor = plano.pop(clave)
                if isinstance(valor, (list, tuple)):
                    return "\n".join(str(elemento) for elemento in valor)
                return str(valor)
        return None

    def _extraer_archivo_plano(self, plano: Dict[str, Any]) -> Optional[str]:
        for clave in _CLAVES_ARCHIVO:
            if clave in plano and plano[clave] is not None:
                return str(plano.pop(clave))
        return None

    def _construir_opciones(
        self, plano: Mapping[str, Any], advertencias: List[str]
    ) -> Dict[str, Any]:
        """Normaliza y valida todas las opciones de ejecución."""
        case_sensitive = self._a_booleano(
            self._tomar(
                plano,
                ("case_sensitive", "sensible_mayusculas", "sensible_a_mayusculas",
                 "distinguir_mayusculas", "respetar_mayusculas"),
            ),
            False,
        )
        normalizar_acentos = self._a_booleano(
            self._tomar(
                plano,
                ("normalizar_acentos", "quitar_acentos", "sin_acentos",
                 "ignorar_acentos", "normalize_accents"),
            ),
            False,
        )
        quitar_stopwords = self._a_booleano(
            self._tomar(
                plano,
                ("quitar_stopwords", "sin_stopwords", "filtrar_stopwords",
                 "ignorar_palabras_vacias", "remove_stopwords"),
            ),
            False,
        )
        incluir_posiciones = self._a_booleano(
            self._tomar(
                plano,
                ("incluir_posiciones", "posiciones", "con_posiciones",
                 "include_positions"),
            ),
            False,
        )
        solo_letras = self._a_booleano(
            self._tomar(plano, ("solo_letras", "only_letters", "alfabeticas")),
            False,
        )
        dividir_compuestos = self._a_booleano(
            self._tomar(
                plano,
                ("dividir_compuestos", "split_compounds", "separar_compuestos"),
            ),
            False,
        )
        leer_rutas = self._a_booleano(
            self._tomar(plano, ("leer_rutas", "leer_paths", "rutas_como_archivo")),
            False,
        )

        top = self._a_entero(
            self._tomar(plano, ("top", "limite", "límite", "n", "ranking")),
            10,
            minimo=1,
            maximo=1000,
        )
        min_longitud = self._a_entero(
            self._tomar(
                plano,
                ("min_longitud", "longitud_minima", "min_len", "min_length"),
            ),
            1,
            minimo=1,
            maximo=200,
        )
        max_caracteres = self._a_entero(
            self._tomar(
                plano,
                ("max_caracteres", "max_chars", "limite_caracteres", "límite_caracteres"),
            ),
            self.LIMITE_CARACTERES,
            minimo=1,
            maximo=50_000_000,
        )

        idioma = str(
            self._tomar(plano, ("idioma", "language", "lang")) or "auto"
        ).strip().lower()
        if idioma not in ("auto", "es", "en", "ambos", "both"):
            advertencias.append(
                f"Idioma `{idioma}` no soportado; se usará `auto` (ES + EN)."
            )
            idioma = "auto"
        if idioma in ("ambos", "both"):
            idioma = "auto"

        objetivo = self._tomar(
            plano, ("palabra", "palabra_objetivo", "buscar", "objetivo", "word")
        )
        if objetivo is not None:
            objetivo = str(objetivo).strip() or None

        stopwords_extra = self._normalizar_stopwords(
            self._tomar(plano, ("stopwords_extra", "palabras_vacias_extra", "extras"))
        )

        encoding = str(
            self._tomar(plano, ("encoding", "codificacion", "codificación", "charset"))
            or "utf-8"
        )
        try:
            "".encode(encoding)
        except LookupError:
            advertencias.append(
                f"Encoding `{encoding}` desconocido; se usará `utf-8`."
            )
            encoding = "utf-8"

        return {
            "case_sensitive": case_sensitive,
            "normalizar_acentos": normalizar_acentos,
            "quitar_stopwords": quitar_stopwords,
            "idioma": idioma,
            "top": top,
            "min_longitud": min_longitud,
            "max_caracteres": max_caracteres,
            "incluir_posiciones": incluir_posiciones,
            "posiciones_max": self.LIMITE_POSICIONES,
            "solo_letras": solo_letras,
            "dividir_compuestos": dividir_compuestos,
            "leer_rutas": leer_rutas,
            "palabra_objetivo": objetivo,
            "stopwords_extra": stopwords_extra,
            "encoding": encoding,
        }

    # -- Análisis -----------------------------------------------------------

    def _analizar(
        self,
        texto: str,
        opciones: Mapping[str, Any],
        origen: str,
        advertencias: List[str],
    ) -> Dict[str, Any]:
        """Calcula todas las métricas de conteo sobre el texto."""
        if not isinstance(texto, str):
            texto = str(texto)

        truncado = False
        if len(texto) > opciones["max_caracteres"]:
            texto = texto[: opciones["max_caracteres"]]
            truncado = True
            advertencias.append(
                f"Texto truncado a {opciones['max_caracteres']} caracteres."
            )

        stopwords = self._stopwords(opciones)
        tokens = _PATRON_TOKEN.findall(texto)
        if opciones["dividir_compuestos"]:
            tokens = [
                parte
                for token in tokens
                for parte in _PATRON_COMPUESTO.split(token)
                if parte
            ]

        total_bruto = len(tokens)
        procesados: List[str] = []
        descartadas = {"no_letras": 0, "longitud": 0, "vacias": 0}

        for token in tokens:
            if opciones["solo_letras"] and not any(c.isalpha() for c in token):
                descartadas["no_letras"] += 1
                continue
            normalizada = self._normalizar(
                token,
                opciones["normalizar_acentos"],
                opciones["case_sensitive"],
            )
            if not normalizada:
                descartadas["longitud"] += 1
                continue
            if len(normalizada) < opciones["min_longitud"]:
                descartadas["longitud"] += 1
                continue
            if normalizada in stopwords:
                descartadas["vacias"] += 1
                continue
            procesados.append(normalizada)

        frecuencias = Counter(procesados)
        total = len(procesados)
        unicas = len(frecuencias)

        top = [
            {
                "palabra": palabra,
                "conteo": conteo,
                "porcentaje": round(100.0 * conteo / total, 2) if total else 0.0,
            }
            for palabra, conteo in frecuencias.most_common(opciones["top"])
        ]

        palabras_ordenadas = sorted(frecuencias)
        mas_larga = max(palabras_ordenadas, key=len) if palabras_ordenadas else None
        longitud_promedio = (
            round(sum(len(p) for p in procesados) / total, 2) if total else 0.0
        )

        resultado: Dict[str, Any] = {
            "total_palabras": total,
            "palabras_unicas": unicas,
            "total_tokens_brutos": total_bruto,
            "frecuencias": dict(frecuencias.most_common()),
            "top": top,
            "palabra_mas_frecuente": top[0]["palabra"] if top else None,
            "palabra_mas_larga": mas_larga,
            "longitud_maxima": len(mas_larga) if mas_larga else 0,
            "longitud_promedio": longitud_promedio,
            "caracteres": len(texto),
            "caracteres_sin_espacios": sum(1 for c in texto if not c.isspace()),
            "oraciones": self._contar_oraciones(texto),
            "parrafos": self._contar_parrafos(texto),
            "tiempo_lectura_min": round(total / 200.0, 2) if total else 0.0,
            "descartadas": descartadas,
        }

        if opciones["incluir_posiciones"] and procesados:
            resultado["posiciones"] = self._posiciones(
                procesados, opciones["posiciones_max"], advertencias
            )

        if opciones["palabra_objetivo"]:
            objetivo = self._normalizar(
                opciones["palabra_objetivo"],
                opciones["normalizar_acentos"],
                opciones["case_sensitive"],
            )
            coincidencias = frecuencias.get(objetivo, 0)
            resultado["objetivo"] = {
                "palabra": objetivo,
                "coincidencias": coincidencias,
                "porcentaje": round(100.0 * coincidencias / total, 2) if total else 0.0,
                "presente": coincidencias > 0,
            }

        return {
            "ok": True,
            "result": resultado,
            "details": {
                "modulo": self.NOMBRE,
                "clase": type(self).__name__,
                "version": self.VERSION,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "origen": origen,
                "truncado": truncado,
                "opciones": self._opciones_publicas(opciones),
                "stopwords_aplicadas": len(stopwords),
                "advertencias": advertencias,
            },
        }

    # -- Utilidades internas ------------------------------------------------

    @staticmethod
    def _normalizar(palabra: str, quitar_acentos: bool, case_sensitive: bool) -> str:
        """Normaliza una palabra para agrupar variantes equivalentes."""
        normalizada = unicodedata.normalize("NFC", palabra)
        if quitar_acentos:
            normalizada = "".join(
                c
                for c in unicodedata.normalize("NFD", normalizada)
                if unicodedata.category(c) != "Mn"
            )
        if not case_sensitive:
            normalizada = normalizada.casefold()
        return normalizada

    def _stopwords(self, opciones: Mapping[str, Any]) -> frozenset:
        idioma = opciones["idioma"]
        if not opciones["quitar_stopwords"] and not opciones["stopwords_extra"]:
            return frozenset()

        conjunto = set()
        if opciones["quitar_stopwords"]:
            if idioma in ("es", "auto"):
                conjunto.update(_PALABRAS_VACIAS_ES)
            if idioma in ("en", "auto"):
                conjunto.update(_PALABRAS_VACIAS_EN)

        for palabra in opciones["stopwords_extra"]:
            conjunto.add(
                self._normalizar(
                    palabra,
                    opciones["normalizar_acentos"],
                    opciones["case_sensitive"],
                )
            )
        return frozenset(p for p in conjunto if p)

    def _posiciones(
        self, procesados: Sequence[str], limite: int, advertencias: List[str]
    ) -> Dict[str, List[int]]:
        posiciones: Dict[str, List[int]] = {}
        recortadas = False
        for indice, palabra in enumerate(procesados):
            lista = posiciones.setdefault(palabra, [])
            if len(lista) < limite:
                lista.append(indice)
            else:
                recortadas = True
        if recortadas:
            advertencias.append(
                f"Posiciones recortadas a {limite} apariciones por palabra."
            )
        return posiciones

    @staticmethod
    def _contar_oraciones(texto: str) -> int:
        return sum(
            1 for fragmento in _PATRON_FIN_ORACION.split(texto) if fragmento.strip()
        )

    @staticmethod
    def _contar_parrafos(texto: str) -> int:
        if not texto.strip():
            return 0
        return sum(
            1 for bloque in _PATRON_PARRAFO.split(texto) if bloque.strip()
        ) or 1

    @staticmethod
    def _parece_ruta(valor: str) -> bool:
        if not valor or "\n" in valor or len(valor) > 4096:
            return False
        try:
            return Path(valor).expanduser().is_file()
        except (OSError, ValueError):
            return False

    @staticmethod
    def _leer_archivo(
        ruta: str, encoding: str, limite: Optional[int] = None
    ) -> str:
        """Lee un archivo (o stdin con `-`) sin cargar más de lo necesario."""
        if ruta.strip() == "-":
            if sys.stdin.isatty():
                raise ValueError(
                    "Se pidió leer de stdin, pero la entrada es interactiva."
                )
            return sys.stdin.read() if limite is None else sys.stdin.read(limite + 1)
        camino = Path(ruta).expanduser()
        if not camino.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {camino}")
        if not camino.is_file():
            raise IsADirectoryError(f"La ruta no es un archivo: {camino}")
        with camino.open("r", encoding=encoding, errors="replace") as manejador:
            return manejador.read(-1 if limite is None else limite + 1)

    @staticmethod
    def _tomar(plano: Mapping[str, Any], claves: Iterable[str]) -> Any:
        for clave in claves:
            if clave in plano and plano[clave] is not None:
                return plano[clave]
        return None

    @staticmethod
    def _a_booleano(valor: Any, defecto: bool) -> bool:
        if valor is None:
            return defecto
        if isinstance(valor, bool):
            return valor
        if isinstance(valor, (int, float)):
            return bool(valor)
        texto = str(valor).strip().lower()
        if texto in _CLAVES_BOOLEANAS_VERDADERO:
            return True
        if texto in _CLAVES_BOOLEANAS_FALSO:
            return False
        return defecto

    @staticmethod
    def _a_entero(valor: Any, defecto: int, minimo: int, maximo: int) -> int:
        if valor is None:
            return defecto
        try:
            numero = int(float(str(valor).strip().replace(",", ".")))
        except (TypeError, ValueError):
            return defecto
        return max(minimo, min(maximo, numero))

    @staticmethod
    def _normalizar_stopwords(valor: Any) -> List[str]:
        if valor is None:
            return []
        if isinstance(valor, str):
            return [p.strip() for p in re.split(r"[,;]+", valor) if p.strip()]
        if isinstance(valor, Mapping):
            return [str(p) for p in valor.keys()]
        if isinstance(valor, Iterable):
            return [str(p).strip() for p in valor if str(p).strip()]
        return []

    @staticmethod
    def _opciones_publicas(opciones: Mapping[str, Any]) -> Dict[str, Any]:
        publicas = dict(opciones)
        publicas["stopwords_extra"] = sorted(opciones.get("stopwords_extra", []))
        return publicas

    # -- Autoverificación ---------------------------------------------------

    def self_test(self) -> Dict[str, Any]:
        """Ejecuta una batería de pruebas de humo sobre la herramienta."""
        casos: List[Dict[str, Any]] = []

        def verificar(nombre: str, respuesta: Mapping[str, Any], validador) -> None:
            try:
                correcto = bool(respuesta.get("ok")) and bool(validador(respuesta))
                detalle = respuesta.get("error")
            except Exception as exc:  # noqa: BLE001
                correcto = False
                detalle = f"{type(exc).__name__}: {exc}"
            casos.append(
                {"caso": nombre, "ok": correcto, "detalle": detalle}
            )

        verificar(
            "conteo_basico",
            self.run("Hola mundo, hola TARDIS."),
            lambda r: r["result"]["total_palabras"] == 4
            and r["result"]["palabras_unicas"] == 3
            and r["result"]["top"][0]["palabra"] == "hola",
        )
        verificar(
            "acentos",
            self.run("canción cancion", normalizar_acentos=True),
            lambda r: r["result"]["palabras_unicas"] == 1
            and r["result"]["total_palabras"] == 2,
        )
        verificar(
            "stopwords",
            self.run("el sol y la luna", quitar_stopwords=True, idioma="es"),
            lambda r: r["result"]["total_palabras"] == 2
            and r["result"]["descartadas"]["vacias"] == 3,
        )
        verificar(
            "contrato_diccionario",
            self.run({"texto": "uno dos dos tres", "top": 1}),
            lambda r: r["result"]["top"] == [
                {"palabra": "dos", "conteo": 2, "porcentaje": 50.0}
            ],
        )
        verificar(
            "texto_vacio",
            self.run(""),
            lambda r: r["result"]["total_palabras"] == 0
            and r["result"]["parrafos"] == 0,
        )
        verificar(
            "posiciones",
            self.run("alfa beta alfa", incluir_posiciones=True),
            lambda r: r["result"]["posiciones"]["alfa"] == [0, 2],
        )
        verificar(
            "objetivo",
            self.run("sol luna sol", palabra="SOL"),
            lambda r: r["result"]["objetivo"]["coincidencias"] == 2,
        )

        error = self.run(12345)
        casos.append(
            {
                "caso": "error_controlado",
                "ok": error.get("ok") is False and bool(error.get("error")),
                "detalle": error.get("error"),
            }
        )

        fallos = sum(1 for caso in casos if not caso["ok"])
        return {
            "ok": fallos == 0,
            "result": {
                "total": len(casos),
                "aprobados": len(casos) - fallos,
                "fallos": fallos,
            },
            "details": {
                "modulo": self.NOMBRE,
                "version": self.VERSION,
                "casos": casos,
            },
        }


def contar_palabras(texto: Any, **opciones: Any) -> Dict[str, Any]:
    """Atajo funcional: devuelve directamente el bloque ``result``."""
    respuesta = QueCuenteLas5729().run(texto, **opciones)
    if respuesta.get("ok"):
        return respuesta["result"]
    return {"error": respuesta.get("error")}


def run(args: Any = None, *extra: Any, **kwargs: Any) -> Dict[str, Any]:
    """Punto de entrada funcional usado por el motor dinámico de TARDIS."""
    posicionales: Tuple[Any, ...] = () if args is None else (args,)
    return QueCuenteLas5729().run(*posicionales, *extra, **kwargs)


# Alias de compatibilidad con `_load_module_function` (t_<nombre>, <nombre>).
t_que_cuente_las_5729 = run
que_cuente_las_5729 = run


# ---------------------------------------------------------------------------
# Interfaz de línea de comandos
# ---------------------------------------------------------------------------


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=QueCuenteLas5729.NOMBRE,
        description="Cuenta las palabras de un texto o archivo.",
    )
    parser.add_argument("texto_posicional", nargs="?", help="Texto a analizar.")
    parser.add_argument("-t", "--texto", help="Texto a analizar.")
    parser.add_argument("-f", "--archivo", help="Archivo de texto a analizar.")
    parser.add_argument("-n", "--top", type=int, default=10, help="Tamaño del ranking.")
    parser.add_argument(
        "--stopwords", action="store_true", help="Excluir palabras vacías."
    )
    parser.add_argument("--idioma", default="auto", choices=["auto", "es", "en"])
    parser.add_argument(
        "--case-sensitive", action="store_true", help="Distinguir mayúsculas."
    )
    parser.add_argument(
        "--acentos", action="store_true", help="Normalizar acentos."
    )
    parser.add_argument(
        "--posiciones", action="store_true", help="Incluir posiciones."
    )
    parser.add_argument("--min-longitud", type=int, default=1)
    parser.add_argument(
        "--json", action="store_true", help="Emitir la respuesta JSON completa."
    )
    parser.add_argument(
        "--self-test", action="store_true", help="Ejecutar autoverificación."
    )
    opciones = parser.parse_args(argv)

    herramienta = QueCuenteLas5729()

    if opciones.self_test:
        verificacion = herramienta.self_test()
        print(json.dumps(verificacion, indent=2, ensure_ascii=False))
        return 0 if verificacion.get("ok") else 2

    texto = opciones.texto or opciones.texto_posicional
    respuesta = herramienta.run(
        texto,
        archivo=opciones.archivo,
        top=opciones.top,
        quitar_stopwords=opciones.stopwords,
        idioma=opciones.idioma,
        case_sensitive=opciones.case_sensitive,
        normalizar_acentos=opciones.acentos,
        incluir_posiciones=opciones.posiciones,
        min_longitud=opciones.min_longitud,
        leer_rutas=True,
    )

    if opciones.json or not respuesta.get("ok"):
        print(json.dumps(respuesta, indent=2, ensure_ascii=False))
        return 0 if respuesta.get("ok") else 1

    datos = respuesta["result"]
    print(f"Palabras: {datos['total_palabras']} | Únicas: {datos['palabras_unicas']}")
    print(f"Caracteres: {datos['caracteres']} | Oraciones: {datos['oraciones']}")
    print("Ranking:")
    for posicion, item in enumerate(datos["top"], 1):
        print(
            f"  {posicion:>2}. {item['palabra']}: "
            f"{item['conteo']} ({item['porcentaje']}%)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
