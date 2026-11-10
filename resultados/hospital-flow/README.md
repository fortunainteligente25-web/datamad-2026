# Hospital Flow · DATAMAD 2026

Web app para móvil: escribes qué te pasa ("necesito operarme la rodilla", "me he torcido el tobillo") y te dice **a qué hospital ir** según especialidad, cercanía y saturación. Además te ayuda a **llegar** (taxi), a **avisar a alguien** y a **llamar al 112**.

> Prototipo de hackathon. La ocupación y las esperas de urgencias son **simuladas**. Es una orientación, no un diagnóstico.

## Cómo funciona

```
mensaje ──► reglas de seguridad ──► LLM (extractor) ──► triaje ──► ranking (core/) ──► top 3 ──► LLM (explicador) ──► móvil
               │ emergencia o crisis: respuesta inmediata con 112 / 024, sin esperar al LLM
```

- **El LLM nunca elige el hospital.** Solo entiende el mensaje (especialidad + urgencia) y explica el resultado. El ranking es una fórmula transparente en `core/`.
- **Las reglas van siempre primero** y el LLM solo puede *subir* la gravedad, nunca bajarla.
- **Sin API key la app funciona igual**, solo con reglas.
- Más detalle para la memoria: [`docs/arquitectura.md`](docs/arquitectura.md).

## Estructura

```
api.py              API FastAPI + sirve el frontend
core/               lógica (viene de la demo en Streamlit)
  ingestion.py        catálogo de hospitales + simulación de ocupación
  processing.py       limpieza, ranking de urgencias, reglas de triaje, citas
  triaje.py           combina reglas + LLM
  programada.py       ranking para operaciones (listas de espera)
  taxis.py            emisoras de radio-taxi + paradas del Geoportal
llm/                LLM (Claude Haiku por defecto)
  extractor.py        mensaje → {especialidad, urgencia, procedimiento, resumen}
  explicador.py       top 3 → 2 frases (con plantilla si no hay LLM)
  prompts.py          todos los prompts
  casos_prueba.py     20 frases de prueba con tabla de resultados
data/raw/           datos originales (no se tocan)
data/clean/         datos limpios
data/limpieza.py    perfilado y limpieza
frontend/           web móvil: HTML + CSS + JS, sin build
docs/
  arquitectura.md     explicación para la memoria (flujo, decisiones, datos)
  pantallas.png       capturas de la app en el móvil
  prompt_hospital_flow.md   el prompt con el que se encargó la app
demo_streamlit/     la demo original en Streamlit, tal cual (de respaldo)
```

## Ejecutarlo (Windows, terminal de VS Code)

Requiere Python 3.10 o superior (`python --version`).

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # y pega tu ANTHROPIC_API_KEY dentro
python api.py
```

Abre http://localhost:8000 (la documentación de la API está en http://localhost:8000/docs).

> En Mac/Linux: `source venv/bin/activate` y `cp .env.example .env`.

## Probarlo en el móvil

- **Misma Wi-Fi:** abre `http://IP-DE-TU-PC:8000` en el móvil (la IP sale con `ipconfig`). Llamar, WhatsApp y SMS funcionan; el **GPS y la agenda de contactos no**, porque el navegador los exige con `https`.
- **Con https (recomendado para la demo):** instala [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) y ejecuta:
  ```powershell
  cloudflared tunnel --url http://localhost:8000
  ```
  Te da un enlace `https://...trycloudflare.com` para abrir en cualquier móvil. Haced un QR con él para la presentación.

## Probar el LLM

```powershell
python -m llm.casos_prueba            # con LLM si hay clave en .env
python -m llm.casos_prueba --reglas   # solo reglas (18/20 ahora mismo)
python -m llm.extractor "me he caido y me duele mucho la muñeca"
```

## Datos

1. Copiad los originales en `data/raw/` (por ejemplo `datos_originales.csv`).
2. Perfilado (no cambia nada):  `python data/limpieza.py`
3. Limpieza genérica:          `python data/limpieza.py --limpiar` → `data/clean/` + `docs/informe_limpieza.md`

**Listas de espera quirúrgica.** Si existe `data/clean/listas_espera.csv` con las columnas `hospital_id, especialidad, demora_media_dias`, el modo "operación programada" ordena por días de espera + distancia. Fuente: [Comunidad de Madrid](https://www.comunidad.madrid/salud/lista-espera-quirurgica) (consulta por hospital y especialidad, y por proceso).

**Paradas de taxi.** Desde la carpeta del proyecto, en PowerShell:

```powershell
$base = "https://sigma.madrid.es/hosted/rest/services/GEOPORTAL/RESERVAS_PLAZAS_TAXI/MapServer"
foreach ($c in 0..3) {
    Invoke-WebRequest -UseBasicParsing "$base/$c/query?where=1%3D1&outFields=*&outSR=4326&f=geojson" -OutFile "data\raw\paradas_taxi_$c.geojson"
}
```

Al reiniciar la API aparece la parada más cercana en "Pedir taxi" y el botón "Paradas" en el mapa.

## Demo original (Streamlit)

La demo con la que empezamos está en `demo_streamlit/`, sin cambios y con su propia copia de la lógica (`demo_streamlit/src/`). Sirve de respaldo si algo falla el día de la presentación:

```powershell
cd demo_streamlit
pip install -r requirements.txt
streamlit run app.py
```

La app nueva usa `core/`, que parte de esa misma lógica con las mejoras (modo programada, reglas nuevas, prioridad de especialidad).

## Privacidad

- Lo que escribe el usuario **no se guarda** en el servidor.
- Los contactos de confianza se guardan **solo en el móvil** (localStorage).
- Las citas son una simulación y se guardan en `data/citas.json` (no se sube a GitHub).

## Créditos y fuentes

- Lógica base: demo Hospital Flow en Streamlit (equipo).
- Teléfonos de radio-taxi: [esMadrid](https://w3.esmadrid.com/en/node/94) (verificar antes de presentar).
- Paradas de taxi: [Geoportal del Ayuntamiento de Madrid](https://sigma.madrid.es/hosted/rest/services/GEOPORTAL/RESERVAS_PLAZAS_TAXI/MapServer).
- Mapa: [Leaflet](https://leafletjs.com) · teselas © OpenStreetMap y CARTO.
- Iconos: [Lucide](https://lucide.dev) (ISC).
