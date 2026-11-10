"""
Extractor: mensaje del paciente -> JSON estructurado
====================================================

Usa tool use para obligar al modelo a responder con un esquema fijo y lo valida
con Pydantic. Si no hay API key, hay un error de red, un timeout o la respuesta no
valida, devuelve None y la app sigue con las reglas.

Prueba rápida:  python -m llm.extractor "necesito operarme la rodilla"
"""
from __future__ import annotations

import logging
import sys
from typing import Literal

from pydantic import BaseModel

from llm import cliente, prompts

log = logging.getLogger(__name__)
NOMBRE_HERRAMIENTA = "clasificar_consulta"


class Clasificacion(BaseModel):
    especialidad: str | None
    urgencia: Literal["vital", "urgente", "programada", "leve"]
    procedimiento: str = ""
    resumen: str = ""


def _herramienta(especialidades: list[str]) -> dict:
    return {
        "name": NOMBRE_HERRAMIENTA,
        "description": "Devuelve la clasificación estructurada del mensaje del paciente.",
        "input_schema": {
            "type": "object",
            "properties": {
                "especialidad": {"type": "string", "enum": [*especialidades, "ninguna"]},
                "urgencia": {"type": "string", "enum": ["vital", "urgente", "programada", "leve"]},
                "procedimiento": {"type": "string"},
                "resumen": {"type": "string"},
            },
            "required": ["especialidad", "urgencia", "procedimiento", "resumen"],
        },
    }


def extraer(mensaje: str, especialidades: list[str]) -> Clasificacion | None:
    """Clasifica el mensaje con el LLM. Devuelve None si el LLM no está disponible o falla."""
    llm = cliente.obtener_cliente()
    if llm is None:
        return None
    try:
        respuesta = llm.messages.create(
            model=cliente.MODELO,
            max_tokens=300,
            system=prompts.SISTEMA_EXTRACTOR.format(lista=", ".join(especialidades)),
            tools=[_herramienta(especialidades)],
            tool_choice={"type": "tool", "name": NOMBRE_HERRAMIENTA},
            messages=[{"role": "user", "content": mensaje}],
        )
        bloque = next(b for b in respuesta.content if b.type == "tool_use")
        datos = dict(bloque.input)
        if datos.get("especialidad") not in especialidades:  # "ninguna" o algo fuera de la lista
            datos["especialidad"] = None
        return Clasificacion(**datos)
    except Exception as exc:  # red, timeout, cuota, validación... -> reglas
        log.warning("Extractor LLM no disponible (%s); se usan las reglas.", type(exc).__name__)
        return None


if __name__ == "__main__":
    from core import ingestion, processing

    registros, _ = ingestion.obtener_datos_hospitales()
    df = processing.aplanar_hospitales(registros)
    lista = sorted({e for fila in df["especialidades"] for e in fila.split("; ")} - {"Urgencias generales"})
    texto = " ".join(sys.argv[1:]) or "necesito operarme la rodilla"
    print("LLM disponible:", cliente.disponible(), "| modelo:", cliente.MODELO)
    print(extraer(texto, lista))
