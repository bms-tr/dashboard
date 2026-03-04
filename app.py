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

BG_IMAGE_PATH = Path("FONDO_DAHSBOARD.jpg")

# Aliases
ALIASES_INSTANT = ["POT T1", "POT T2", "POT T3", "POT T4", "POT T5"]
ALIASES_LINES = ["POT T1", "POT T2", "POT T3", "POT T4", "POT T4 ALUMBRADO", "POT T5"]

COLOR_MAP = {
    "POT T1": "#4F6D7A",
    "POT T2": "#7D8F8E",
    "POT T3": "#9FB4B9",
    "POT T4": "#C4D7D1",
    "POT T5": "#A8B6A9",
}

# ============================================================
# LOGIN
# ============================================================
def require_login():
    if st.session_state.get("auth_ok"):
        return
    st.title("🔐 Acceso")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Entrar"):
        if u == st.secrets["auth"]["user"] and p == st.secrets["auth"]["password"]:
            st.session_state["auth_ok"] = True
            st.experimental_rerun()
        else:
            st.error("Credenciales incorrectas.")
    st.stop()

# ============================================================
# FONDO + OCULTAR HEADER / MENU / FOOTER
# ============================================================
def aplicar_fondo_css():
    try:
        with open(BG_IMAGE_PATH, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except:
        b64 = ""

    st.markdown(
        f"""
        <style>
        /* Fondo responsive */
        .stApp {{
            background-image: url("data:image/jpg;base64,{b64}");
            background-size: cover;
            background-position: center top;
            background-repeat: no-repeat;
        }}

        /* Quitar header y menú */
        header[data-testid="stHeader"] {{display: none !important;}}
        #MainMenu {{display:none !important;}}

        /* Quitar footer */
        footer {{display:none !important;}}

        /* Quitar decoraciones */
        [data-testid="stDecoration"] {{display:none !important;}}

        .block-container {{
            padding-top: 1rem !important;
        }}
        </style>
        """,
        unsafe_allow_html=True
    )

# ============================================================
# SUPABASE: Datos desde 00:00 hasta ahora (hoy)
# ============================================================
def iso_z(dt): return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def supabase_cargar_hoy():
    base_url = st.secrets["supabase"]["url"].rstrip("/")
    key      = st.secrets["supabase"]["key"]
    table    = st.secrets["supabase"]["table"]

    now_local = datetime.now(TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc)
    now_utc = now_local.astimezone(timezone.utc)

    params = [
        "select=timestamp_utc,punto_alias,punto_clave,valor",
        "order=timestamp_utc.desc",
        f"timestamp_utc=gte.{iso_z(start_utc)}",
        f"timestamp_utc=lte.{iso_z(now_utc)}"
    ]

    url = f"{base_url}/rest/v1/{table}?" + "&".join(params)
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Range": "0-28799"
    }

    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    df = pd.DataFrame(r.json())

    if df.empty:
        return df

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["hora_local"] = df["timestamp_utc"].dt.tz_convert(TZ)
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["punto_alias"] = df["punto_alias"].astype(str).str.strip()

    # Reorden asc
    return df.sort_values("timestamp_utc")

# ============================================================
# METEO (estable)
# ============================================================
def obtener_tiempo():
    try:
        r = requests.get("https://wttr.in/Madrid?format=j1",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=7)
        j = r.json()
        estado  = j["current_condition"][0]["weatherDesc"][0]["value"]
        temp_c  = float(j["current_condition"][0]["temp_C"])
        feels_c = float(j["current_condition"][0]["FeelsLikeC"])
        hum     = int(j["current_condition"][0]["humidity"])
        v_kmh   = int(j["current_condition"][0]["windspeedKmph"])
        return estado, temp_c, feels_c, hum, v_kmh
    except:
        return None, None, None, None, None

# ============================================================
# APP
# ============================================================
require_login()
aplicar_fondo_css()

# ============================================================
# CABECERA: Fecha/Hora y Meteo
# ============================================================
fila1_left, fila1_spacer, fila1_right = st.columns([1,2,1])

with fila1_right:
    hoy = datetime.now(TZ).strftime("%Y-%m-%d")
    hora = datetime.now(TZ).strftime("%H:%M")

    st.markdown(
        f"""
        <div style="text-align:right;">
            <div style="font-size:38px; font-weight:800; color:#111;">{hoy}</div>
            <div style="font-size:56px; font-weight:900; color:#111; margin-top:-10px;">{hora}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    e, t, f, h, v = obtener_tiempo()
    if e:
        st.markdown(
            f"""
            <div style="text-align:right; font-size:18px; color:#222; font-weight:600;">
                {e} · <b>{t:.1f}°C</b><br>
                <span style="font-size:14px;">
                Sensación {f:.1f}°C · Humedad {h}% · Viento {v} km/h
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            "<div style='text-align:right; font-size:16px; color:#333;'>Tiempo no disponible</div>",
            unsafe_allow_html=True
        )

# ============================================================
# CARGAR DATOS DE HOY
# ============================================================
df = supabase_cargar_hoy()

if df.empty:
    st.info("Sin datos para hoy.")
    time.sleep(60)
    st.experimental_rerun()

# Últimos valores
last_idx = df.groupby("punto_alias")["timestamp_utc"].idxmax()
df_last = df.loc[last_idx, ["punto_alias","valor","hora_local"]]

# Instantáneos para T1..T5
inst_vals = []
for a in ALIASES_INSTANT:
    v = df_last[df_last["punto_alias"] == a]["valor"]
    inst_vals.append(float(v.iloc[0]) if not v.empty else 0.0)
df_instant = pd.DataFrame({"alias": ALIASES_INSTANT, "valor": inst_vals})

# ============================================================
# ENERGÍA ACUMULADA (POT / 60 por minuto)
# ============================================================
ener_acum = (
    df[df["punto_alias"].isin(ALIASES_INSTANT)]
    .assign(energia=lambda x: x["valor"] / 60)
    .groupby("punto_alias")["energia"]
    .sum()
)
df_acum = pd.DataFrame({
    "alias": ALIASES_INSTANT,
    "kwh": [ener_acum[a] if a in ener_acum else 0 for a in ALIASES_INSTANT]
})

# Totales
total_inst = df_instant["valor"].sum()
total_kwh  = df_acum["kwh"].sum()

# ============================================================
# TARTAS + VALORES (Distribución en la parte superior)
# ============================================================
tarta_inst_col, tarta_acum_col, valores_col = st.columns([1.2,1.2,1.0])

# --- TARTA INSTANTÁNEA
with tarta_inst_col:
    st.markdown("### Potencia instantánea")
    fig1 = px.pie(df_instant,
                  names="alias",
                  values="valor",
                  color="alias",
                  color_discrete_map=COLOR_MAP,
                  hole=0.35)
    fig1.update_traces(
        textinfo="label+value+percent",
        textposition="inside"
    )
    fig1.update_layout(
        showlegend=True,
        legend_title_text="Potencias",
        margin=dict(l=0, r=0, t=10, b=10),
        height=250
    )
    st.plotly_chart(fig1, use_container_width=True)

# --- TARTA ACUMULADA
with tarta_acum_col:
    st.markdown("### Energía acumulada del día")
    fig2 = px.pie(df_acum,
                  names="alias",
                  values="kwh",
                  color="alias",
                  color_discrete_map=COLOR_MAP,
                  hole=0.35)
    fig2.update_traces(
        textinfo="value+percent",
        textposition="inside"
    )
    fig2.update_layout(
        showlegend=False,
        margin=dict(l=0, r=0, t=10, b=10),
        height=250
    )
    st.plotly_chart(fig2, use_container_width=True)

# --- VALORES TOTALES (DERECHA)
with valores_col:
    st.markdown("### Total Instantáneo")
    st.markdown(
        f"""
        <div style="font-size:48px; font-weight:900; color:#111;">
            {total_inst:.2f} kW
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown("### Energía acumulada hoy")
    st.markdown(
        f"""
        <div style="font-size:42px; font-weight:800; color:#333;">
            {total_kwh:.2f} kWh
        </div>
        """,
        unsafe_allow_html=True
    )

# ============================================================
# GRÁFICO DE LÍNEAS (ocupa ancho total)
# ============================================================
df_lines = df[df["punto_alias"].isin(ALIASES_LINES)]
pivot = (
    df_lines
    .pivot_table(index="hora_local",
                 columns="punto_alias",
                 values="valor",
                 aggfunc="mean")
    .sort_index()
)

# Asegurar columnas en orden
for a in ALIASES_LINES:
    if a not in pivot.columns:
        pivot[a] = None
pivot = pivot[ALIASES_LINES]

st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
st.subheader("Serie temporal (desde 00:00)")
st.line_chart(pivot, height=380, use_container_width=True)

# ============================================================
# AUTO-REFRESH
# ============================================================
time.sleep(60)
st.experimental_rerun()
