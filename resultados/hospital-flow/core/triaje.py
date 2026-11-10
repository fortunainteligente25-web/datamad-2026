"""
Triaje combinado: reglas + LLM
==============================

Orden de seguridad:
  1. Las reglas de la demo (processing.orientar_sintomas) se ejecutan SIEMPRE primero.
  2. Si las reglas detectan una emergencia o una crisis, se responde al instante (sin esperar al LLM).
  3. Si no, el LLM afina la especialidad y el nivel. El LLM puede SUBIR la gravedad, nunca bajarla.
  4. Sin API key o si el LLM falla, todo funciona solo con reglas.

Ningún paso de aquí elige hospital: eso lo hace el ranking.
"""
from __future__ import annotations

import logging
from typing import Any

from core import processing

log = logging.getLogger(__name__)

# Gravedad de cada nivel ("leve" y "programada" empatan: no son urgentes)
GRAVEDAD = {"sin_datos": 0, "leve": 1, "programada": 1, "urgente": 2, "emergencia": 3}
URGENCIA_LLM_A_NIVEL = {"vital": "emergencia", "urgente": "urgente", "programada": "programada", "leve": "leve"}


def _combinar_nivel(nivel_reglas: str, nivel_llm: str) -> str:
    """El más grave gana. Entre 'leve' y 'programada', gana 'programada' (es más concreto)."""
    if GRAVEDAD[nivel_llm] > GRAVEDAD[nivel_reglas]:
        return nivel_llm
    if GRAVEDAD[nivel_llm] == GRAVEDAD[nivel_reglas] and "programada" in (nivel_llm, nivel_reglas):
        return "programada"
    return nivel_reglas


def analizar(texto: str, especialidades_validas: list[str], usar_llm: bool = True) -> dict[str, Any]:
    """
    Devuelve: nivel, crisis, especialidad, procedimiento, resumen, mensaje, coincidencias y fuente
    ('reglas' o 'llm+reglas').
    """
    reglas = processing.orientar_sintomas(texto)
    resultado: dict[str, Any] = {
        "nivel": reglas["nivel"],
        "crisis": reglas["crisis"],
        "especialidad": reglas["especialidad"] if reglas["especialidad"] in especialidades_validas else None,
        "procedimiento": None,
        "resumen": None,
        "coincidencias": reglas["coincidencias"],
        "fuente": "reglas",
    }

    # Emergencia o crisis: respuesta inmediata, sin LLM.
    if reglas["nivel"] in ("sin_datos", "emergencia") or not usar_llm:
        resultado["mensaje"] = processing.mensaje_nivel(resultado["nivel"], resultado["crisis"])
        return resultado

    from llm import extractor  # import tardío: el núcleo funciona aunque falte la capa LLM

    llm = extractor.extraer(texto, especialidades_validas)
    if llm is not None:
        resultado["nivel"] = _combinar_nivel(reglas["nivel"], URGENCIA_LLM_A_NIVEL[llm.urgencia])
        # Pediatría tiene prioridad: si las reglas ven a un niño, se respeta.
        if resultado["especialidad"] != "Pediatría" and llm.especialidad:
            resultado["especialidad"] = llm.especialidad
        resultado["procedimiento"] = llm.procedimiento or None
        resultado["resumen"] = llm.resumen or None
        resultado["fuente"] = "llm+reglas"

    resultado["mensaje"] = processing.mensaje_nivel(resultado["nivel"], resultado["crisis"])
    return resultado
