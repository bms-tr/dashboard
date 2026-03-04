import base64
import time
import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import plotly.express as px

# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================
st.set_page_config(page_title="BMS Dashboard", layout="wide")
TZ = ZoneInfo("Europe/Madrid")
st.session_state.setdefault("auth_ok", False)

# Ruta del fondo en la raíz del repo
BG_IMAGE_PATH = Path("FONDO_DAHSBOARD.jpg")

# Aliases fijos
ALIAS_PIE = ["POT T1", "POT T2", "POT T3", "POT T4", "POT T5"]  # tarta (sin alumbrado)
ALIAS_LINES = ["POT T1", "POT T2", "POT T3", "POT T4", "POT T4 ALUMBRADO", "POT T5"]  # líneas

# ============================================================
# LOGIN
# ============================================================
def require_login():
    if st.session_state.get("auth_ok"):
        return True
    st.title("🔐 Acceso")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Entrar"):
        try:
            if u == st.secrets["auth"]["user"] and p == st.secrets["auth"]["password"]:
                st.session_state["auth_ok"] = True
                st.experimental_rerun()
            else:
                st.error("Credenciales incorrectas.")
        except Exception:
            st.error("Error: secrets.toml no encontrado.")
    st.stop()

# ============================================================
# ESTILOS: FONDO + OCULTAR HEADER/FOOTER/MENÚ
# ============================================================
def aplicar_fondo_y_css():
    try:
        with open(BG_IMAGE_PATH, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except Exception:
        b64 = None

    css_fondo = (
        f""".stApp {{
                background: url("data:image/jpg;base64,{b64}") no-repeat center center fixed;
                background-size: cover;
            }}"""
        if b64
        else ""
    )

    st.markdown(
        f"""
        <style>
        {css_fondo}

        /* Ocultar cabecera, menú y pie (Streamlit >=1.30) */
        header[data-testid="stHeader"] {{ display: none !important; }}
        #MainMenu {{ display: none !important; }}
        footer {{ display: none !important; }}
        [data-testid="stDecoration"] {{ display: none !important; }}

        /* Eliminar paddings extra globales */
        .block-container {{
            padding-top: 0 !important;
            padding-bottom: 0 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True
    )

# ============================================================
# SUPABASE
# ============================================================
def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def supabase_select_today(punto_clave: str | None = None) -> pd.DataFrame:
    """
    Trae datos desde 00:00 de hoy (hora Madrid) hasta ahora,
    ordenando DESC en la API y luego ASC en memoria.
    """
    base_url = st.secrets["supabase"]["url"].rstrip("/")
    key      = st.secrets["supabase"]["key"]
    table    = st.secrets["supabase"]["table"]

    now_local = datetime.now(TZ)
    today_local_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    # Convertimos a UTC para la consulta (porque timestamp_utc está en UTC)
    from_dt_utc = today_local_start.astimezone(timezone.utc)
    to_dt_utc   = now_local.astimezone(timezone.utc)

    query_parts = [
        "select=timestamp_utc,punto_alias,punto_clave,valor",
        "order=timestamp_utc.desc",  # pedimos lo último primero
        f"timestamp_utc=gte.{iso_z(from_dt_utc)}",
        f"timestamp_utc=lte.{iso_z(to_dt_utc)}"
    ]
    if punto_clave:
        query_parts.append(f"punto_clave=eq.{punto_clave}")
    query = "&".join(query_parts)

    url = f"{base_url}/rest/v1/{table}?{query}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Cache-Control": "no-cache",
        "Range": "0-28799"  # hasta ~28.800 filas
    }

    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    if df.empty:
        return df

    # Tipado y limpieza
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["punto_alias"] = df["punto_alias"].astype(str).str.strip()

    # Reordenamos ascendente para graficar cronológicamente
    df = df.sort_values("timestamp_utc", ascending=True, kind="mergesort").reset_index(drop=True)

    # Eje X en hora Madrid (UTC+1/UTC+2 según temporada)
    df["hora_local"] = df["timestamp_utc"].dt.tz_convert(TZ)
    return df

# ============================================================
# METEO (estable con wttr.in y User-Agent de navegador)
# ============================================================
def obtener_tiempo_madrid():
    try:
        r = requests.get("https://wttr.in/Madrid?format=j1", headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        j = r.json()
        estado     = j["current_condition"][0]["weatherDesc"][0]["value"]
        temp_c     = float(j["current_condition"][0]["temp_C"])
        feels_c    = float(j["current_condition"][0]["FeelsLikeC"])
        humedad    = int(j["current_condition"][0]["humidity"])
        viento_kmh = int(j["current_condition"][0]["windspeedKmph"])
        return estado, temp_c, feels_c, humedad, viento_kmh
    except Exception:
        return None, None, None, None, None

# ============================================================
# APP
# ============================================================
require_login()
aplicar_fondo_y_css()

# Cabecera (fecha/hora/tiempo) dentro del layout para que siempre se vea
cab_left, cab_spacer, cab_right = st.columns([1, 2, 1])
with cab_right:
    hoy_txt  = datetime.now(TZ).strftime("%Y-%m-%d")
    hora_txt = datetime.now(TZ).strftime("%H:%M")
    st.markdown(
        f"""
        <div style="text-align:right">
            <div style="font-size:38px; font-weight:800; color:#111; line-height:1.1">{hoy_txt}</div>
            <div style="font-size:56px; font-weight:900; color:#111; line-height:1.0">{hora_txt}</div>
        </div>
        """,
        unsafe_allow_html=True
    )
    estado, t_c, f_c, hum, v_kmh = obtener_tiempo_madrid()
    if estado:
        st.markdown(
            f"""
            <div style="text-align:right; font-size:18px; font-weight:600; color:#222; margin-top:4px">
                {estado} · <b>{t_c:.1f}°C</b><br>
                <span style="font-size:14px; color:#333">
                    Sensación {f_c:.1f}°C · Humedad {hum}% · Viento {v_kmh} km/h
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.markdown("<div style='text-align:right; font-size:16px; color:#333'>Tiempo no disponible</div>", unsafe_allow_html=True)

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)  # pequeño espaciado

# ===== Carga de datos del día (00:00 → ahora)
with st.spinner("Cargando datos de hoy…"):
    try:
        df = supabase_select_today()
    except Exception as e:
        st.error(f"Error leyendo Supabase: {e}")
        st.stop()

if df.empty:
    st.info("No hay datos para hoy todavía.")
    time.sleep(60)
    st.experimental_rerun()

# ===== TARTA (izquierda) + TOTAL grande (derecha)
tarta_col, total_col = st.columns([1.4, 1.0], gap="large")

# Último valor por alias
last_idx = df.groupby("punto_alias")["timestamp_utc"].idxmax()
df_last = df.loc[last_idx, ["punto_alias", "valor", "hora_local"]]

# Datos para la tarta (sólo POT T1..T5)
rows = []
for alias in ALIAS_PIE:
    m = df_last[df_last["punto_alias"] == alias]
    val = float(m["valor"].iloc[0]) if not m.empty and pd.notna(m["valor"].iloc[0]) else 0.0
    rows.append({"alias": alias, "valor": val})
df_pie = pd.DataFrame(rows)

# Colores neutros
COLOR_MAP = {
    "POT T1": "#4F6D7A",
    "POT T2": "#7D8F8E",
    "POT T3": "#9FB4B9",
    "POT T4": "#C4D7D1",
    "POT T5": "#A8B6A9",
}

with tarta_col:
    st.subheader("Distribución de Potencias (último valor)")
    if (df_pie["valor"] > 0).any():
        fig = px.pie(
            df_pie,
            names="alias",
            values="valor",
            color="alias",
            color_discrete_map=COLOR_MAP,
            hole=0.35
        )
        # Mostrar etiqueta con valor + %
        fig.update_traces(
            textposition="inside",
            textinfo="label+percent",
            hovertemplate="%{label}: %{value:.2f} kW<br>%{percent}"
        )
        fig.update_layout(
            showlegend=True,
            legend_title_text="Potencias",
            margin=dict(l=10, r=10, t=10, b=10),
            template="simple_white"
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No hay valores > 0 en el último instante para POT T1..T5.")

with total_col:
    total_kw = df_pie["valor"].sum()
    hora_ult = df["hora_local"].max()
    st.subheader("Total")
    st.markdown(
        f"""
        <div style="font-size:64px; font-weight:900; color:#111; line-height:1.0">
            {total_kw:,.2f} kW
        </div>
        """,
        unsafe_allow_html=True
    )
    if pd.notna(hora_ult):
        st.markdown(
            f"<div style='color:#444'>Última actualización: {hora_ult.strftime('%Y-%m-%d %H:%M')}</div>",
            unsafe_allow_html=True
        )

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ===== GRÁFICO DE LÍNEAS (inferior, ancho completo), sin selectores
st.subheader("Serie temporal (desde 00:00)")
# Filtramos sólo las series fijas
df_lines = df[df["punto_alias"].isin(ALIAS_LINES)].copy()

# Pivot para st.line_chart (no interactivo)
pivot = (
    df_lines
    .pivot_table(index="hora_local", columns="punto_alias", values="valor", aggfunc="mean")
    .sort_index()
)

# Asegurar todas las columnas en el orden deseado (aunque falte alguna)
for alias in ALIAS_LINES:
    if alias not in pivot.columns:
        pivot[alias] = pd.NA
pivot = pivot[ALIAS_LINES]

st.line_chart(pivot, height=420, use_container_width=True)

st.caption("© BMS Dashboard — Auto‑refresh 60 s — Horario Madrid (UTC+1)")

# ===== AUTO REFRESH
time.sleep(60)
st.experimental_rerun()
