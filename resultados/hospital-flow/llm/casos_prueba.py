"""
Casos de prueba del triaje (reglas + LLM)
=========================================

Ejecutar:   python -m llm.casos_prueba          (usa el LLM si hay API key en .env)
            python -m llm.casos_prueba --reglas  (solo reglas)

"esperado" admite varios niveles válidos, porque algunos casos son frontera.
"""
from __future__ import annotations

import sys
import time

from core import ingestion, processing, triaje
from llm import cliente

# (frase, niveles válidos, especialidad esperada o None si da igual)
CASOS: list[tuple[str, set[str], str | None]] = [
    ("me duele el pecho y no puedo respirar", {"emergencia"}, None),
    ("necesito operarme la rodilla", {"programada"}, "Traumatología"),
    ("mi hija tiene fiebre alta desde ayer", {"urgente"}, "Pediatría"),
    ("me he torcido el tobillo jugando al futbol", {"urgente", "leve"}, "Traumatología"),
    ("tengo una tos que no se me quita y me silva el pecho", {"urgente", "leve"}, "Neumología"),
    ("mi padre tiene la cara torcida y no puede hablar bien", {"emergencia"}, None),
    ("me cai de la bici y creo que me e roto la muñeca", {"urgente"}, "Traumatología"),
    ("llevo dos dias vomitando y con diarrea", {"urgente"}, "Digestivo"),
    ("tengo que operarme de la cadera, estoy en lista de espera", {"programada"}, "Traumatología"),
    ("me duele mucho la cabeza desde esta mañana", {"urgente", "leve"}, "Neurología"),
    ("mi bebe no para de llorar y tiene 39 de fiebre", {"urgente"}, "Pediatría"),
    ("noto palpitaciones muy fuertes y me mareo", {"urgente", "emergencia"}, "Cardiología"),
    ("me he cortado con un cuchillo y sangra mucho", {"urgente", "emergencia"}, None),
    ("tengo un dolor de barriga muy fuerte en el lado derecho", {"urgente"}, "Digestivo"),
    ("me pica la garganta y tengo un poco de mocos", {"leve"}, None),
    ("me han dicho que me tienen que poner una protesis de rodilla", {"programada"}, "Traumatología"),
    ("mi abuelo se ha desmayado y no responde", {"emergencia"}, None),
    ("creo que tengo un esguince en el tobillo", {"urgente", "leve"}, "Traumatología"),
    ("me duele la espalda desde hace una semana", {"leve"}, "Traumatología"),
    ("tengo asma y hoy me cuesta mas respirar de lo normal", {"urgente", "emergencia"}, "Neumología"),
]


def main() -> None:
    usar_llm = "--reglas" not in sys.argv and cliente.disponible()
    registros, _ = ingestion.obtener_datos_hospitales()
    df = processing.aplanar_hospitales(registros)
    especialidades = sorted({e for fila in df["especialidades"] for e in fila.split("; ")} - {"Urgencias generales"})

    print(f"Modo: {'LLM + reglas (' + cliente.MODELO + ')' if usar_llm else 'solo reglas'}\n")
    print(f"{'OK':3} {'Frase':58} {'Nivel':11} {'Especialidad':14} {'Fuente':11} {'ms':>5}")
    print("-" * 108)
    aciertos = 0
    for frase, niveles, esp in CASOS:
        t0 = time.perf_counter()
        r = triaje.analizar(frase, especialidades, usar_llm=usar_llm)
        ms = (time.perf_counter() - t0) * 1000
        ok = r["nivel"] in niveles and (esp is None or r["especialidad"] == esp)
        aciertos += ok
        print(f"{'✔' if ok else '✘':3} {frase[:58]:58} {r['nivel']:11} {str(r['especialidad'] or '-'):14} "
              f"{r['fuente']:11} {ms:5.0f}")
    print("-" * 108)
    print(f"Aciertos: {aciertos}/{len(CASOS)}")


if __name__ == "__main__":
    main()
