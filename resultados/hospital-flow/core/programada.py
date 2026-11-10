"""
Operaciones programadas (listas de espera quirúrgica)
=====================================================

Si existe data/clean/listas_espera.csv, el ranking de operaciones programadas
usa los días de espera + la distancia. Si no existe, ordena por especialidad y
distancia y avisa de que faltan las listas oficiales.

Formato esperado de data/clean/listas_espera.csv (lo genera data/limpieza.py):
    hospital_id, especialidad, demora_media_dias[, pacientes]
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from core import processing

RUTA_LISTAS = Path(__file__).resolve().parent.parent / "data" / "clean" / "listas_espera.csv"
PESO_DEMORA = 0.6
PESO_DISTANCIA = 0.4


def cargar_listas() -> pd.DataFrame | None:
    if not RUTA_LISTAS.exists():
        return None
    df = pd.read_csv(RUTA_LISTAS)
    obligatorias = {"hospital_id", "especialidad", "demora_media_dias"}
    if not obligatorias.issubset(df.columns):
        return None
    df["especialidad_norm"] = df["especialidad"].astype(str).map(processing._normalizar)
    return df


def recomendar(df: pd.DataFrame, lat: float, lon: float, especialidad: str | None) -> tuple[pd.DataFrame, bool]:
    """Devuelve (ranking, hay_listas_de_espera)."""
    base = processing.recomendar_hospitales(df, lat, lon, w_espera=0, w_ocupacion=0, w_distancia=1,
                                            especialidad=especialidad)
    # Para operarse, la especialidad es imprescindible: si algún hospital la tiene, solo esos.
    if especialidad and base["tiene_especialidad"].any():
        base = base[base["tiene_especialidad"]].reset_index(drop=True)
        base["ranking"] = base.index + 1
    base["demora_dias"] = float("nan")
    listas = cargar_listas()
    if listas is None or not especialidad:
        return base, False

    objetivo = processing._normalizar(especialidad)
    demoras = listas[listas["especialidad_norm"] == objetivo].set_index("hospital_id")["demora_media_dias"]
    base["demora_dias"] = base["id"].map(demoras)
    con_datos = base["demora_dias"].notna()
    if not con_datos.any():
        return base, False

    penalizacion = (
        PESO_DEMORA * processing._minmax(base["demora_dias"].fillna(base["demora_dias"].max()))
        + PESO_DISTANCIA * processing._minmax(base["distancia_km"])
        + (~base["tiene_especialidad"]) * processing.PENALIZACION_SIN_ESPECIALIDAD
    )
    base["score"] = ((1 - penalizacion.clip(0, 1)) * 100).round(1)
    base = base.sort_values(["score", "distancia_km"], ascending=[False, True]).reset_index(drop=True)
    base["ranking"] = base.index + 1
    return base, True
