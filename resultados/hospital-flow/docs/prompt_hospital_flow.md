# Hospital Flow · DATAMAD 2026

## Contexto
- Hackathon DATAMAD 2026 (URJC Vicálvaro). Somos 5: yo llevo el LLM; hay uno de datos, uno de frontend y dos de memoria. El código tiene que ser fácil de leer para ellos.
- En mi carpeta tienes una demo en Streamlit (`app.py`, `ingestion.py`, `processing.py`). Reutiliza su lógica: catálogo de hospitales, simulación de ocupación, ranking (espera + ocupación + distancia), reglas de triaje y citas. Ojo: `app.py` importa `from src import ...` pero los archivos están sueltos.
- Te adjunto `datos_originales`, que hay que limpiar.

## Objetivo
Web app para móvil: el usuario escribe qué le pasa ("necesito operarme la rodilla", "me he torcido el tobillo") y la app le dice a qué hospital ir según especialidad, cercanía y saturación. Además le ayuda a llegar (taxi), a avisar a alguien y a llamar a emergencias.

## Stack y estructura
- Backend: Python + FastAPI (`api.py`), que sirve también el frontend.
- Frontend: HTML + CSS + JS sin frameworks ni build (`frontend/`), mapa con Leaflet. Sustituye a la UI de Streamlit.
- Carpetas: `llm/` · `core/` (lógica de la demo, separa ranking/triaje/citas si ayuda) · `data/raw/` (originales sin tocar) · `data/clean/` · `frontend/` · `docs/` · `.env` · `requirements.txt` · `README.md`.

## Paso 1 · Limpieza de datos (lo primero)
1. Perfila `datos_originales` y dame un informe corto: filas, columnas, tipos, nulos, duplicados, valores raros y codificación. PARA y espera mi OK.
2. `data/limpieza.py` (pandas, reproducible): columnas en snake_case; textos sin espacios sobrantes; especialidades unificadas en UNA lista cerrada (la misma que usará el LLM); coordenadas en WGS84 (coma → punto, lat/lon cambiadas, UTM EPSG:25830 → 4326 con pyproj si hace falta) y fuera lo que caiga fuera de la Comunidad de Madrid; fechas en ISO; sin duplicados. Los nulos NO se inventan: se marcan o se eliminan con motivo.
3. Resultado en `data/clean/` + `docs/informe_limpieza.md` (qué se cambió, cuántas filas y por qué) para los de memoria.

## LLM (mi parte)
- `llm/extractor.py`: mensaje → JSON validado con Pydantic `{especialidad: lista cerrada | null, urgencia: vital | urgente | programada | leve, procedimiento, resumen}`. Modelo en `.env` (por defecto `claude-haiku-5-5`), timeout 8 s.
- `llm/explicador.py`: explica el top 3 en 2 frases usando SOLO los datos que recibe. Sin diagnósticos. Se carga después del ranking para no hacer esperar.
- El LLM NUNCA elige hospital: lo elige `core/`. Si es "programada" y los datos traen listas de espera por especialidad, ordena por espera quirúrgica + distancia.
- Las reglas de emergencia de la demo se ejecutan SIEMPRE antes que el LLM y gana el nivel más grave. Sin API key o si el LLM falla, todo sigue funcionando con reglas.
- No guardes en el servidor lo que escribe el usuario.
- `llm/casos_prueba.py`: 20 frases (algunas con faltas) + script que saque una tabla de resultados.

## Emergencias
- Botón "112" fijo en la cabecera de todas las pantallas (`tel:112`).
- Si es emergencia: pantalla roja con "Llamar al 112" como acción principal y "Avisar a alguien" como secundaria. Sin taxi ni citas, y con el aviso de no conducir.
- Si es una crisis (ideas suicidas): 024 + 112 con el texto de la demo.

## Avisar a un familiar o amigo
- Hasta 3 contactos de confianza (nombre, teléfono, relación), guardados SOLO en el móvil (localStorage).
- Añadir con la Contact Picker API si existe (Chrome Android); si no, formulario. Teléfonos normalizados a +34.
- Por contacto: Llamar (`tel:`), WhatsApp (`wa.me` con el texto ya escrito) y SMS (formato válido en iOS y Android). Texto: "Hola [nombre], voy al [hospital] ([dirección]). Mi ubicación: [enlace de Google Maps]".

## Taxi
- Los datasets "Taxi" de datos.madrid.es son de flota y licencias: no sirven para pedir uno.
- Paradas: Geoportal del Ayuntamiento, `https://sigma.madrid.es/hosted/rest/services/GEOPORTAL/RESERVAS_PLAZAS_TAXI/MapServer` (capas 0-3, EPSG:25830). Descarga cada capa con `/{capa}/query?where=1%3D1&outFields=*&outSR=4326&f=geojson`; si no tienes acceso, pídeme que lo baje a `data/raw/`. Muestra la parada más cercana y la distancia a pie.
- Llamar: radio-taxis que publica esMadrid (verifica los números antes): Tele Taxi 913 712 131 · pidetaxi 915 478 200 · TxMAD (app oficial del Ayuntamiento) 914 043 324.
- Tarjeta "Dile al taxista: [hospital], [dirección]" con botón de copiar.

## Pantallas
1. Inicio: "¿Qué te pasa?" + chips de ejemplo + ubicación (GPS; si la deniega, selector de zona como en la demo) + "Buscar hospital".
2. Resultado: banner de triaje + tarjeta del hospital recomendado (espera, distancia y minutos, ocupación con texto, especialidad) + "Por qué" + 3 acciones: Cómo llegar (Google Maps), Pedir taxi, Avisar a alguien. Debajo, "Ver otras 2 opciones".
3. Mapa: hospitales por color de ocupación, mi ubicación e interruptor de paradas de taxi.
4. Citas: lo de la demo.
5. Contactos: gestionar los de confianza.
Barra inferior: Inicio · Mapa · Citas · Contactos. Taxi y Avisar se abren como hojas inferiores.

## Diseño limpio y claro
- Mobile-first a 390×844; en escritorio, máximo 480 px de ancho. Nada de scroll horizontal.
- Fondo claro, tarjetas blancas con radio de 16 px, un solo color principal; el rojo, solo para emergencias. Fuente del sistema.
- Una acción principal por pantalla; lo demás, plegado.
- Botones de 48 px o más, texto de 16 px o más, contraste WCAG AA y el color nunca va solo (siempre con texto).
- Iconos SVG (Lucide), nada de emojis. Respeta las zonas seguras del iPhone.
- Estados de carga, error, sin ubicación y sin contactos. Etiqueta visible "Ocupación y esperas simuladas".
- Textos en español, cortos y de tú.

## Cómo trabajar
- Por fases, enseñándome cada una antes de seguir: datos → API → LLM → pantallas → taxi y contactos → pulido.
- En el móvil, el GPS y los contactos necesitan HTTPS: explícame cómo probarlo con un túnel (cloudflared) o un deploy en Render, y genera un QR del enlace para la presentación.
- Al final: README (instalar, ejecutar, probar), capturas a 390×844 de cada pantalla y lista de lo que falta.

## Criterios de aceptación
- "me duele el pecho y no puedo respirar" → emergencia: 112 primero, sin taxi.
- "necesito operarme la rodilla" → Traumatología, programada.
- "mi hija tiene fiebre alta desde ayer" → Pediatría, urgente.
- Sin API key → funciona con reglas. Ubicación denegada → selector de zona.
