"""
Taxis: emisoras de radio-taxi y paradas
=======================================

- Emisoras: teléfonos publicados por esMadrid (web oficial de turismo del Ayuntamiento).
  Verificadlos antes de la presentación.
- Paradas: servicio ArcGIS del Geoportal del Ayuntamiento de Madrid
  (GEOPORTAL/RESERVAS_PLAZAS_TAXI, capas 0-3). Se leen los archivos
  data/raw/paradas_taxi_*.geojson (o .json) si existen. Cómo descargarlos: ver README.

Nota: los datasets "Taxi" de datos.madrid.es son de flota y licencias; no sirven para pedir un taxi.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from core.processing import distancia_km

log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent
CARPETAS = (RAIZ / "data" / "raw", RAIZ / "data" / "clean", RAIZ)
VELOCIDAD_A_PIE_KMH = 4.8
MADRID_LAT = (40.30, 40.65)   # término municipal de Madrid, con margen
MADRID_LON = (-3.90, -3.50)

FUENTE_EMISORAS = "Teléfonos publicados por esMadrid"
EMISORAS: list[dict[str, str]] = [
    {"nombre": "Tele Taxi", "telefono": "+34913712131", "visible": "91 371 21 31"},
    {"nombre": "pidetaxi", "telefono": "+34915478200", "visible": "91 547 82 00"},
    {"nombre": "TxMAD", "telefono": "+34914043324", "visible": "91 404 33 24",
     "nota": "App oficial del Ayuntamiento"},
]

HORARIO_CAPA = {"0": "Fines de semana", "1": "Lunes a viernes", "2": "Todos los días", "3": "Otras"}
_CLAVES_TEXTO = ("direc", "ubicac", "calle", "vial", "nombre", "denom", "descrip", "localiz", "emplaz")
_CLAVES_PLAZAS = ("plaza", "capac", "num")

_cache: dict[str, Any] = {"firma": None, "paradas": []}


def _texto(props: dict[str, Any]) -> str:
    for clave, valor in props.items():
        if any(k in str(clave).lower() for k in _CLAVES_TEXTO) and isinstance(valor, str) and valor.strip():
            texto = re.sub(r"\s+", " ", valor).strip().title()
            return re.sub(r"\b(De|Del|La|Las|Los|El|Y|En)\b", lambda m: m.group(1).lower(), texto)
    return "Parada de taxi"


def _plazas(props: dict[str, Any]) -> int | None:
    for clave, valor in props.items():
        if any(k in str(clave).lower() for k in _CLAVES_PLAZAS):
            try:
                n = int(float(valor))
                if 0 < n < 200:
                    return n
            except (TypeError, ValueError):
                continue
    return None


def _punto(geom: dict[str, Any] | None) -> tuple[float, float] | None:
    """Devuelve (lat, lon) de una geometría GeoJSON o Esri JSON."""
    if not geom:
        return None
    if "x" in geom and "y" in geom:  # Esri JSON
        return float(geom["y"]), float(geom["x"])
    coords = geom.get("coordinates")
    tipo = geom.get("type")
    if not coords:
        return None
    if tipo == "Point":
        return float(coords[1]), float(coords[0])
    # Multipunto, línea o polígono: centro aproximado de todos los vértices
    planos: list[list[float]] = []

    def aplanar(c: Any) -> None:
        if isinstance(c, list) and c and isinstance(c[0], (int, float)):
            planos.append(c)
        elif isinstance(c, list):
            for x in c:
                aplanar(x)

    aplanar(coords)
    if not planos:
        return None
    return sum(p[1] for p in planos) / len(planos), sum(p[0] for p in planos) / len(planos)


def _archivos() -> list[Path]:
    rutas: list[Path] = []
    for carpeta in CARPETAS:
        rutas += sorted(carpeta.glob("paradas_taxi*.geojson")) + sorted(carpeta.glob("paradas_taxi*.json"))
    return rutas


def cargar_paradas() -> list[dict[str, Any]]:
    """Lee y normaliza todas las paradas disponibles (con caché por fecha de modificación)."""
    rutas = _archivos()
    firma = tuple((str(r), r.stat().st_mtime) for r in rutas)
    if firma == _cache["firma"]:
        return _cache["paradas"]

    paradas: list[dict[str, Any]] = []
    vistas: set[tuple[float, float]] = set()
    for ruta in rutas:
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("No se pudo leer %s: %s", ruta.name, exc)
            continue
        capa = re.search(r"(\d)", ruta.stem)
        horario = HORARIO_CAPA.get(capa.group(1), "") if capa else ""
        for f in datos.get("features", []):
            props = f.get("properties") or f.get("attributes") or {}
            punto = _punto(f.get("geometry"))
            if not punto:
                continue
            lat, lon = punto
            if not (MADRID_LAT[0] <= lat <= MADRID_LAT[1] and MADRID_LON[0] <= lon <= MADRID_LON[1]):
                continue  # fuera de Madrid o en coordenadas UTM (pedid outSR=4326)
            clave = (round(lat, 5), round(lon, 5))
            if clave in vistas:
                continue
            vistas.add(clave)
            paradas.append({"lat": lat, "lon": lon, "nombre": _texto(props), "plazas": _plazas(props),
                            "horario": horario})

    _cache.update(firma=firma, paradas=paradas)
    if rutas:
        log.info("Paradas de taxi cargadas: %d (de %d archivos)", len(paradas), len(rutas))
    return paradas


def paradas_cercanas(lat: float, lon: float, n: int = 3) -> list[dict[str, Any]]:
    resultado = []
    for p in cargar_paradas():
        km = distancia_km(lat, lon, p["lat"], p["lon"])
        resultado.append({**p, "distancia_m": round(km * 1000),
                          "a_pie_min": max(1, round(km / VELOCIDAD_A_PIE_KMH * 60))})
    return sorted(resultado, key=lambda p: p["distancia_m"])[:n]
