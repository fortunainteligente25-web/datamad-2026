"""
Capa de adquisición de datos - Hospital Flow
============================================

Responsabilidades:
  1. Conectar con una fuente de datos abiertos de hospitales / centros de salud
     (portal de datos abiertos de la Comunidad de Madrid u otro endpoint JSON/GeoJSON).
  2. Si la fuente no está configurada o falla, usar un catálogo local de referencia.
  3. Simular datos "en tiempo real" (ocupación, camas libres, tiempos de espera),
     ya que ninguna fuente abierta publica estas métricas en vivo.

Todos los datos de ocupación y espera son SINTÉTICOS. Los valores de camas del
catálogo local son ilustrativos, no cifras oficiales.

Para usar una fuente abierta real, define la variable de entorno:
    HOSPITAL_FLOW_OPEN_DATA_URL=https://.../recurso.json
El endpoint puede devolver una lista JSON, un objeto con claves habituales
("records", "@graph", "data", "results", "items", "result") o un GeoJSON.
"""
from __future__ import annotations

import hashlib
import math
import os
import random
from copy import deepcopy
from datetime import datetime
from typing import Any

import requests

OPEN_DATA_URL: str = os.getenv("HOSPITAL_FLOW_OPEN_DATA_URL", "").strip()
REQUEST_TIMEOUT_S: int = 8

# Caja aproximada de la Comunidad de Madrid (para descartar registros fuera de ámbito)
MADRID_LAT_RANGE = (39.8, 41.2)
MADRID_LON_RANGE = (-4.7, -3.0)

CATALOGO_LOCAL: list[dict[str, Any]] = [
    {
        "id": "H-LAPAZ",
        "nombre": "Hospital Universitario La Paz",
        "direccion": "Paseo de la Castellana, 261, Madrid",
        "lat": 40.4806, "lon": -3.6872,
        "camas_urgencias": 90,
        "especialidades": ["Urgencias generales", "Pediatría", "Cardiología", "Neurología", "Traumatología", "Neumología", "Digestivo"],
    },
    {
        "id": "H-12OCT",
        "nombre": "Hospital Universitario 12 de Octubre",
        "direccion": "Avenida de Córdoba, s/n, Madrid",
        "lat": 40.3752, "lon": -3.6975,
        "camas_urgencias": 85,
        "especialidades": ["Urgencias generales", "Pediatría", "Cardiología", "Neurología", "Traumatología", "Digestivo"],
    },
    {
        "id": "H-GREGMAR",
        "nombre": "Hospital General Universitario Gregorio Marañón",
        "direccion": "Calle del Doctor Esquerdo, 46, Madrid",
        "lat": 40.4189, "lon": -3.6706,
        "camas_urgencias": 80,
        "especialidades": ["Urgencias generales", "Pediatría", "Cardiología", "Traumatología", "Neumología", "Digestivo"],
    },
    {
        "id": "H-CLINICO",
        "nombre": "Hospital Clínico San Carlos",
        "direccion": "Calle del Profesor Martín Lagos, s/n, Madrid",
        "lat": 40.4410, "lon": -3.7191,
        "camas_urgencias": 60,
        "especialidades": ["Urgencias generales", "Cardiología", "Neurología", "Digestivo", "Neumología"],
    },
    {
        "id": "H-RYC",
        "nombre": "Hospital Universitario Ramón y Cajal",
        "direccion": "Carretera de Colmenar Viejo, km 9,100, Madrid",
        "lat": 40.4887, "lon": -3.6900,
        "camas_urgencias": 70,
        "especialidades": ["Urgencias generales", "Cardiología", "Neurología", "Traumatología", "Neumología"],
    },
    {
        "id": "H-FJD",
        "nombre": "Hospital Fundación Jiménez Díaz",
        "direccion": "Avenida de los Reyes Católicos, 2, Madrid",
        "lat": 40.4376, "lon": -3.7203,
        "camas_urgencias": 55,
        "especialidades": ["Urgencias generales", "Cardiología", "Traumatología", "Digestivo"],
    },
    {
        "id": "H-GETAFE",
        "nombre": "Hospital Universitario de Getafe",
        "direccion": "Carretera de Toledo, km 12,500, Getafe",
        "lat": 40.3010, "lon": -3.7140,
        "camas_urgencias": 45,
        "especialidades": ["Urgencias generales", "Pediatría", "Traumatología", "Neumología"],
    },
    {
        "id": "H-FUENLA",
        "nombre": "Hospital Universitario de Fuenlabrada",
        "direccion": "Camino del Molino, 2, Fuenlabrada",
        "lat": 40.2960, "lon": -3.8000,
        "camas_urgencias": 35,
        "especialidades": ["Urgencias generales", "Pediatría", "Traumatología"],
    },
    {
        "id": "H-PRINCIPE",
        "nombre": "Hospital Universitario Príncipe de Asturias",
        "direccion": "Carretera de Alcalá, s/n, Alcalá de Henares",
        "lat": 40.5127, "lon": -3.3498,
        "camas_urgencias": 40,
        "especialidades": ["Urgencias generales", "Pediatría", "Cardiología", "Traumatología"],
    },
    {
        "id": "H-INFANTA",
        "nombre": "Hospital Universitario Infanta Leonor",
        "direccion": "Avenida de la Gran Vía de Vallecas, s/n, Madrid",
        "lat": 40.3860, "lon": -3.6050,
        "camas_urgencias": 30,
        "especialidades": ["Urgencias generales", "Pediatría", "Digestivo"],
    },
]


# --------------------------------------------------------------------------- #
# Conexión con datos abiertos
# --------------------------------------------------------------------------- #
def _extraer_registros(payload: Any) -> list[dict[str, Any]]:
    """Extrae la lista de registros de las estructuras JSON más habituales."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for clave in ("records", "@graph", "data", "results", "items", "features", "result"):
            if clave in payload:
                return _extraer_registros(payload[clave])
    return []


def descargar_datos_abiertos(url: str | None = None, timeout: int = REQUEST_TIMEOUT_S) -> list[dict[str, Any]]:
    """Descarga registros en bruto desde un endpoint abierto (JSON / GeoJSON)."""
    url = (url or OPEN_DATA_URL).strip()
    if not url:
        raise ValueError("No hay URL de datos abiertos configurada (HOSPITAL_FLOW_OPEN_DATA_URL).")
    respuesta = requests.get(url, timeout=timeout, headers={"Accept": "application/json"})
    respuesta.raise_for_status()
    return _extraer_registros(respuesta.json())


def _primero(registro: dict[str, Any], claves: tuple[str, ...]) -> Any:
    """Devuelve el primer valor no vacío entre varias claves alternativas."""
    bajo = {str(k).lower(): v for k, v in registro.items()}
    for clave in claves:
        valor = bajo.get(clave)
        if valor not in (None, ""):
            return valor
    return None


def normalizar_registro_abierto(registro: dict[str, Any], idx: int) -> dict[str, Any] | None:
    """Convierte un registro externo al esquema base de catálogo (o None si no sirve)."""
    props = registro
    lat = lon = None
    if registro.get("type") == "Feature":  # GeoJSON
        props = dict(registro.get("properties") or {})
        coords = (registro.get("geometry") or {}).get("coordinates") or []
        if len(coords) >= 2:
            lon, lat = coords[0], coords[1]

    nombre = _primero(props, ("nombre", "name", "title", "centro", "denominacion"))
    lat = lat if lat is not None else _primero(props, ("lat", "latitude", "latitud"))
    lon = lon if lon is not None else _primero(props, ("lon", "lng", "long", "longitude", "longitud"))
    if nombre is None or lat is None or lon is None:
        return None
    try:
        lat = float(str(lat).replace(",", "."))
        lon = float(str(lon).replace(",", "."))
    except ValueError:
        return None
    if not (MADRID_LAT_RANGE[0] <= lat <= MADRID_LAT_RANGE[1] and MADRID_LON_RANGE[0] <= lon <= MADRID_LON_RANGE[1]):
        return None

    camas = _primero(props, ("camas_urgencias", "camas", "beds"))
    try:
        camas = max(1, int(float(camas)))
    except (TypeError, ValueError):
        camas = 60  # valor por defecto cuando la fuente no informa de camas

    return {
        "id": f"OD-{idx:03d}",
        "nombre": str(nombre).strip(),
        "direccion": str(_primero(props, ("direccion", "dirección", "address", "vial")) or "Comunidad de Madrid"),
        "lat": lat,
        "lon": lon,
        "camas_urgencias": camas,
        "especialidades": ["Urgencias generales"],
    }


def obtener_catalogo_base() -> tuple[list[dict[str, Any]], str]:
    """Catálogo de hospitales: datos abiertos si es posible, local en caso contrario."""
    nota_error = ""
    if OPEN_DATA_URL:
        try:
            registros = descargar_datos_abiertos()
            catalogo = []
            for i, reg in enumerate(registros):
                normalizado = normalizar_registro_abierto(reg, i)
                if normalizado:
                    catalogo.append(normalizado)
            if catalogo:
                return catalogo, "Datos abiertos (endpoint configurado) + simulación de tiempo real"
            nota_error = " (la fuente no devolvió registros utilizables)"
        except (requests.RequestException, ValueError) as exc:
            nota_error = f" (fuente abierta no disponible: {type(exc).__name__})"
    return deepcopy(CATALOGO_LOCAL), "Catálogo local de referencia + datos sintéticos" + nota_error


# --------------------------------------------------------------------------- #
# Simulación de datos en tiempo real
# --------------------------------------------------------------------------- #
def _semilla(texto: str) -> int:
    return int(hashlib.md5(texto.encode("utf-8")).hexdigest()[:12], 16)


def _carga_horaria(hora: float) -> float:
    """Carga base (0.45-0.85) con picos a media mañana (~11h) y por la tarde (~19h)."""
    pico_m = math.exp(-((hora - 11) ** 2) / (2 * 2.5 ** 2))
    pico_t = math.exp(-((hora - 19) ** 2) / (2 * 2.5 ** 2))
    return 0.45 + 0.40 * max(pico_m, pico_t)


def simular_tiempo_real(catalogo: list[dict[str, Any]], ahora: datetime | None = None) -> list[dict[str, Any]]:
    """
    Añade métricas sintéticas a cada hospital. Los valores son estables durante
    bloques de 5 minutos (misma semilla), de forma que la app no "parpadea".
    Devuelve registros ANIDADOS (como los de una API real) para que la capa de
    procesamiento tenga que aplanarlos.
    """
    ahora = ahora or datetime.now()
    hora = ahora.hour + ahora.minute / 60
    base = _carga_horaria(hora)
    bloque = int(ahora.timestamp() // 300)

    resultado: list[dict[str, Any]] = []
    for h in catalogo:
        sesgo = random.Random(_semilla(h["id"])).uniform(-0.12, 0.18)  # hospitales más/menos saturados
        rng = random.Random(_semilla(f"{h['id']}-{bloque}"))
        ocupacion = min(0.99, max(0.15, base + sesgo + rng.uniform(-0.07, 0.07)))

        camas_totales = int(h["camas_urgencias"])
        ocupadas = round(camas_totales * ocupacion)
        espera = round(8 + (ocupacion ** 3) * 200 * rng.uniform(0.85, 1.15))
        pacientes = max(0, round(espera / 6 + rng.uniform(-3, 3)))

        resultado.append({
            "id": h["id"],
            "nombre": h["nombre"],
            "especialidades": list(h["especialidades"]),
            "ubicacion": {"direccion": h["direccion"], "lat": h["lat"], "lon": h["lon"]},
            "capacidad": {"camas_urgencias": camas_totales},
            "tiempo_real": {
                "ocupacion_pct": round(ocupacion * 100, 1),
                "camas_disponibles": camas_totales - ocupadas,
                "espera_min": espera,
                "pacientes_espera": pacientes,
                "actualizado": ahora.strftime("%Y-%m-%d %H:%M:%S"),
            },
        })
    return resultado


def obtener_datos_hospitales(ahora: datetime | None = None) -> tuple[list[dict[str, Any]], str]:
    """Punto de entrada de la capa: devuelve (registros anidados, descripción de la fuente)."""
    catalogo, fuente = obtener_catalogo_base()
    return simular_tiempo_real(catalogo, ahora), fuente
