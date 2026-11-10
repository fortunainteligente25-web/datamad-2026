"""
Perfilado y limpieza de datos · Hospital Flow
=============================================

1) Perfilar (no cambia nada, solo informa):
       python data/limpieza.py
   Lee todos los CSV / Excel / JSON de data/raw/ y saca un informe por pantalla:
   filas, columnas, tipos, nulos, duplicados, columnas numéricas guardadas como texto,
   coordenadas fuera de Madrid...

2) Limpiar (limpieza genérica y segura):
       python data/limpieza.py --limpiar
   Escribe cada archivo limpio en data/clean/<nombre>.csv y el registro de cambios
   en docs/informe_limpieza.md. Lo específico de cada dataset (qué columna es qué,
   cómo se llaman las especialidades...) se añade en MAPEOS cuando veamos los datos.

Reglas: los originales de data/raw/ NO se tocan y los nulos NO se inventan.
"""
from __future__ import annotations

import csv
import io
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
RAW = RAIZ / "data" / "raw"
CLEAN = RAIZ / "data" / "clean"
INFORME = RAIZ / "docs" / "informe_limpieza.md"
EXTENSIONES = {".csv", ".txt", ".xlsx", ".xls", ".json"}
MADRID_LAT, MADRID_LON = (39.8, 41.2), (-4.7, -3.0)

# Especialidades: variante (sin tildes, minúsculas) -> nombre oficial de la lista cerrada.
# La lista cerrada es la misma que usa el LLM (sale de los datos de hospitales).
ESPECIALIDADES = {
    "traumatologia": "Traumatología", "traumatologia y cirugia ortopedica": "Traumatología",
    "cot": "Traumatología", "cirugia ortopedica y traumatologia": "Traumatología",
    "cardiologia": "Cardiología", "neurologia": "Neurología", "neumologia": "Neumología",
    "digestivo": "Digestivo", "aparato digestivo": "Digestivo", "gastroenterologia": "Digestivo",
    "pediatria": "Pediatría", "urgencias pediatricas": "Pediatría",
}
# Mapeos específicos por archivo (se rellenan al ver datos_originales)
MAPEOS: dict[str, dict] = {}


# --------------------------------------------------------------------------- #
# Lectura robusta (codificación y separador)
# --------------------------------------------------------------------------- #
def leer(ruta: Path) -> pd.DataFrame:
    ext = ruta.suffix.lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(ruta)
    if ext == ".json":
        return pd.json_normalize(pd.read_json(ruta).to_dict(orient="records"))
    bruto = ruta.read_bytes()
    for codificacion in ("utf-8-sig", "latin-1"):
        try:
            texto = bruto.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    try:
        separador = csv.Sniffer().sniff(texto[:5000], delimiters=";,\t|").delimiter
    except csv.Error:
        separador = ";" if texto[:5000].count(";") > texto[:5000].count(",") else ","
    return pd.read_csv(io.StringIO(texto), sep=separador, dtype=str, keep_default_na=True)


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def sin_tildes(texto: str) -> str:
    texto = unicodedata.normalize("NFD", str(texto))
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def snake(nombre: str) -> str:
    nombre = re.sub(r"[^0-9a-zA-Z]+", "_", sin_tildes(nombre).strip().lower())
    return re.sub(r"_+", "_", nombre).strip("_") or "columna"


def a_numero(serie: pd.Series) -> pd.Series:
    """'1.234,5' -> 1234.5 · '12,5' -> 12.5 · '40.4' -> 40.4"""
    s = serie.astype(str).str.strip().replace({"": None, "nan": None, "None": None, "-": None})
    con_ambos = s.str.contains(r"\.", na=False) & s.str.contains(",", na=False)
    s = s.where(~con_ambos, s.str.replace(".", "", regex=False))
    return pd.to_numeric(s.str.replace(",", ".", regex=False), errors="coerce")


def es_texto(serie: pd.Series) -> bool:
    """True para columnas de texto (object en pandas 2, str/string en pandas 3)."""
    return pd.api.types.is_object_dtype(serie) or pd.api.types.is_string_dtype(serie)


def es_numerica(serie: pd.Series, umbral: float = 0.9) -> bool:
    no_nulos = serie.dropna().astype(str).str.strip()
    no_nulos = no_nulos[no_nulos != ""]
    if no_nulos.empty:
        return False
    return a_numero(no_nulos).notna().mean() >= umbral


def columnas_coordenadas(df: pd.DataFrame) -> tuple[str | None, str | None]:
    lat = next((c for c in df.columns if re.fullmatch(r"(lat|latitud|latitude|y)", snake(c))), None)
    lon = next((c for c in df.columns if re.fullmatch(r"(lon|lng|long|longitud|longitude|x)", snake(c))), None)
    return lat, lon


# --------------------------------------------------------------------------- #
# Perfilado
# --------------------------------------------------------------------------- #
def perfilar(df: pd.DataFrame, nombre: str) -> str:
    lineas = [f"\n=== {nombre} ===", f"Filas: {len(df):,} · Columnas: {df.shape[1]} · "
              f"Duplicadas exactas: {int(df.duplicated().sum()):,}"]
    lineas.append(f"{'columna':32} {'tipo':8} {'nulos':>7} {'únicos':>7}  ejemplo / aviso")
    for col in df.columns:
        serie = df[col]
        nulos = serie.isna().mean() * 100
        avisos = []
        if es_texto(serie) and es_numerica(serie):
            avisos.append("número guardado como texto")
        if es_texto(serie) and serie.dropna().astype(str).str.match(r"^\s|.*\s$").any():
            avisos.append("espacios sobrantes")
        ejemplo = str(serie.dropna().iloc[0])[:28] if serie.notna().any() else "—"
        lineas.append(f"{str(col)[:32]:32} {str(serie.dtype)[:8]:8} {nulos:6.1f}% {serie.nunique():7,}  "
                      f"{ejemplo}{'  ⚠ ' + ', '.join(avisos) if avisos else ''}")
    lat, lon = columnas_coordenadas(df)
    if lat and lon:
        la, lo = a_numero(df[lat]), a_numero(df[lon])
        fuera = (~la.between(*MADRID_LAT) | ~lo.between(*MADRID_LON)) & la.notna()
        cambiadas = la.between(*MADRID_LON) & lo.between(*MADRID_LAT)
        lineas.append(f"Coordenadas ({lat}, {lon}): {int(fuera.sum())} fuera de Madrid · "
                      f"{int(cambiadas.sum())} parecen lat/lon cambiadas · valores >180 = UTM (EPSG:25830)")
    return "\n".join(lineas)


# --------------------------------------------------------------------------- #
# Limpieza genérica
# --------------------------------------------------------------------------- #
def limpiar(df: pd.DataFrame, nombre: str) -> tuple[pd.DataFrame, list[str]]:
    cambios: list[str] = []
    n0 = len(df)

    df = df.rename(columns={c: snake(c) for c in df.columns})
    cambios.append("Nombres de columnas en snake_case (sin tildes ni espacios).")

    for col in df.columns:
        if es_texto(df[col]):
            df[col] = df[col].astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
            df[col] = df[col].replace({"": pd.NA})
    cambios.append("Textos sin espacios sobrantes; celdas vacías como nulo (no se inventan valores).")

    numericas = [c for c in df.columns if es_texto(df[c]) and es_numerica(df[c])]
    for col in numericas:
        df[col] = a_numero(df[col])
    if numericas:
        cambios.append(f"Convertidas a número (coma decimal → punto): {', '.join(numericas)}.")

    for col in [c for c in df.columns if "especialidad" in c or "servicio" in c]:
        antes = df[col].copy()
        df[col] = df[col].map(lambda v: ESPECIALIDADES.get(sin_tildes(v).lower().strip(), v) if pd.notna(v) else v)
        n = int((antes.fillna("") != df[col].fillna("")).sum())
        if n:
            cambios.append(f"Columna '{col}': {n} valor(es) unificado(s) a la lista cerrada de especialidades.")

    lat, lon = columnas_coordenadas(df)
    if lat and lon:
        la, lo = pd.to_numeric(df[lat], errors="coerce"), pd.to_numeric(df[lon], errors="coerce")
        cambiadas = la.between(*MADRID_LON) & lo.between(*MADRID_LAT)
        if cambiadas.any():
            df.loc[cambiadas, [lat, lon]] = df.loc[cambiadas, [lon, lat]].to_numpy()
            cambios.append(f"{int(cambiadas.sum())} fila(s) con latitud y longitud intercambiadas, corregidas.")
        la, lo = pd.to_numeric(df[lat], errors="coerce"), pd.to_numeric(df[lon], errors="coerce")
        fuera = ~(la.between(*MADRID_LAT) & lo.between(*MADRID_LON))
        if fuera.any():
            df = df[~fuera]
            cambios.append(f"{int(fuera.sum())} fila(s) eliminada(s): sin coordenadas o fuera de la Comunidad de Madrid.")

    duplicadas = int(df.duplicated().sum())
    if duplicadas:
        df = df.drop_duplicates()
        cambios.append(f"{duplicadas} fila(s) duplicada(s) eliminada(s).")

    cambios.append(f"Filas: {n0:,} → {len(df):,}.")
    return df.reset_index(drop=True), cambios


# --------------------------------------------------------------------------- #
def main() -> None:
    archivos = [r for r in sorted(RAW.iterdir()) if r.suffix.lower() in EXTENSIONES and not r.name.startswith("paradas_taxi")]
    if not archivos:
        print(f"No hay datos en {RAW}. Copia ahí datos_originales (CSV, Excel o JSON).")
        return
    hacer_limpieza = "--limpiar" in sys.argv
    informe = [f"# Informe de limpieza\n\nGenerado: {datetime.now():%Y-%m-%d %H:%M}\n"]
    for ruta in archivos:
        try:
            df = leer(ruta)
        except Exception as exc:  # archivo ilegible: se informa y se sigue
            print(f"\n=== {ruta.name} ===\nNo se pudo leer: {exc}")
            continue
        print(perfilar(df, ruta.name))
        if hacer_limpieza:
            limpio, cambios = limpiar(df, ruta.stem)
            CLEAN.mkdir(parents=True, exist_ok=True)
            destino = CLEAN / f"{snake(ruta.stem)}.csv"
            limpio.to_csv(destino, index=False)
            informe.append(f"## {ruta.name} → data/clean/{destino.name}\n" + "\n".join(f"- {c}" for c in cambios) + "\n")
            print(f"→ Guardado {destino.relative_to(RAIZ)}")
    if hacer_limpieza:
        INFORME.parent.mkdir(parents=True, exist_ok=True)
        INFORME.write_text("\n".join(informe), encoding="utf-8")
        print(f"\nInforme: {INFORME.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
