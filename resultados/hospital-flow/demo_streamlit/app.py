"""
Capa de presentación - Hospital Flow (Streamlit)
Ejecutar con:  streamlit run app.py
"""
from __future__ import annotations

import html
from datetime import date, datetime, time, timedelta

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src import ingestion, processing

st.set_page_config(page_title="Hospital Flow", page_icon="🏥", layout="wide")

ZONAS: dict[str, tuple[float, float]] = {
    "Puerta del Sol": (40.4168, -3.7038),
    "Atocha": (40.4065, -3.6895),
    "Chamartín": (40.4723, -3.6827),
    "Moncloa": (40.4352, -3.7189),
    "Vallecas": (40.3930, -3.6190),
    "Getafe (centro)": (40.3057, -3.7327),
    "Fuenlabrada": (40.2842, -3.7942),
    "Alcalá de Henares": (40.4820, -3.3640),
}

EMOJI_NIVEL = {"Baja": "🟢", "Media": "🟡", "Alta": "🔴"}

EMERGENCIA_HTML = """
<a href="tel:112" style="display:block;text-align:center;background:#d62828;color:#ffffff;
font-size:1.5rem;font-weight:800;padding:18px;border-radius:12px;text-decoration:none;
box-shadow:0 4px 12px rgba(214,40,40,.45);">🚨 EMERGENCIA GRAVE · LLAMAR AL 112</a>
"""

SALUDO_CHAT = (
    "👋 Hola, soy el asistente de orientación de **Hospital Flow**. Descríbeme tus síntomas y te "
    "diré si parece una emergencia, una urgencia o algo que puede valorarse en tu centro de salud.\n\n"
    f"_{processing.AVISO_LEGAL}_"
)


# --------------------------------------------------------------------------- #
# Datos
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=60, show_spinner="Cargando datos de hospitales…")
def cargar_datos() -> tuple[pd.DataFrame, str]:
    registros, fuente = ingestion.obtener_datos_hospitales()
    return processing.aplanar_hospitales(registros), fuente


def ubicacion_actual() -> tuple[float, float]:
    zona = st.session_state.get("zona", "Puerta del Sol")
    return ZONAS.get(zona, ZONAS["Puerta del Sol"])


def render_sidebar(df: pd.DataFrame, fuente: str) -> None:
    with st.sidebar:
        st.title("🏥 Hospital Flow")
        st.caption("Reduce esperas en urgencias con datos abiertos y simulados.")
        st.markdown(f"**Fuente:** {fuente}")
        st.markdown(f"**Última actualización:** {df['actualizado'].iloc[0]}")
        if st.button("🔄 Actualizar datos"):
            st.cache_data.clear()
            st.rerun()
        st.divider()
        st.caption(
            "⚠️ Prototipo con datos sintéticos de ocupación y espera. "
            "No ofrece diagnóstico médico; ante una emergencia llama al 112."
        )


# --------------------------------------------------------------------------- #
# Pestaña 1: Inicio
# --------------------------------------------------------------------------- #
def render_inicio(df: pd.DataFrame) -> None:
    st.markdown(EMERGENCIA_HTML, unsafe_allow_html=True)
    st.caption("En un móvil el botón marca directamente; desde un ordenador, llama al 112 desde tu teléfono.")
    st.divider()

    c1, c2 = st.columns([3, 2])
    sintomas = c1.text_input(
        "🔎 ¿Qué síntomas tienes?", key="sintomas", placeholder="Ej.: dolor de cabeza y fiebre desde ayer"
    )
    zona = c2.selectbox("📍 ¿Dónde estás?", list(ZONAS), key="zona")

    with st.expander("⚙️ Ajustar prioridades de la recomendación"):
        a, b, c = st.columns(3)
        w_espera = a.slider("Tiempo de espera", 0, 10, 4, key="w_espera")
        w_ocupacion = b.slider("Ocupación", 0, 10, 3, key="w_ocupacion")
        w_distancia = c.slider("Distancia", 0, 10, 3, key="w_distancia")

    lat, lon = ZONAS[zona]
    triaje = processing.orientar_sintomas(sintomas)
    nivel = triaje["nivel"]

    if nivel == "emergencia":
        st.error(triaje["mensaje"], icon="🚨")
        st.markdown(EMERGENCIA_HTML, unsafe_allow_html=True)
    elif nivel == "urgente":
        st.warning(triaje["mensaje"], icon="⚠️")
    elif nivel == "leve":
        st.info(triaje["mensaje"], icon="ℹ️")
    if nivel != "sin_datos":
        if triaje["especialidad"]:
            st.caption(f"🩺 Área orientativa: {triaje['especialidad']} · {processing.AVISO_LEGAL}")
        else:
            st.caption(processing.AVISO_LEGAL)

    ranking = processing.recomendar_hospitales(
        df, lat, lon, w_espera, w_ocupacion, w_distancia, triaje["especialidad"]
    )
    mejor = ranking.iloc[0]

    st.subheader("🏆 Hospital recomendado")
    with st.container(border=True):
        st.markdown(f"### {mejor['nombre']}")
        st.caption(f"{mejor['direccion']} · Puntuación **{mejor['score']}/100**")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Espera estimada", f"{int(mejor['espera_min'])} min")
        m2.metric("Ocupación", f"{mejor['ocupacion_pct']} %", help=f"Nivel: {mejor['nivel_ocupacion']}")
        m3.metric("Distancia", f"{mejor['distancia_km']} km", help=f"≈ {int(mejor['viaje_min'])} min en coche")
        m4.metric("Camas libres", int(mejor["camas_disponibles"]))
        st.caption(f"Nivel de ocupación: {EMOJI_NIVEL[mejor['nivel_ocupacion']]} {mejor['nivel_ocupacion']}")

    with st.expander("📋 Ver ranking completo"):
        tabla = ranking[
            ["ranking", "nombre", "score", "espera_min", "ocupacion_pct", "distancia_km", "camas_disponibles"]
        ].rename(columns={
            "ranking": "#", "nombre": "Hospital", "score": "Puntuación", "espera_min": "Espera (min)",
            "ocupacion_pct": "Ocupación (%)", "distancia_km": "Distancia (km)", "camas_disponibles": "Camas libres",
        })
        st.dataframe(tabla, hide_index=True)

    st.subheader("📅 Agendar cita")
    if nivel == "emergencia":
        st.warning("Con los síntomas descritos no conviene agendar una cita: **llama al 112**.")
        return

    sugerida = datetime.now() + timedelta(hours=1)
    with st.form("form_cita", clear_on_submit=True):
        f1, f2 = st.columns(2)
        hospital_nombre = f1.selectbox("Hospital", ranking["nombre"].tolist(), index=0)
        paciente = f2.text_input("Nombre del paciente")
        f3, f4 = st.columns(2)
        fecha = f3.date_input("Fecha", value=sugerida.date(), min_value=date.today())
        hora = f4.time_input("Hora", value=sugerida.replace(minute=0, second=0, microsecond=0).time(), step=900)
        motivo = st.text_area("Motivo de la consulta", value=sintomas, height=80)
        enviado = st.form_submit_button("✅ Confirmar cita", type="primary")

    if enviado:
        fila = ranking[ranking["nombre"] == hospital_nombre].iloc[0]
        try:
            cita = processing.crear_cita(fila["id"], hospital_nombre, paciente, fecha, hora, motivo)
            st.success(
                f"Cita **{cita['id']}** confirmada en {cita['hospital']} el {cita['fecha']} a las {cita['hora']}. "
                "Puedes gestionarla en la pestaña «📅 Citas Hechas»."
            )
            st.toast("Cita agendada", icon="✅")
        except ValueError as exc:
            st.error(str(exc))


# --------------------------------------------------------------------------- #
# Pestaña 2: Mapa
# --------------------------------------------------------------------------- #
def render_mapa(df: pd.DataFrame) -> None:
    st.subheader("🗺️ Mapa de ocupación de urgencias")
    niveles = st.multiselect(
        "Niveles a mostrar", ["Baja", "Media", "Alta"], default=["Baja", "Media", "Alta"], key="niveles_mapa"
    )
    conteo = df["nivel_ocupacion"].value_counts()
    k1, k2, k3 = st.columns(3)
    k1.metric("🟢 Ocupación baja", int(conteo.get("Baja", 0)))
    k2.metric("🟡 Ocupación media", int(conteo.get("Media", 0)))
    k3.metric("🔴 Ocupación alta", int(conteo.get("Alta", 0)))

    lat, lon = ubicacion_actual()
    mapa = folium.Map(location=[40.42, -3.70], zoom_start=10, tiles="OpenStreetMap")
    folium.Marker(
        [lat, lon], tooltip="📍 Tu ubicación", icon=folium.Icon(color="blue", icon="user", prefix="fa")
    ).add_to(mapa)

    for _, h in df[df["nivel_ocupacion"].isin(niveles)].iterrows():
        nombre = html.escape(h["nombre"])
        popup_html = (
            f"<div style='font-family:sans-serif;font-size:13px;min-width:230px'>"
            f"<b>{nombre}</b><br><span style='color:#666'>{html.escape(h['direccion'])}</span><hr style='margin:6px 0'>"
            f"Ocupación: <b>{h['ocupacion_pct']} %</b> ({h['nivel_ocupacion']})<br>"
            f"Espera estimada: <b>{int(h['espera_min'])} min</b><br>"
            f"Camas libres: <b>{int(h['camas_disponibles'])}</b> / {int(h['camas_urgencias'])}<br>"
            f"Pacientes en espera: <b>{int(h['pacientes_espera'])}</b></div>"
        )
        folium.CircleMarker(
            location=[h["lat"], h["lon"]],
            radius=14,
            color="#333333",
            weight=2,
            fill=True,
            fill_color=processing.COLORES_NIVEL[h["nivel_ocupacion"]],
            fill_opacity=0.9,
            tooltip=f"{h['nombre']} · {h['ocupacion_pct']} %",
            popup=folium.Popup(popup_html, max_width=320),
        ).add_to(mapa)

    st_folium(mapa, height=560, use_container_width=True, returned_objects=[])
    st.markdown("🟢 **Baja** (<60 %) · 🟡 **Media** (60–85 %) · 🔴 **Alta** (≥85 %) · 🔵 Tu ubicación")


# --------------------------------------------------------------------------- #
# Pestaña 3: Ayuda IA (chat simulado)
# --------------------------------------------------------------------------- #
def render_chat(df: pd.DataFrame) -> None:
    st.subheader("🤖 Ayuda IA · Orientación rápida de triaje")
    st.caption("Asistente simulado basado en reglas. No diagnostica ni sustituye a un profesional sanitario.")

    if "chat" not in st.session_state:
        st.session_state.chat = [{"role": "assistant", "content": SALUDO_CHAT}]

    if st.button("🗑️ Nueva conversación"):
        st.session_state.chat = [{"role": "assistant", "content": SALUDO_CHAT}]
        st.rerun()

    for mensaje in st.session_state.chat:
        with st.chat_message(mensaje["role"]):
            st.markdown(mensaje["content"])

    texto = st.chat_input("Describe tus síntomas…", key="chat_input")
    if texto:
        triaje = processing.orientar_sintomas(texto)
        lat, lon = ubicacion_actual()
        ranking = processing.recomendar_hospitales(df, lat, lon, especialidad=triaje["especialidad"])
        mejor = ranking.iloc[0] if not ranking.empty else None
        st.session_state.chat.append({"role": "user", "content": texto})
        st.session_state.chat.append({"role": "assistant", "content": processing.respuesta_chat(triaje, mejor)})
        st.rerun()

    if st.session_state.chat and st.session_state.chat[-1]["role"] == "assistant" and len(st.session_state.chat) > 1:
        ultimo_user = next((m["content"] for m in reversed(st.session_state.chat) if m["role"] == "user"), "")
        if processing.orientar_sintomas(ultimo_user)["nivel"] == "emergencia":
            st.markdown(EMERGENCIA_HTML, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Pestaña 4: Citas hechas
# --------------------------------------------------------------------------- #
def render_citas() -> None:
    st.subheader("📅 Citas hechas")
    todas = processing.listar_citas()
    activas = [c for c in todas if c["estado"] == processing.ESTADO_CONFIRMADA]
    canceladas = [c for c in todas if c["estado"] == processing.ESTADO_CANCELADA]

    k1, k2 = st.columns(2)
    k1.metric("Confirmadas", len(activas))
    k2.metric("Canceladas", len(canceladas))

    filtro = st.radio("Mostrar", ["Activas", "Canceladas", "Todas"], horizontal=True, key="filtro_citas")
    lista = {"Activas": activas, "Canceladas": canceladas, "Todas": todas}[filtro]

    if not lista:
        st.info("No hay citas que mostrar. Agenda una desde la pestaña «🏠 Inicio».")
        return

    for c in lista:
        activa = c["estado"] == processing.ESTADO_CONFIRMADA
        with st.container(border=True):
            top1, top2 = st.columns([4, 1])
            top1.markdown(f"**{c['hospital']}**  \n👤 {c['paciente']} · 🗓️ {c['fecha']} a las {c['hora']}")
            top1.caption(f"Motivo: {c['motivo']} · Ref. {c['id']}")
            top2.markdown("✅ Confirmada" if activa else "❌ Cancelada")

            if not activa:
                continue

            acciones1, acciones2 = st.columns([1, 3])
            if acciones1.button("❌ Cancelar cita", key=f"cancelar_{c['id']}"):
                try:
                    processing.cancelar_cita(c["id"])
                    st.toast("Cita cancelada", icon="🗑️")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

            with acciones2.expander("✏️ Modificar cita"):
                with st.form(f"form_mod_{c['id']}"):
                    m1, m2 = st.columns(2)
                    nueva_fecha = m1.date_input(
                        "Nueva fecha", value=max(date.fromisoformat(c["fecha"]), date.today()),
                        min_value=date.today(), key=f"fecha_{c['id']}",
                    )
                    nueva_hora = m2.time_input(
                        "Nueva hora", value=datetime.strptime(c["hora"], "%H:%M").time(), step=900,
                        key=f"hora_{c['id']}",
                    )
                    nuevo_motivo = st.text_input("Motivo", value=c["motivo"], key=f"motivo_{c['id']}")
                    guardar = st.form_submit_button("💾 Guardar cambios")
                if guardar:
                    try:
                        processing.modificar_cita(c["id"], nueva_fecha, nueva_hora, nuevo_motivo)
                        st.toast("Cita modificada", icon="✅")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    try:
        df, fuente = cargar_datos()
    except ValueError as exc:
        st.error(f"No se pudieron cargar los datos de hospitales: {exc}")
        st.stop()

    render_sidebar(df, fuente)
    st.title("🏥 Hospital Flow")
    st.caption("Encuentra el hospital con menos espera cerca de ti · Madrid")

    tab_inicio, tab_mapa, tab_ia, tab_citas = st.tabs(
        ["🏠 Inicio", "🗺️ Mapa", "🤖 Ayuda IA", "📅 Citas Hechas"]
    )
    with tab_inicio:
        render_inicio(df)
    with tab_mapa:
        render_mapa(df)
    with tab_ia:
        render_chat(df)
    with tab_citas:
        render_citas()


main()
