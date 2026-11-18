"""crear_una_funcin_5237.py
--------------------------------------------------------------------------
Herramienta dinámica de TARDIS · GODWORKS SYSTEM v26.4.

Meta: crear una función de prueba que sume dos números enteros.

Contrato de integración (core/tardis_dynamic_function_engine.py):
    * Clase principal ....... CrearUnaFuncin5237
    * Método exigido ....... CrearUnaFuncin5237.run(*args, **kwargs) -> dict
    * Punto de entrada ...... run(args) / t_crear_una_funcin_5237(args)
    * Metadatos ............. TOOL_METADATA
    * Smoke test ............ ejecutar: python crear_una_funcin_5237.py

Retorno normalizado:
    {"ok": True,  "result": <int>, "details": {...}}
    {"ok": False, "error": "<motivo>", "details": {...}}

Sin dependencias externas: sólo biblioteca estándar.
"""

from __future__ import annotations

import json
import operator
import re
import sys
import time
from datetime import datetime
from numbers import Integral
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "CrearUnaFuncin5237",
    "sumar_enteros",
    "run",
    "t_crear_una_funcin_5237",
    "crear_una_funcin_5237",
    "TOOL_METADATA",
    "__version__",
]

__version__ = "1.0.0"

TOOL_METADATA = {
    "name": "crear_una_funcin_5237",
    "description": (
        "Suma dos números enteros con validación estricta de tipos, coerción "
        "controlada de textos numéricos y reporte detallado del resultado."
    ),
    "version": __version__,
    "parameters": {
        "a": {
            "type": "integer",
            "description": "Primer sumando (acepta entero, texto numérico o float entero).",
        },
        "b": {
            "type": "integer",
            "description": "Segundo sumando (acepta entero, texto numérico o float entero).",
        },
    },
    "returns": {
        "type": "object",
        "required": ["ok"],
        "properties": {
            "ok": {"type": "boolean"},
            "result": {"type": "integer"},
            "details": {"type": "object"},
            "error": {"type": "string"},
        },
    },
}

# Claves admitidas para localizar cada sumando dentro de un diccionario.
_ALIAS_A = (
    "a", "x", "num1", "num_1", "n1", "numero1", "número1", "entero1",
    "sumando1", "sumando_1", "operando1", "operando_1", "left", "first",
    "arg1", "value1", "valor1",
)
_ALIAS_B = (
    "b", "y", "num2", "num_2", "n2", "numero2", "número2", "entero2",
    "sumando2", "sumando_2", "operando2", "operando_2", "right", "second",
    "arg2", "value2", "valor2",
)
_CLAVES_TEXTO = (
    "input", "query", "texto", "text", "prompt", "peticion", "petición",
    "meta", "goal", "expresion", "expresión", "operacion", "operación",
)
_CLAVES_ANIDADAS = ("args", "kwargs", "params", "parametros", "parámetros", "payload")

_PATRON_SUMA = re.compile(
    r"([+-]?\d[\d_]*)\s*(?:\+|,|;|\by\b|\band\b)\s*([+-]?\d[\d_]*)",
    re.IGNORECASE,
)

_MISSING = object()
_INT64_MIN = -(2 ** 63)
_INT64_MAX = 2 ** 63 - 1


def _coerce_entero(valor: Any, etiqueta: str) -> Tuple[int, Optional[str]]:
    """Convierte *valor* a ``int`` estricto.

    Devuelve ``(entero, nota_de_coercion)``; lanza ``TypeError`` o
    ``ValueError`` con un mensaje legible cuando la conversión no es posible.
    """
    if isinstance(valor, bool):
        raise TypeError(
            f"`{etiqueta}` recibió un booleano ({valor!r}); se esperaba un número entero"
        )
    if isinstance(valor, Integral):
        return int(valor), None
    if isinstance(valor, float):
        if valor != valor or valor in (float("inf"), float("-inf")):
            raise ValueError(f"`{etiqueta}` no es un entero finito: {valor!r}")
        if not valor.is_integer():
            raise ValueError(f"`{etiqueta}` tiene parte decimal ({valor!r}); se esperaba un entero")
        return int(valor), "float entero → int"
    if isinstance(valor, str):
        texto = valor.strip().replace("_", "").replace(" ", "")
        if not texto:
            raise ValueError(f"`{etiqueta}` está vacío")
        try:
            return int(texto, 10), "texto → int"
        except ValueError:
            pass
        try:
            numero = float(texto)
        except ValueError:
            raise ValueError(
                f"`{etiqueta}` no es un entero válido: {valor!r}"
            ) from None
        if not numero.is_integer():
            raise ValueError(f"`{etiqueta}` no es un entero válido: {valor!r}")
        return int(numero), "texto decimal entero → int"
    try:
        return operator.index(valor), "objeto con __index__ → int"
    except TypeError:
        raise TypeError(
            f"`{etiqueta}` de tipo {type(valor).__name__} no es convertible a entero: {valor!r}"
        ) from None


def _buscar_alias(fuente: Mapping, alias: Sequence[str]) -> Tuple[Any, Optional[str]]:
    """Busca en *fuente* la primera clave de *alias* (sin distinguir mayúsculas)."""
    normalizado: Dict[str, Any] = {}
    for clave, valor in fuente.items():
        if isinstance(clave, str):
            normalizado.setdefault(clave.strip().lower(), valor)
    for nombre in alias:
        if nombre in normalizado:
            return normalizado[nombre], nombre
    return _MISSING, None


def sumar_enteros(a: Any, b: Any) -> int:
    """Suma dos enteros con coerción controlada. Lanza excepción si son inválidos."""
    entero_a, _ = _coerce_entero(a, "a")
    entero_b, _ = _coerce_entero(b, "b")
    return entero_a + entero_b


class CrearUnaFuncin5237:
    """Herramienta de prueba: suma determinista de dos números enteros.

    Modos de invocación admitidos por :meth:`run`:
        * ``run(2, 3)``                          → posicional
        * ``run(a=2, b=3)``                      → por nombre
        * ``run({"a": 2, "b": 3})``              → diccionario (motor dinámico)
        * ``run({"x": "2", "y": "3"})``          → alias + texto numérico
        * ``run([2, 3])``                        → secuencia
        * ``run("suma 2 y 3")``                  → lenguaje natural simple
        * ``run()``                              → identidad 0 + 0

    Siempre retorna un diccionario; nunca propaga excepciones desde ``run``.
    """

    NAME = "crear_una_funcin_5237"
    VERSION = __version__

    def __init__(self, nombre: Optional[str] = None) -> None:
        self.nombre = nombre or self.NAME

    # ------------------------------------------------------------------
    # Resolución de operandos
    # ------------------------------------------------------------------
    def _resolver_operandos(
        self, posicionales: Sequence[Any], nombrados: Mapping[str, Any]
    ) -> Tuple[int, int, Dict[str, Any]]:
        """Normaliza cualquier combinación de argumentos a dos enteros."""
        notas: List[str] = []
        brutos: Dict[str, Any] = {}
        fuentes: Dict[str, str] = {}

        valores = list(posicionales)

        # 1) Diccionario único (contrato del motor dinámico).
        if len(valores) == 1 and isinstance(valores[0], Mapping):
            fuente = valores.pop(0)
            for clave in _CLAVES_ANIDADAS:
                anidado = fuente.get(clave)
                if isinstance(anidado, Mapping):
                    brutos.update(anidado)
                    notas.append(f"parámetros anidados expandidos desde `{clave}`")
            brutos.update(fuente)
            fuentes["origen"] = "diccionario"

        # 2) Secuencia única con los dos sumandos.
        elif len(valores) == 1 and isinstance(valores[0], (list, tuple)) and valores[0]:
            valores = list(valores[0])
            notas.append("secuencia desempaquetada como operandos")
            fuentes["origen"] = "secuencia"

        # 3) Cadena única con expresión de suma ("12 y 30", "12+30", ...).
        elif len(valores) == 1 and isinstance(valores[0], str):
            coincidencia = _PATRON_SUMA.search(valores[0])
            if coincidencia:
                valores = [coincidencia.group(1), coincidencia.group(2)]
                notas.append("operandos extraídos de texto")
                fuentes["origen"] = "texto"

        crudos: Dict[str, Any] = {}
        if len(valores) >= 2:
            crudos["a"], fuentes["a"] = valores[0], "posicional[0]"
            crudos["b"], fuentes["b"] = valores[1], "posicional[1]"
            if len(valores) > 2:
                notas.append(f"{len(valores) - 2} argumento(s) posicional(es) extra ignorado(s)")
        elif len(valores) == 1:
            crudos["a"], fuentes["a"] = valores[0], "posicional[0]"

        # 4) Alias por nombre o dentro del diccionario.
        if "a" not in crudos:
            valor, clave = _buscar_alias(nombrados, _ALIAS_A)
            if valor is _MISSING:
                valor, clave = _buscar_alias(brutos, _ALIAS_A)
                if valor is not _MISSING:
                    fuentes["a"] = f"diccionario['{clave}']"
            else:
                fuentes["a"] = f"kwarg['{clave}']"
            if valor is not _MISSING:
                crudos["a"] = valor
            elif "a" in brutos:
                crudos["a"], fuentes["a"] = brutos["a"], "diccionario['a']"
        elif "a" in brutos:
            notas.append("se ignoró `a` del diccionario por prioridad del argumento posicional")

        if "b" not in crudos:
            valor, clave = _buscar_alias(nombrados, _ALIAS_B)
            if valor is _MISSING:
                valor, clave = _buscar_alias(brutos, _ALIAS_B)
                if valor is not _MISSING:
                    fuentes["b"] = f"diccionario['{clave}']"
            else:
                fuentes["b"] = f"kwarg['{clave}']"
            if valor is not _MISSING:
                crudos["b"] = valor
            elif "b" in brutos:
                crudos["b"], fuentes["b"] = brutos["b"], "diccionario['b']"
        elif "b" in brutos:
            notas.append("se ignoró `b` del diccionario por prioridad del argumento posicional")

        # 5) Último recurso: extraer una suma embebida en textos del diccionario.
        if "a" not in crudos or "b" not in crudos:
            candidatos: List[str] = []
            for clave in _CLAVES_TEXTO:
                valor = brutos.get(clave)
                if isinstance(valor, str):
                    candidatos.append(valor)
            candidatos.extend(
                valor for valor in brutos.values()
                if isinstance(valor, str) and len(valor) <= 200
            )
            for texto in candidatos:
                coincidencia = _PATRON_SUMA.search(texto)
                if not coincidencia:
                    continue
                if "a" not in crudos:
                    crudos["a"] = coincidencia.group(1)
                    fuentes["a"] = "texto del diccionario"
                if "b" not in crudos:
                    crudos["b"] = coincidencia.group(2)
                    fuentes["b"] = "texto del diccionario"
                notas.append(f"suma inferida del texto: {texto.strip()[:60]!r}")
                break

        # 6) Identidad aritmética cuando no se suministró un operando.
        if "a" not in crudos:
            crudos["a"], fuentes["a"] = 0, "identidad por defecto"
            notas.append("sin primer sumando: se usó la identidad 0")
        if "b" not in crudos:
            crudos["b"], fuentes["b"] = 0, "identidad por defecto"
            notas.append("sin segundo sumando: se usó la identidad 0")

        entero_a, nota_a = _coerce_entero(crudos["a"], "a")
        entero_b, nota_b = _coerce_entero(crudos["b"], "b")
        if nota_a:
            notas.append(f"coerción de `a`: {nota_a}")
        if nota_b:
            notas.append(f"coerción de `b`: {nota_b}")

        return entero_a, entero_b, {"fuentes": fuentes, "notas": notas}

    # ------------------------------------------------------------------
    # Punto de entrada exigido
    # ------------------------------------------------------------------
    def run(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Ejecuta la suma y retorna un diccionario normalizado.

        Nunca lanza excepciones: los fallos se reportan como
        ``{"ok": False, "error": ...}``.
        """
        inicio = time.perf_counter()
        try:
            entero_a, entero_b, meta = self._resolver_operandos(args, kwargs)
            total = entero_a + entero_b
            duracion = round((time.perf_counter() - inicio) * 1000, 4)

            return {
                "ok": True,
                "result": total,
                "details": {
                    "operacion": "suma de enteros",
                    "operandos": {"a": entero_a, "b": entero_b},
                    "resultado": total,
                    "fuentes": meta["fuentes"],
                    "notas": meta["notas"],
                    "tipo_resultado": type(total).__name__,
                    "int64": {
                        "seguro": _INT64_MIN <= total <= _INT64_MAX,
                        "limite_inferior": _INT64_MIN,
                        "limite_superior": _INT64_MAX,
                    },
                    "modulo": self.nombre,
                    "clase": type(self).__name__,
                    "version": self.VERSION,
                    "duracion_ms": duracion,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                },
            }
        except Exception as exc:
            duracion = round((time.perf_counter() - inicio) * 1000, 4)
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "details": {
                    "modulo": self.nombre,
                    "clase": type(self).__name__,
                    "version": self.VERSION,
                    "entrada_posicional": [repr(v) for v in args],
                    "entrada_nombrada": sorted(str(k) for k in kwargs),
                    "duracion_ms": duracion,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                },
            }

    __call__ = run

    # ------------------------------------------------------------------
    # Autoverificación
    # ------------------------------------------------------------------
    def self_test(self) -> Dict[str, Any]:
        """Batería interna de casos; útil para CI y para el smoke test."""
        casos = [
            ("posicionales", lambda: self.run(2, 3), 5),
            ("kwargs", lambda: self.run(a=40, b=2), 42),
            ("diccionario_alias", lambda: self.run({"x": -7, "y": 7}), 0),
            ("texto_numerico", lambda: self.run({"a": "12", "b": "30"}), 42),
            ("float_entero", lambda: self.run(1.0, 2.0), 3),
            ("secuencia", lambda: self.run([5, 6]), 11),
            ("lenguaje_natural", lambda: self.run("suma 15 y 27"), 42),
            ("sin_argumentos", lambda: self.run(), 0),
            ("negativos", lambda: self.run(-5, -8), -13),
            ("enteros_grandes", lambda: self.run(10 ** 18, 10 ** 18), 2 * 10 ** 18),
        ]
        resultados = []
        fallos = 0
        for nombre, ejecutar, esperado in casos:
            respuesta = ejecutar()
            obtenido = respuesta.get("result")
            correcto = bool(respuesta.get("ok")) and obtenido == esperado
            if not correcto:
                fallos += 1
            resultados.append(
                {
                    "caso": nombre,
                    "ok": correcto,
                    "esperado": esperado,
                    "obtenido": obtenido,
                    "error": respuesta.get("error"),
                }
            )

        error_controlado = self.run("no_numerico", 1)
        if error_controlado.get("ok") is not False:
            fallos += 1
            resultados.append(
                {"caso": "error_controlado", "ok": False, "detalle": "debió fallar y no falló"}
            )
        else:
            resultados.append(
                {"caso": "error_controlado", "ok": True, "error": error_controlado.get("error")}
            )

        total = len(resultados)
        return {
            "ok": fallos == 0,
            "result": {"total": total, "aprobados": total - fallos, "fallos": fallos},
            "details": {"casos": resultados, "modulo": self.nombre, "version": self.VERSION},
        }


def run(args: Any = None, *extra: Any, **kwargs: Any) -> Dict[str, Any]:
    """Punto de entrada funcional usado por el motor dinámico de TARDIS."""
    posicionales = () if args is None else (args,)
    return CrearUnaFuncin5237().run(*posicionales, *extra, **kwargs)


# Alias de compatibilidad con `_load_module_function` (t_<nombre>, <nombre>).
t_crear_una_funcin_5237 = run
crear_una_funcin_5237 = run


if __name__ == "__main__":
    herramienta = CrearUnaFuncin5237()
    verificacion = herramienta.self_test()

    print("=== TARDIS :: crear_una_funcin_5237 ===")
    print(json.dumps(herramienta.run(2, 3), indent=2, ensure_ascii=False))
    print("--- autoverificación ---")
    print(json.dumps(verificacion, indent=2, ensure_ascii=False))
    sys.exit(0 if verificacion.get("ok") else 1)
