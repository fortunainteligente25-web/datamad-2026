"""
Explicador: top 3 del ranking -> 2 frases en lenguaje natural
=============================================================

El LLM solo recibe los datos del ranking y tiene prohibido inventar. Si no hay
LLM, se usa una plantilla con los mismos datos.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from llm import cliente, prompts

log = logging.getLogger(__name__)

CAMPOS = ("nombre", "espera_min", "viaje_min", "total_estimado_min", "distancia_km", "ocupacion_pct",
          "nivel_ocupacion", "camas_disponibles", "tiene_especialidad", "demora_dias")


def _km(valor: Any) -> str:
    return f"{float(valor):.1f}".replace(".", ",")


def _limpiar(hospitales: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: h.get(k) for k in CAMPOS if h.get(k) is not None} for h in hospitales[:3]]


def plantilla(especialidad: str | None, modo: str, hospitales: list[dict[str, Any]]) -> str:
    h = hospitales[0]
    if modo == "programada":
        con_esp = f" con {especialidad}" if especialidad and h.get("tiene_especialidad") else ""
        texto = f"{h['nombre']} es el hospital{con_esp} más cercano a ti ({_km(h['distancia_km'])} km)."
        if h.get("demora_dias") is not None:
            texto += f" Su espera media para operarse es de {round(h['demora_dias'])} días."
        else:
            texto += " Cuando carguemos las listas de espera oficiales, también contarán los días de espera."
        return texto

    total = h["espera_min"] + h["viaje_min"]
    texto = (f"En el {h['nombre']} sumas unos {total} min entre el viaje ({h['viaje_min']} min) "
             f"y la espera ({h['espera_min']} min).")
    if len(hospitales) > 1:
        o = hospitales[1]
        total_o = o["espera_min"] + o["viaje_min"]
        if total <= min(x["espera_min"] + x["viaje_min"] for x in hospitales[1:]):
            texto += f" Es donde antes te atienden: en el {o['nombre']} serían unos {total_o} min."
        elif especialidad and h.get("tiene_especialidad") and not o.get("tiene_especialidad"):
            texto += f" El {o['nombre']} tarda algo menos ({total_o} min), pero no tiene {especialidad}."
        elif o.get("ocupacion_pct", 0) > h.get("ocupacion_pct", 0):
            texto += (f" El {o['nombre']} tarda algo menos ({total_o} min), pero está más saturado "
                      f"({o['ocupacion_pct']} % frente a {h['ocupacion_pct']} %).")
        else:
            texto += f" La siguiente opción, el {o['nombre']}, suma unos {total_o} min."
    return texto


def explicar(nivel: str, especialidad: str | None, modo: str,
             hospitales: list[dict[str, Any]]) -> tuple[str, str]:
    """Devuelve (texto, fuente) donde fuente es 'llm' o 'plantilla'."""
    datos = _limpiar(hospitales)
    llm = cliente.obtener_cliente()
    if llm is not None and datos:
        try:
            entrada = {"nivel": nivel, "especialidad": especialidad, "modo": modo, "hospitales": datos}
            respuesta = llm.messages.create(
                model=cliente.MODELO,
                max_tokens=200,
                system=prompts.SISTEMA_EXPLICADOR,
                messages=[{"role": "user", "content": json.dumps(entrada, ensure_ascii=False)}],
            )
            texto = "".join(b.text for b in respuesta.content if b.type == "text").strip()
            if texto:
                return texto, "llm"
        except Exception as exc:
            log.warning("Explicador LLM no disponible (%s); se usa la plantilla.", type(exc).__name__)
    return plantilla(especialidad, modo, datos or hospitales), "plantilla"
