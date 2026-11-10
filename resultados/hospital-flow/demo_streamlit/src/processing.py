"""
Capa de procesamiento y lógica - Hospital Flow
==============================================

  1. Limpieza y aplanado de los datos (anidados) que devuelve la ingesta.
  2. Algoritmo de recomendación (espera + ocupación + distancia).
  3. Orientación de síntomas (triaje basado en reglas, NO es diagnóstico médico).
  4. Gestión de citas (crear, listar, modificar y cancelar) persistida en JSON.
"""
from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

# --------------------------------------------------------------------------- #
# Constantes
# --------------------------------------------------------------------------- #
UMBRAL_MEDIA = 60.0   # % de ocupación a partir del cual el nivel es "Media"
UMBRAL_ALTA = 85.0    # % de ocupación a partir del cual el nivel es "Alta"
COLORES_NIVEL = {"Baja": "#2ecc71", "Media": "#f1c40f", "Alta": "#e74c3c"}
VELOCIDAD_MEDIA_KMH = 30.0  # velocidad media urbana para estimar el tiempo de viaje
PENALIZACION_SIN_ESPECIALIDAD = 0.15

AVISO_LEGAL = (
    "Esta orientación es meramente informativa y no sustituye el diagnóstico ni el "
    "consejo de un profesional sanitario."
)


# --------------------------------------------------------------------------- #
# 1. Limpieza y aplanado
# --------------------------------------------------------------------------- #
def clasificar_ocupacion(pct: float) -> str:
    """Baja (<60 %), Media (60-85 %) o Alta (>=85 %)."""
    if pct < UMBRAL_MEDIA:
        return "Baja"
    if pct < UMBRAL_ALTA:
        return "Media"
    return "Alta"


def aplanar_hospitales(registros: list[dict[str, Any]]) -> pd.DataFrame:
    """Aplana los registros anidados, limpia tipos/valores y añade el nivel de ocupación."""
    if not registros:
        raise ValueError("No hay datos de hospitales que procesar.")

    df = pd.json_normalize(registros, sep="_")
    df = df.rename(columns={
        "ubicacion_direccion": "direccion",
        "ubicacion_lat": "lat",
        "ubicacion_lon": "lon",
        "capacidad_camas_urgencias": "camas_urgencias",
        "tiempo_real_ocupacion_pct": "ocupacion_pct",
        "tiempo_real_camas_disponibles": "camas_disponibles",
        "tiempo_real_espera_min": "espera_min",
        "tiempo_real_pacientes_espera": "pacientes_espera",
        "tiempo_real_actualizado": "actualizado",
    })

    for col in ("id", "nombre", "lat", "lon"):
        if col not in df.columns:
            raise ValueError(f"Falta la columna obligatoria '{col}' en los datos.")

    # Textos
    df["nombre"] = df["nombre"].astype(str).str.strip()
    if "direccion" not in df.columns:
        df["direccion"] = "Comunidad de Madrid"
    df["direccion"] = df["direccion"].fillna("Comunidad de Madrid").astype(str).str.strip()
    if "especialidades" in df.columns:
        df["especialidades"] = df["especialidades"].apply(
            lambda v: "; ".join(v) if isinstance(v, list) else (str(v) if v else "Urgencias generales")
        )
    else:
        df["especialidades"] = "Urgencias generales"
    if "actualizado" not in df.columns:
        df["actualizado"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Numéricos
    for col in ("lat", "lon", "camas_urgencias", "ocupacion_pct", "camas_disponibles", "espera_min", "pacientes_espera"):
        if col not in df.columns:
            df[col] = float("nan")
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["nombre", "lat", "lon"]).drop_duplicates(subset="id").reset_index(drop=True)

    df["camas_urgencias"] = df["camas_urgencias"].fillna(60).clip(lower=1)
    df["ocupacion_pct"] = df["ocupacion_pct"].fillna(df["ocupacion_pct"].median()).fillna(50).clip(0, 100)
    estimadas = (df["camas_urgencias"] * (1 - df["ocupacion_pct"] / 100)).round()
    df["camas_disponibles"] = df["camas_disponibles"].fillna(estimadas)
    df["camas_disponibles"] = df[["camas_disponibles", "camas_urgencias"]].min(axis=1).clip(lower=0)
    df["espera_min"] = df["espera_min"].fillna(df["espera_min"].median()).fillna(30).clip(lower=0)
    df["pacientes_espera"] = df["pacientes_espera"].fillna((df["espera_min"] / 6).round()).clip(lower=0)

    for col in ("camas_urgencias", "camas_disponibles", "espera_min", "pacientes_espera"):
        df[col] = df[col].round().astype(int)
    df["ocupacion_pct"] = df["ocupacion_pct"].round(1)
    df["nivel_ocupacion"] = df["ocupacion_pct"].apply(clasificar_ocupacion)
    return df


# --------------------------------------------------------------------------- #
# 2. Algoritmo de recomendación
# --------------------------------------------------------------------------- #
def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en línea recta (fórmula de Haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _minmax(serie: pd.Series) -> pd.Series:
    rango = serie.max() - serie.min()
    if rango == 0:
        return serie * 0.0
    return (serie - serie.min()) / rango


def _normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar textos."""
    texto = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in texto if unicodedata.category(c) != "Mn").lower()


def recomendar_hospitales(
    df: pd.DataFrame,
    lat: float,
    lon: float,
    w_espera: float = 4,
    w_ocupacion: float = 3,
    w_distancia: float = 3,
    especialidad: str | None = None,
) -> pd.DataFrame:
    """
    Ordena los hospitales de mejor a peor.

    score = 100 * (1 - penalización), donde la penalización es la media ponderada
    de tres factores normalizados (min-max) entre 0 y 1:
        tiempo de espera, ocupación y distancia.
    Si se indica una especialidad, los hospitales que no la tienen reciben una
    penalización adicional fija.
    """
    if df.empty:
        return df.copy()

    out = df.copy()
    out["distancia_km"] = out.apply(lambda r: distancia_km(lat, lon, r["lat"], r["lon"]), axis=1).round(1)
    out["viaje_min"] = (out["distancia_km"] / VELOCIDAD_MEDIA_KMH * 60).round().astype(int)

    pesos = [max(0.0, float(w_espera)), max(0.0, float(w_ocupacion)), max(0.0, float(w_distancia))]
    total = sum(pesos)
    if total == 0:
        pesos, total = [1.0, 1.0, 1.0], 3.0
    pe, po, pd_ = (p / total for p in pesos)

    penalizacion = (
        pe * _minmax(out["espera_min"].astype(float))
        + po * _minmax(out["ocupacion_pct"].astype(float))
        + pd_ * _minmax(out["distancia_km"].astype(float))
    )

    if especialidad and especialidad != "General":
        objetivo = _normalizar(especialidad)
        tiene = out["especialidades"].apply(lambda s: objetivo in _normalizar(s))
        penalizacion = penalizacion + (~tiene) * PENALIZACION_SIN_ESPECIALIDAD
        out["tiene_especialidad"] = tiene
    else:
        out["tiene_especialidad"] = True

    out["score"] = ((1 - penalizacion.clip(0, 1)) * 100).round(1)
    out["total_estimado_min"] = out["espera_min"] + out["viaje_min"]
    out = out.sort_values(["score", "distancia_km"], ascending=[False, True]).reset_index(drop=True)
    out["ranking"] = out.index + 1
    return out


# --------------------------------------------------------------------------- #
# 3. Orientación de síntomas (reglas; no es diagnóstico)
# --------------------------------------------------------------------------- #
CLAVES_CRISIS = (
    "suicid", "quitarme la vida", "quitarse la vida", "no quiero vivir", "hacerme dano", "hacerme daño",
)
CLAVES_EMERGENCIA = (
    "dolor de pecho", "dolor en el pecho", "opresion en el pecho", "no puedo respirar", "me ahogo",
    "inconsciente", "perdida de conocimiento", "desmayo", "convulsion", "hemorragia", "sangrado abundante",
    "ictus", "derrame cerebral", "cara torcida", "no puedo hablar", "habla arrastrada", "paralisis",
    "sobredosis", "atragant", "anafilaxia", "reaccion alergica grave", "hinchazon de garganta",
    "quemadura grave", "no responde",
)
CLAVES_URGENTE = (
    "fiebre alta", "fractura", "hueso roto", "vomito", "dolor abdominal", "dolor fuerte", "herida profunda",
    "corte profundo", "mareo intenso", "quemadura", "deshidrat", "sangre en", "dificultad para respirar",
    "falta de aire", "palpitacion", "golpe en la cabeza", "dolor intenso", "fiebre", "esguince", "infeccion",
)
CLAVES_ESPECIALIDAD = {
    "Pediatría": ("mi hijo", "mi hija", "bebe", "nino", "nina", "lactante"),
    "Cardiología": ("pecho", "palpitacion", "taquicardia", "presion arterial", "corazon"),
    "Neurología": ("cabeza", "migrana", "mareo", "ictus", "convulsion", "hormigueo", "cara torcida", "habla"),
    "Traumatología": ("fractura", "hueso", "esguince", "torcedura", "golpe", "rodilla", "tobillo", "muneca", "espalda", "caida"),
    "Neumología": ("tos", "respirar", "asma", "falta de aire", "silbido"),
    "Digestivo": ("abdominal", "barriga", "estomago", "vomito", "diarrea", "nausea"),
}


def _contiene(texto: str, clave: str) -> bool:
    """Coincidencia por inicio de palabra (palabra completa si la clave es muy corta)."""
    patron = rf"\b{re.escape(clave)}\b" if len(clave) <= 4 else rf"\b{re.escape(clave)}"
    return re.search(patron, texto) is not None


def orientar_sintomas(texto: str) -> dict[str, Any]:
    """
    Devuelve un dict con: nivel ('sin_datos' | 'leve' | 'urgente' | 'emergencia'),
    crisis (bool), especialidad (str | None), coincidencias (list[str]) y mensaje (str).
    """
    t = _normalizar(texto).strip()
    if not t:
        return {"nivel": "sin_datos", "crisis": False, "especialidad": None, "coincidencias": [], "mensaje": ""}

    crisis = [c for c in CLAVES_CRISIS if _contiene(t, _normalizar(c))]
    emergencia = [c for c in CLAVES_EMERGENCIA if _contiene(t, c)]
    urgente = [c for c in CLAVES_URGENTE if _contiene(t, c)]

    puntos = {esp: sum(_contiene(t, k) for k in claves) for esp, claves in CLAVES_ESPECIALIDAD.items()}
    especialidad = None
    if puntos["Pediatría"] > 0:
        especialidad = "Pediatría"
    else:
        mejor, valor = max(puntos.items(), key=lambda kv: kv[1])
        especialidad = mejor if valor > 0 else None

    if crisis:
        nivel = "emergencia"
        mensaje = (
            "Siento mucho que estés pasando por esto, y es importante que no lo afrontes a solas. "
            "Si estás en peligro inmediato, **llama ya al 112**. También puedes llamar al **024** "
            "(línea de atención a la conducta suicida, gratuita y 24 horas). Si puedes, avisa a alguien "
            "de confianza para que se quede contigo."
        )
        coincidencias = crisis
    elif emergencia:
        nivel = "emergencia"
        mensaje = (
            "Los síntomas descritos podrían indicar una **emergencia**. **Llama al 112 ahora** y sigue "
            "sus instrucciones. No conduzcas tú mismo/a hasta el hospital."
        )
        coincidencias = emergencia
    elif urgente:
        nivel = "urgente"
        mensaje = (
            "Los síntomas aconsejan que te **valore un médico hoy**. Acude a urgencias en las próximas "
            "horas; si empeoras o aparece dolor en el pecho, dificultad intensa para respirar o pérdida "
            "de conocimiento, llama al 112."
        )
        coincidencias = urgente
    else:
        nivel = "leve"
        mensaje = (
            "Por lo que cuentas, no parece una urgencia vital. Puedes pedir cita en tu **centro de salud**, "
            "consultar en tu farmacia y vigilar la evolución. Si empeora o aparecen síntomas nuevos, acude a urgencias."
        )
        coincidencias = []

    return {
        "nivel": nivel,
        "crisis": bool(crisis),
        "especialidad": especialidad,
        "coincidencias": coincidencias,
        "mensaje": mensaje,
    }


def respuesta_chat(triaje: dict[str, Any], mejor_hospital: pd.Series | None) -> str:
    """Construye la respuesta (markdown) del asistente simulado de triaje."""
    nivel = triaje["nivel"]
    if nivel == "sin_datos":
        return ("Cuéntame qué síntomas tienes (por ejemplo: *«fiebre y dolor de garganta desde ayer»*) "
                "y te daré una orientación inicial.")

    partes = [triaje["mensaje"]]
    if triaje["especialidad"] and nivel in ("urgente", "leve") and not triaje["crisis"]:
        partes.append(f"🩺 Área orientativa: **{triaje['especialidad']}**.")
    if nivel == "urgente" and mejor_hospital is not None:
        partes.append(
            f"🏥 Ahora mismo, el hospital con mejor equilibrio entre espera, ocupación y distancia es "
            f"**{mejor_hospital['nombre']}** (espera estimada {int(mejor_hospital['espera_min'])} min, "
            f"ocupación {mejor_hospital['ocupacion_pct']} %, a {mejor_hospital['distancia_km']} km)."
        )
    partes.append(f"_{AVISO_LEGAL}_")
    return "\n\n".join(partes)


# --------------------------------------------------------------------------- #
# 4. Gestión de citas (persistencia en JSON)
# --------------------------------------------------------------------------- #
CITAS_PATH = Path(os.getenv("HOSPITAL_FLOW_CITAS", Path(__file__).resolve().parent.parent / "data" / "citas.json"))
ESTADO_CONFIRMADA = "Confirmada"
ESTADO_CANCELADA = "Cancelada"


def _cargar_citas() -> list[dict[str, Any]]:
    if not CITAS_PATH.exists():
        return []
    try:
        with CITAS_PATH.open("r", encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _guardar_citas(citas: list[dict[str, Any]]) -> None:
    CITAS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CITAS_PATH.open("w", encoding="utf-8") as f:
        json.dump(citas, f, indent=2, ensure_ascii=False)


def _validar_fecha_hora(fecha: date, hora: time) -> None:
    if datetime.combine(fecha, hora) < datetime.now():
        raise ValueError("La fecha y hora de la cita no pueden estar en el pasado.")


def crear_cita(
    hospital_id: str,
    hospital_nombre: str,
    paciente: str,
    fecha: date,
    hora: time,
    motivo: str = "",
) -> dict[str, Any]:
    """Crea y guarda una cita. Lanza ValueError si los datos no son válidos."""
    paciente = (paciente or "").strip()
    if not paciente:
        raise ValueError("Indica el nombre del paciente.")
    _validar_fecha_hora(fecha, hora)

    citas = _cargar_citas()
    hora_txt = hora.strftime("%H:%M")
    for c in citas:
        if (c["estado"] == ESTADO_CONFIRMADA and c["hospital_id"] == hospital_id
                and c["fecha"] == fecha.isoformat() and c["hora"] == hora_txt
                and _normalizar(c["paciente"]) == _normalizar(paciente)):
            raise ValueError("Ya existe una cita confirmada para ese paciente, hospital, fecha y hora.")

    cita = {
        "id": uuid4().hex[:8],
        "hospital_id": hospital_id,
        "hospital": hospital_nombre,
        "paciente": paciente,
        "fecha": fecha.isoformat(),
        "hora": hora_txt,
        "motivo": (motivo or "").strip() or "Consulta de urgencias",
        "estado": ESTADO_CONFIRMADA,
        "creada": datetime.now().isoformat(timespec="seconds"),
    }
    citas.append(cita)
    _guardar_citas(citas)
    return cita


def listar_citas(solo_activas: bool = False) -> list[dict[str, Any]]:
    """Lista las citas ordenadas por fecha y hora."""
    citas = _cargar_citas()
    if solo_activas:
        citas = [c for c in citas if c["estado"] == ESTADO_CONFIRMADA]
    return sorted(citas, key=lambda c: (c["fecha"], c["hora"]))


def cancelar_cita(cita_id: str) -> dict[str, Any]:
    """Marca una cita como cancelada."""
    citas = _cargar_citas()
    for c in citas:
        if c["id"] == cita_id:
            if c["estado"] == ESTADO_CANCELADA:
                raise ValueError("La cita ya estaba cancelada.")
            c["estado"] = ESTADO_CANCELADA
            _guardar_citas(citas)
            return c
    raise ValueError("Cita no encontrada.")


def modificar_cita(
    cita_id: str,
    fecha: date | None = None,
    hora: time | None = None,
    motivo: str | None = None,
) -> dict[str, Any]:
    """Modifica fecha, hora y/o motivo de una cita confirmada."""
    citas = _cargar_citas()
    for c in citas:
        if c["id"] == cita_id:
            if c["estado"] != ESTADO_CONFIRMADA:
                raise ValueError("Solo se pueden modificar citas confirmadas.")
            nueva_fecha = fecha or date.fromisoformat(c["fecha"])
            nueva_hora = hora or datetime.strptime(c["hora"], "%H:%M").time()
            _validar_fecha_hora(nueva_fecha, nueva_hora)
            c["fecha"] = nueva_fecha.isoformat()
            c["hora"] = nueva_hora.strftime("%H:%M")
            if motivo is not None:
                c["motivo"] = motivo.strip() or c["motivo"]
            _guardar_citas(citas)
            return c
    raise ValueError("Cita no encontrada.")
