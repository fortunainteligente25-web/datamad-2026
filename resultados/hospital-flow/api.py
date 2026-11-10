"""
Hospital Flow · API (FastAPI)
=============================

Une la lógica (core/), el LLM (llm/) y sirve el frontend móvil (frontend/).

Ejecutar:   python api.py            -> http://localhost:8000
Docs API:   http://localhost:8000/docs
"""
from __future__ import annotations

import json
import time
from datetime import date, time as hora_t
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parent / ".env")

from core import ingestion, processing, programada, taxis, triaje  # noqa: E402
from llm import cliente, explicador  # noqa: E402

RAIZ = Path(__file__).resolve().parent
CACHE_S = 60  # los datos "en tiempo real" simulados se recalculan cada minuto
MADRID_BBOX = ((39.8, 41.2), (-4.7, -3.0))

ZONAS: dict[str, tuple[float, float]] = {  # de la demo, para cuando no hay GPS
    "Puerta del Sol": (40.4168, -3.7038),
    "Atocha": (40.4065, -3.6895),
    "Chamartín": (40.4723, -3.6827),
    "Moncloa": (40.4352, -3.7189),
    "Vallecas": (40.3930, -3.6190),
    "Getafe (centro)": (40.3057, -3.7327),
    "Fuenlabrada": (40.2842, -3.7942),
    "Alcalá de Henares": (40.4820, -3.3640),
}

app = FastAPI(title="Hospital Flow API", version="0.1.0",
              description="Recomendación de hospital por especialidad, cercanía y saturación.")

_cache: dict[str, Any] = {"t": 0.0, "df": None, "fuente": ""}


# --------------------------------------------------------------------------- #
# Datos
# --------------------------------------------------------------------------- #
def datos() -> tuple[pd.DataFrame, str]:
    if _cache["df"] is None or time.time() - _cache["t"] > CACHE_S:
        registros, fuente = ingestion.obtener_datos_hospitales()
        _cache.update(df=processing.aplanar_hospitales(registros), fuente=fuente, t=time.time())
    return _cache["df"], _cache["fuente"]


def especialidades_validas(df: pd.DataFrame) -> list[str]:
    todas = {e.strip() for fila in df["especialidades"] for e in str(fila).split(";") if e.strip()}
    return sorted(todas - {"Urgencias generales"})


def a_registros(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame -> lista de dicts con tipos nativos de Python (JSON seguro)."""
    filas = json.loads(df.to_json(orient="records", force_ascii=False))
    for f in filas:
        f["especialidades"] = [e.strip() for e in str(f.get("especialidades", "")).split(";") if e.strip()]
    return filas


def en_madrid(lat: float, lon: float) -> bool:
    (la0, la1), (lo0, lo1) = MADRID_BBOX
    return la0 <= lat <= la1 and lo0 <= lon <= lo1


def info_datos(fuente: str, df: pd.DataFrame) -> dict[str, Any]:
    return {"fuente": fuente, "actualizado": str(df["actualizado"].iloc[0]), "simulado": True}


# --------------------------------------------------------------------------- #
# Modelos de entrada
# --------------------------------------------------------------------------- #
class PeticionRecomendar(BaseModel):
    mensaje: str = Field(min_length=2, max_length=1000)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class PeticionExplicar(BaseModel):
    nivel: str
    especialidad: str | None = None
    modo: str = "urgencias"
    hospitales: list[dict[str, Any]] = Field(min_length=1, max_length=3)


class NuevaCita(BaseModel):
    hospital_id: str
    paciente: str = Field(min_length=1, max_length=120)
    fecha: date
    hora: hora_t
    motivo: str = Field(default="", max_length=300)


class CambioCita(BaseModel):
    fecha: date | None = None
    hora: hora_t | None = None
    motivo: str | None = Field(default=None, max_length=300)


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/api/estado")
def estado() -> dict[str, Any]:
    df, fuente = datos()
    return {
        "ok": True,
        "hospitales": len(df),
        "llm": cliente.disponible(),
        "modelo": cliente.MODELO if cliente.disponible() else None,
        "paradas_taxi": len(taxis.cargar_paradas()),
        "datos": info_datos(fuente, df),
    }


@app.get("/api/zonas")
def zonas() -> list[dict[str, Any]]:
    return [{"nombre": n, "lat": la, "lon": lo} for n, (la, lo) in ZONAS.items()]


@app.get("/api/hospitales")
def hospitales() -> dict[str, Any]:
    df, fuente = datos()
    return {"hospitales": a_registros(df), "datos": info_datos(fuente, df)}


@app.post("/api/recomendar")
def recomendar(p: PeticionRecomendar) -> dict[str, Any]:
    """Triaje (reglas + LLM) y ranking. El mensaje del usuario NO se guarda."""
    df, fuente = datos()
    t = triaje.analizar(p.mensaje, especialidades_validas(df))

    hay_listas = False
    if t["nivel"] == "programada":
        ranking, hay_listas = programada.recomendar(df, p.lat, p.lon, t["especialidad"])
        modo = "programada"
    else:
        ranking = processing.recomendar_hospitales(df, p.lat, p.lon, especialidad=t["especialidad"])
        # Un niño va a un hospital con urgencias pediátricas: si alguno la tiene, solo esos.
        if t["especialidad"] == "Pediatría" and ranking["tiene_especialidad"].any():
            ranking = ranking[ranking["tiene_especialidad"]].reset_index(drop=True)
            ranking["ranking"] = ranking.index + 1
        modo = "urgencias"

    return {
        "triaje": t,
        "modo": modo,
        "listas_espera": hay_listas,
        "hospitales": a_registros(ranking.head(3)),
        "fuera_de_madrid": not en_madrid(p.lat, p.lon),
        "datos": info_datos(fuente, df),
    }


@app.post("/api/explicar")
def explicar(p: PeticionExplicar) -> dict[str, str]:
    texto, fuente = explicador.explicar(p.nivel, p.especialidad, p.modo, p.hospitales)
    return {"texto": texto, "fuente": fuente}


@app.get("/api/taxis")
def taxis_cerca(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180)) -> dict[str, Any]:
    return {
        "emisoras": taxis.EMISORAS,
        "fuente_emisoras": taxis.FUENTE_EMISORAS,
        "paradas": taxis.paradas_cercanas(lat, lon, n=3),
    }


@app.get("/api/taxis/paradas")
def todas_las_paradas() -> dict[str, Any]:
    return {"paradas": taxis.cargar_paradas()}


@app.get("/api/citas")
def listar_citas() -> list[dict[str, Any]]:
    return processing.listar_citas()


@app.post("/api/citas", status_code=201)
def crear_cita(c: NuevaCita) -> dict[str, Any]:
    df, _ = datos()
    fila = df[df["id"] == c.hospital_id]
    if fila.empty:
        raise HTTPException(404, "Hospital no encontrado.")
    try:
        return processing.crear_cita(c.hospital_id, str(fila.iloc[0]["nombre"]), c.paciente, c.fecha, c.hora, c.motivo)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.patch("/api/citas/{cita_id}")
def cambiar_cita(cita_id: str, c: CambioCita) -> dict[str, Any]:
    try:
        return processing.modificar_cita(cita_id, c.fecha, c.hora, c.motivo)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/citas/{cita_id}")
def cancelar_cita(cita_id: str) -> dict[str, Any]:
    try:
        return processing.cancelar_cita(cita_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# El frontend se sirve en "/" (va al final para no tapar las rutas /api)
app.mount("/", StaticFiles(directory=RAIZ / "frontend", html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
