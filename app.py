import base64
import time
import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import plotly.express as px
import plotly.graph_objects as go

# ============================================================
# CONFIG
# ============================================================
st.set_page_config(page_title="BMS Dashboard", layout="wide")
TZ = ZoneInfo("Europe/Madrid")
st.session_state.setdefault("auth_ok", False)

BG_IMAGE_PATH = Path("FONDO_DAHSBOARD.jpg")

ALIASES_INSTANT = ["POT T1", "POT T2", "POT T3", "POT T4", "POT T5"]
ALIASES_LINES   = ["POT T1", "POT T2", "POT T3", "POT T4", "POT T4 ALUMBRADO", "POT T5"]

COLOR_MAP = {
    "POT T1": "#4F6D7A",
    "POT T2": "#7D8F8E",
    "POT T3": "#9FB4B9",
    "POT T4": "#C4D7D1",
    "POT T5": "#A8B6A9",
}

def fmt(x: float) -> str:
    """Entero sin decimales y con punto de miles."""
    return f"{x:,.0f}".replace(",", ".")

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
# FONDO RESPONSIVE
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
        html, body, .stApp {{
            height: 100%;
            width: 100%;
            overflow: visible;
        }}

        .stApp {{
            background-image: url("data:image/jpg;base64,{b64}");
            background-size: contain !important;       /* SIEMPRE completa */
            background-position: top center !important;
            background-repeat: no-repeat !important;
        }}

        /* Ocultar cabeceras/pies/menú */
        header[data-testid="stHeader"] {{display:none !important;}}
        footer {{display:none !important;}}
        #MainMenu {{visibility:hidden !important;}}
        [data-testid="stDecoration"] {{display:none !important;}}

        .block-container {{
            padding-top: 0rem !important;
        }}
        </style>
        """,
        unsafe_allow_html=True
    )

# ============================================================
# SUPABASE (datos desde 00:00 hoy)
# ============================================================
def iso_z(dt): return dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def supabase_cargar_hoy():
    base_url = st.secrets["supabase"]["url"].rstrip("/")
    key      = st.secrets["supabase"]["key"]
    table    = st.secrets["supabase"]["table"]

    now_local   = datetime.now(TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc   = start_local.astimezone(timezone.utc)
    now_utc     = now_local.astimezone(timezone.utc)

    q = [
        "select=timestamp_utc,punto_alias,punto_clave,valor",
        "order=timestamp_utc.desc",
        f"timestamp_utc=gte.{iso_z(start_utc)}",
        f"timestamp_utc=lte.{iso_z(now_utc)}"
    ]
    url = f"{base_url}/rest/v1/{table}?" + "&".join(q)
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Range":"0-28799"}

    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    df = pd.DataFrame(r.json())

    if df.empty:
        return df

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["hora_local"] = df["timestamp_utc"].dt.tz_convert(TZ)      # UTC → Madrid
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["punto_alias"] = df["punto_alias"].astype(str).str.strip()

    return df.sort_values("timestamp_utc")

# ============================================================
# METEO
# ============================================================
def obtener_tiempo():
    try:
        r = requests.get("https://wttr.in/Madrid?format=j1",
                         headers={"User-Agent":"Mozilla/5.0"}, timeout=7)
        j = r.json()
        return (
            j["current_condition"][0]["weatherDesc"][0]["value"],
            float(j["current_condition"][0]["temp_C"]),
            float(j["current_condition"][0]["FeelsLikeC"]),
            int(j["current_condition"][0]["humidity"]),
            int(j["current_condition"][0]["windspeedKmph"])
        )
    except:
        return None, None, None, None, None

# ============================================================
# APP
# ============================================================
require_login()
aplicar_fondo_css()

# ============================================================
# CABECERA: FECHA/HORA/TIEMPO (MÁS AL CENTRO)
# ============================================================
# Más centrado: aumentamos el padding-right
c1, c2, c3 = st.columns([1.4, 1.4, 1.2])   # estructura superior
with c3:
    hoy  = datetime.now(TZ).strftime("%Y-%m-%d")
    hora = datetime.now(TZ).strftime("%H:%M")
    st.markdown(
        f"""
        <div style="text-align:right; padding-right:340px;">  <!-- desplazado + a la izq -->
            <div style="font-size:36px; font-weight:800; color:#111;">{hoy}</div>
            <div style="font-size:54px; font-weight:900; color:#111; margin-top:-10px;">{hora}</div>
        </div>
        """,
        unsafe_allow_html=True
    )
    e, t, f_, h_, v_ = obtener_tiempo()
    if e:
        st.markdown(
            f"""
            <div style="text-align:right; padding-right:340px;
                        font-size:18px; font-weight:600; color:#222;">
                {e} · <b>{t:.1f}°C</b><br>
                <span style="font-size:14px;color:#333">
                    Sensación {f_:.1f}°C · Humedad {h_}% · Viento {v_} km/h
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )

# ============================================================
# DATOS HOY
# ============================================================
df = supabase_cargar_hoy()
if df.empty:
    st.info("Sin datos.")
    time.sleep(60); st.experimental_rerun()

last_idx = df.groupby("punto_alias")["timestamp_utc"].idxmax()
df_last  = df.loc[last_idx]

# Instantáneo (T1..T5)
inst_vals = []
for a in ALIASES_INSTANT:
    v = df_last[df_last["punto_alias"]==a]["valor"]
    inst_vals.append(float(v.iloc[0]) if not v.empty else 0.0)
df_instant = pd.DataFrame({"alias": ALIASES_INSTANT, "valor": inst_vals})
df_instant["valor_fmt"] = df_instant["valor"].apply(fmt)  # para texto con . de miles

# Acumulado (kWh = sum(valor/60))
df_kwh = (
    df[df["punto_alias"].isin(ALIASES_INSTANT)]
    .assign(kwh=lambda x: x["valor"]/60)
    .groupby("punto_alias")["kwh"].sum()
)
df_acum = pd.DataFrame({"alias": ALIASES_INSTANT,
                        "kwh": [df_kwh.get(a, 0) for a in ALIASES_INSTANT]})
df_acum["kwh_fmt"] = df_acum["kwh"].apply(fmt)

total_inst = df_instant["valor"].sum()
total_kwh  = df_acum["kwh"].sum()

# ============================================================
# TARTAS Y TOTALES — MÁS JUNTOS (gap pequeño y márgenes 0)
# ============================================================
col_t1, col_t2, col_tot = st.columns([1.15, 1.15, 0.8], gap="small")

# --- TARTA INSTANTÁNEA (33% del anterior)
with col_t1:
    st.markdown("### Potencia instantánea")
    fig1 = px.pie(
        df_instant, names="alias", values="valor",
        color="alias", color_discrete_map=COLOR_MAP,
        hole=0.35, height=220, custom_data=["valor_fmt"]
    )
    # Texto con valor entero y % (valor con separador de miles)
    fig1.update_traces(
        textposition="inside",
        texttemplate="%{label}<br>%{customdata[0]} kW (%{percent})"
    )
    fig1.update_layout(
        showlegend=True, legend_title_text="Potencias",
        margin=dict(l=0, r=0, t=0, b=0)
    )
    st.plotly_chart(fig1, use_container_width=True)

# --- TARTA ACUMULADA (centrada, sin leyenda)
with col_t2:
    st.markdown("### Energía acumulada del día")
    fig2 = px.pie(
        df_acum, names="alias", values="kwh",
        color="alias", color_discrete_map=COLOR_MAP,
        hole=0.35, height=220, custom_data=["kwh_fmt"]
    )
    fig2.update_traces(
        textposition="inside",
        texttemplate="%{customdata[0]} kWh (%{percent})"
    )
    fig2.update_layout(showlegend=False, margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig2, use_container_width=True)

# --- TOTALES (sin decimales y con . de miles)
with col_tot:
    st.markdown("### Total Instantáneo")
    st.markdown(
        f"<div style='font-size:48px; font-weight:900; color:#111;'>{fmt(total_inst)} kW</div>",
        unsafe_allow_html=True
    )
    st.markdown("### Acumulado Hoy")
    st.markdown(
        f"<div style='font-size:42px; font-weight:800; color:#333;'>{fmt(total_kwh)} kWh</div>",
        unsafe_allow_html=True
    )

# ============================================================
# GRÁFICO DE LÍNEAS — AÚN MÁS PEQUEÑO Y ESTRECHO
# ============================================================
# lo dejamos en ~60 % de la columna izquierda para ganar mucho espacio
line_left, line_right = st.columns([0.6, 1.4], gap="small")

with line_left:
    st.markdown("### Potencias del día")
    df_lines = df[df["punto_alias"].isin(ALIASES_LINES)]
    pivot = (
        df_lines
        .pivot_table(index="hora_local", columns="punto_alias", values="valor")
        .sort_index()
    )
    for a in ALIASES_LINES:
        if a not in pivot.columns:
            pivot[a] = None
    pivot = pivot[ALIASES_LINES]

    fig_line = go.Figure()
    for col in ALIASES_LINES:
        fig_line.add_trace(go.Scatter(
            x=pivot.index, y=pivot[col],
            mode='lines', name=col, line=dict(width=1.5)
        ))

    # Ocultar completamente eje X (ticks, labels, grid)
    fig_line.update_xaxes(showgrid=False, showticklabels=False, ticks="", zeroline=False, visible=True)
    fig_line.update_yaxes(showgrid=True)

    fig_line.update_layout(
        height=180,  # aún más pequeño
        margin=dict(l=0, r=0, t=5, b=0),
        legend=dict(orientation="h", y=1.02, x=0)
    )
    st.plotly_chart(fig_line, use_container_width=True)

with line_right:
    st.markdown("")  # espacio libre reservado para info futura

# ============================================================
# AUTO REFRESH
# ============================================================
time.sleep(60)
st.experimental_rerun()
