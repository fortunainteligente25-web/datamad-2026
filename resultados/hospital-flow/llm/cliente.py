"""Configuración del cliente LLM (Anthropic). Lee la clave y el modelo del archivo .env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODELO = os.getenv("LLM_MODEL", "claude-haiku-5-5").strip() or "claude-haiku-5-5"
TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "8"))


@lru_cache(maxsize=1)
def obtener_cliente():
    """Devuelve el cliente de Anthropic, o None si no hay API key (la app usará solo reglas)."""
    clave = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not clave or clave.startswith("sk-ant-..."):
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        return None
    return Anthropic(api_key=clave, timeout=TIMEOUT_S, max_retries=1)


def disponible() -> bool:
    return obtener_cliente() is not None
