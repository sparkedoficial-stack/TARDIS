"""
Módulo autónomo: que_cuente_las_5729
Sistema: TARDIS-NEURAL-SPACE-KAIJU · Operación Soberana

Descripción:
    Módulo de conteo de palabras de un texto, totalmente autónomo y robusto.
    Implementa la clase QueCuenteLas5729 con el método run(self, *args, **kwargs)
    que retorna un diccionario con el resultado de la ejecución.
"""

from __future__ import annotations

from typing import Any, Dict


class QueCuenteLas5729:
    """
    Clase principal para contar palabras en un texto.

    Método:
        run(self, *args, **kwargs) -> Dict[str, Any]

    Ejecuta el conteo de palabras sobre un texto de entrada y retorna
    un diccionario estructurado con el resultado, incluyendo conteo total,
    palabras únicas, longitud promedio y metadatos de ejecución.
    """

    def run(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        Ejecuta el conteo de palabras del texto proporcionado.

        Parámetros aceptados (vía args o kwargs):
            - texto (str): Texto a analizar. Obligatorio.
            - ignorar_vacios (bool): Si excluir tokens vacíos del conteo. Default True.
            - case_sensitive (bool): Si distinguir mayúsculas/minúsculas para
              palabras únicas. Default False.
            - separador (str): Expresión regular o caracter para dividir palabras.
              Default usa split por espacios en blanco.

        Retorna:
            Dict[str, Any]: Estructura con:
                - exito (bool): Indica si la ejecución fue exitosa.
                - total_palabras (int): Cantidad total de palabras contadas.
                - palabras_unicas (int): Cantidad de palabras distintas.
                - longitud_promedio (float): Longitud promedio de las palabras.
                - texto_entrada (str): Texto procesado.
                - error (str | None): Mensaje de error si falló, None si no.
                - metadata (dict): Información adicional de ejecución.
        """
        resultado: Dict[str, Any] = {
            "exito": False,
            "total_palabras": 0,
            "palabras_unicas": 0,
            "longitud_promedio": 0.0,
            "texto_entrada": "",
            "error": None,
            "metadata": {
                "modulo": "que_cuente_las_5729",
                "clase": "QueCuenteLas5729",
                "metodo": "run",
            },
        }

        try:
            # Extraer el texto de entrada desde args o kwargs
            texto: str = ""
            if args:
                texto = str(args[0])
            elif "texto" in kwargs:
                texto = str(kwargs["texto"])
            else:
                raise ValueError(
                    "No se proporcionó texto para contar. Pase el texto como "
                    "primer argumento posicional o como kwarg 'texto'."
                )

            resultado["texto_entrada"] = texto

            # Opciones de configuración
            ignorar_vacios: bool = kwargs.get("ignorar_vacios", True)
            case_sensitive: bool = kwargs.get("case_sensitive", False)
            separador: str | None = kwargs.get("separador", None)

            # División del texto en palabras
            if separador is not None:
                palabras_raw = texto.split(separador)
            else:
                palabras_raw = texto.split()

            # Filtrado de tokens vacíos si se solicita
            if ignorar_vacios:
                palabras = [p for p in palabras_raw if p.strip() != ""]
            else:
                palabras = palabras_raw

            # Conteo total
            total_palabras = len(palabras)
            resultado["total_palabras"] = total_palabras

            # Conteo de palabras únicas
            if case_sensitive:
                palabras_unicas_set = set(palabras)
            else:
                palabras_unicas_set = set(p.lower() for p in palabras)
            resultado["palabras_unicas"] = len(palabras_unicas_set)

            # Longitud promedio de palabras
            if total_palabras > 0:
                longitud_total = sum(len(p) for p in palabras)
                resultado["longitud_promedio"] = round(
                    longitud_total / total_palabras, 4
                )
            else:
                resultado["longitud_promedio"] = 0.0

            resultado["exito"] = True
            resultado["metadata"]["palabras_procesadas"] = total_palabras
            resultado["metadata"]["estado"] = "completado"

        except Exception as exc:  # Manejo interno de excepciones
            resultado["exito"] = False
            resultado["error"] = f"{type(exc).__name__}: {str(exc)}"
            resultado["metadata"]["estado"] = "fallido"
            resultado["metadata"]["excepcion"] = type(exc).__name__

        return resultado