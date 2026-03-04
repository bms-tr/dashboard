# app.py

import base64
import time
import math
import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import plotly.express as px
import plotly.graph_objects as go

# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================
st.set_page_config(page_title="BMS Dashboard", layout="wide")
TZ = ZoneInfo("Europe/Madrid")
st.session_state.setdefault("auth_ok", False)

# Imagen de fondo EXACTA en la raíz del repo
BG_IMAGE_PATH = Path("FONDO_DAHSBOARD.jpg")

# Series fijas
ALIASES_INSTANT = ["POT T1", "POT T2", "POT T3", "POT T4", "POT T5"]
ALIASES_LINES   = ["POT T1", "POT T2", "POT T3", "POT T4", "POT T4 ALUMBRADO", "POT T5"]

# Colores neutros (coherentes en ambas tartas)
COLOR_MAP = {
    "POT T1": "#4F6D7A",
    "POT T2": "#7D8F8E",
    "POT T3": "#9FB4B9",
    "POT T4": "#C4D7D1",
    "POT T5": "#A8B6A9",
}

# Altura del gráfico de líneas y de los bloques de equipos (confirmado por el usuario)
LINE_HEIGHT = 216  # px (160 * 1.35 ≈ 216)

# ============================================================
# FORMATOS
# ============================================================
def fmt_int(x: float) -> str:
    """Entero sin decimales y con punto de miles."""
    try:
        return f"{float(x):,.0f}".replace(",", ".")
    except Exception:
        return "0"

def fmt_decimal_coma(x: float, ndigits: int = 1) -> str:
    """Formato con coma decimal (es-ES), n decimales."""
    try:
        val = f"{float(x):.{ndigits}f}"
        return val.replace(".", ",")
    except Exception:
        return "0"

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
            st.rerun()
        else:
            st.error("Credenciales incorrectas.")
    st.stop()

# ============================================================
# FONDO RESPONSIVE + LIMPIEZA UI
# ============================================================
def aplicar_fondo_css():
    try:
        with open(BG_IMAGE_PATH, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except Exception:
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
        header[data-testid="stHeader"] {{display:none !important;}}
        footer {{display:none !important;}}
        #MainMenu {{visibility:hidden !important;}}
        [data-testid="stDecoration"] {{display:none !important;}}
        .block-container {{ padding-top: 0rem !important; }}
        /* Compactar subtítulos */
        h3, h4 {{ margin-top: 0.25rem; margin-bottom: 0.25rem; }}
        </style>
        """,
        unsafe_allow_html=True
    )

# ============================================================
# SUPABASE (datos desde 00:00 hoy → ahora)
# ============================================================
def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def supabase_cargar_hoy() -> pd.DataFrame:
    base_url = st.secrets["supabase"]["url"].rstrip("/")
    key      = st.secrets["supabase"]["key"]
    table    = st.secrets["supabase"]["table"]

    ahora_local = datetime.now(TZ)
    inicio_local = ahora_local.replace(hour=0, minute=0, second=0, microsecond=0)

    inicio_utc = inicio_local.astimezone(timezone.utc)
    ahora_utc  = ahora_local.astimezone(timezone.utc)

    q = [
        "select=timestamp_utc,punto_alias,punto_clave,valor",
        "order=timestamp_utc.desc",
        f"timestamp_utc=gte.{iso_z(inicio_utc)}",
        f"timestamp_utc=lte.{iso_z(ahora_utc)}"
    ]
    url = f"{base_url}/rest/v1/{table}?" + "&".join(q)
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
    df["hora_local"] = df["timestamp_utc"].dt.tz_convert(TZ)  # UTC → Madrid
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["punto_alias"] = df["punto_alias"].astype(str).str.strip()
    return df.sort_values("timestamp_utc")

# ============================================================
# METEO (estable)
# ============================================================
def obtener_tiempo_madrid():
    try:
        r = requests.get("https://wttr.in/Madrid?format=j1",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=7)
        j = r.json()
        return (
            j["current_condition"][0]["weatherDesc"][0]["value"],
            float(j["current_condition"][0]["temp_C"]),
            float(j["current_condition"][0]["FeelsLikeC"]),
            int(j["current_condition"][0]["humidity"]),
            int(j["current_condition"][0]["windspeedKmph"])
        )
    except Exception:
        return None, None, None, None, None

# ============================================================
# BLOQUES DE EQUIPO (BC FELIPE / BC CARLOS / GF1 / GF2)
# ============================================================
def ultimo_valor(df: pd.DataFrame, alias: str) -> float | None:
    """Devuelve el último valor (float) para un alias dado; None si no hay."""
    rows = df[df["punto_alias"] == alias]
    if rows.empty:
        return None
    idx = rows["timestamp_utc"].idxmax()
    val = rows.loc[idx, "valor"]
    try:
        return float(val) if pd.notna(val) else None
    except Exception:
        return None

def render_bloque_equipo(col_placeholder, nombre_equipo: str,
                         alias_marcha: str, alias_carga: str, alias_cop: str,
                         altura_px: int = LINE_HEIGHT):
    """Renderiza un bloque de equipo con estilo de maqueta."""
    # Lecturas
    v_marcha = ultimo_valor(df, alias_marcha)
    v_carga  = ultimo_valor(df, alias_carga)
    v_cop    = ultimo_valor(df, alias_cop)

    marcha = 1 if (v_marcha is not None and v_marcha >= 1) else 0
    carga_pct = max(0, min(100, round(v_carga if v_carga is not None else 0)))
    # COP: 1 decimal con coma (si hay dato), si no 0
    cop_str = fmt_decimal_coma(v_cop if v_cop is not None else 0, ndigits=1)

    # Colores y estilos
    border_color = "#6CC04A" if marcha == 1 else "#BEBEBE"  # verde vs gris
    bar_color = "#E00707"  # rojo barra
    box_shadow = "0 0 0 2px " + border_color

    # Geometría
    outer_h = altura_px
    outer_w = 200  # ancho del bloque; puedes ajustar si necesitas más compacto
    inner_h = outer_h - 40  # altura de la caja blanca interna
    inner_w = 90
    bar_h   = int((carga_pct / 100) * (inner_h - 10))  # relleno vertical (con margen)
    # HTML del bloque
    html = f"""
    <div style="
        width:{outer_w}px; height:{outer_h}px; 
        border-radius:16px; 
        box-shadow:{box_shadow};
        background-color:rgba(255,255,255,0.60);
        padding:8px 10px; 
        display:flex; 
        flex-direction:row; 
        align-items:center; 
        justify-content:flex-start;
        column-gap:12px;">
        <!-- Columna izquierda: barra -->
        <div style="display:flex; flex-direction:column; align-items:center;">
            <div style="
                width:{inner_w}px; height:{inner_h}px; 
                background-color:#FFFFFF; 
                border:2px solid #999; 
                border-radius:6px; 
                position:relative; overflow:hidden;">
                <!-- RELLENO ROJO desde abajo -->
                <div style="
                    position:absolute; 
                    bottom:2px; left:2px; 
                    width:{inner_w-4}px; 
                    height:{bar_h}px; 
                    background:{bar_color};
                    border-top:1px solid #990000;
                    border-left:1px solid #990000;
                    border-right:1px solid #990000;">
                </div>
            </div>
        </div>

        <!-- Columna derecha: textos -->
        <div style="display:flex; flex-direction:column; align-items:flex-start;">
            <div style="font-weight:900; font-size:18px; color:#333; margin-bottom:6px;">
                {nombre_equipo}
            </div>
            <div style="font-size:13px; color:#666; line-height:1.1;">% <b>USO</b></div>
            <div style="font-size:22px; font-weight:800; color:#222; margin-bottom:6px;">
                {fmt_int(carga_pct)} %
            </div>
            <div style="font-size:13px; color:#666; line-height:1.1;"><b>COP</b></div>
            <div style="font-size:24px; font-weight:900; color:#222;">
                {cop_str}
            </div>
        </div>
    </div>
    """
    col_placeholder.markdown(html, unsafe_allow_html=True)

# ============================================================
# APP
# ============================================================
require_login()
aplicar_fondo_css()

# ------------------------------------------------------------
# CABECERA: FECHA / HORA / TIEMPO (desplazadas a la izquierda)
# ------------------------------------------------------------
c1, c2, c3 = st.columns([1.4, 1.4, 1.2])
with c3:
    hoy  = datetime.now(TZ).strftime("%Y-%m-%d")
    hora = datetime.now(TZ).strftime("%H:%M")

    # -> padding-right grande para NO pisar logo FCC (ajustado aún más)
    st.markdown(
        f"""
        <div style="text-align:right; padding-right:520px;">
            <div style="font-size:36px; font-weight:800; color:#111;">{hoy}</div>
            <div style="font-size:54px; font-weight:900; color:#111; margin-top:-10px;">{hora}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    e, t_c, f_c, hum, v_kmh = obtener_tiempo_madrid()
    if e:
        st.markdown(
            f"""
            <div style="text-align:right; padding-right:520px;
                        font-size:18px; font-weight:600; color:#222;">
                {e} · <b>{t_c:.1f}°C</b><br>
                <span style="font-size:14px;color:#333">
                    Sensación {f_c:.1f}°C · Humedad {hum}% · Viento {v_kmh} km/h
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )

# ------------------------------------------------------------
# CARGA DE DATOS
# ------------------------------------------------------------
df = supabase_cargar_hoy()
if df.empty:
    st.info("Sin datos para hoy.")
    time.sleep(60)
    st.rerun()

# Últimos valores (para instantáneo y KPIs)
last_idx = df.groupby("punto_alias")["timestamp_utc"].idxmax()
df_last  = df.loc[last_idx, ["punto_alias", "valor", "hora_local"]]

# Instantáneo (T1..T5)
inst_vals = []
for a in ALIASES_INSTANT:
    v = df_last[df_last["punto_alias"] == a]["valor"]
    inst_vals.append(float(v.iloc[0]) if not v.empty else 0.0)
df_instant = pd.DataFrame({"alias": ALIASES_INSTANT, "valor": inst_vals})
df_instant["valor_fmt"] = df_instant["valor"].apply(fmt_int)

# Acumulado diario (kWh)
df_kwh_series = (
    df[df["punto_alias"].isin(ALIASES_INSTANT)]
    .assign(kwh=lambda x: x["valor"] / 60)
    .groupby("punto_alias")["kwh"].sum()
)
df_acum = pd.DataFrame({"alias": ALIASES_INSTANT,
                        "kwh": [df_kwh_series.get(a, 0) for a in ALIASES_INSTANT]})
df_acum["kwh_fmt"] = df_acum["kwh"].apply(fmt_int)

total_inst = float(sum(inst_vals))
total_kwh  = float(df_acum["kwh"].sum())

# ------------------------------------------------------------
# TARTAS + TOTALES (muy juntas)
# ------------------------------------------------------------
col_t1, col_t2, col_tot = st.columns([1.05, 1.05, 0.75], gap="small")

with col_t1:
    st.markdown("### Potencia instantánea")
    fig1 = px.pie(
        df_instant, names="alias", values="valor",
        color="alias", color_discrete_map=COLOR_MAP,
        hole=0.35, height=210, custom_data=["valor_fmt"]
    )
    fig1.update_traces(
        textposition="inside",
        texttemplate="%{label}<br>%{customdata[0]} kW (%{percent})"
    )
    fig1.update_layout(
        showlegend=True, legend_title_text="Potencias",
        margin=dict(l=0, r=0, t=0, b=0)
    )
    st.plotly_chart(fig1, use_container_width=True)

with col_t2:
    st.markdown("### Energía acumulada del día")
    fig2 = px.pie(
        df_acum, names="alias", values="kwh",
        color="alias", color_discrete_map=COLOR_MAP,
        hole=0.35, height=210, custom_data=["kwh_fmt"]
    )
    # -> Etiquetas con alias + kWh + %
    fig2.update_traces(
        textposition="inside",
        texttemplate="%{label}<br>%{customdata[0]} kWh (%{percent})"
    )
    fig2.update_layout(showlegend=False, margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig2, use_container_width=True)

with col_tot:
    st.markdown("### Total Instantáneo")
    st.markdown(
        f"<div style='font-size:48px; font-weight:900; color:#111;'>{fmt_int(total_inst)} kW</div>",
        unsafe_allow_html=True
    )
    st.markdown("### Acumulado Hoy")
    st.markdown(
        f"<div style='font-size:42px; font-weight:800; color:#333;'>{fmt_int(total_kwh)} kWh</div>",
        unsafe_allow_html=True
    )

# ------------------------------------------------------------
# GRÁFICO DE LÍNEAS (más ancho y alto que la versión compacta)
# + BLOQUES DE EQUIPO EN UNA FILA A LA DERECHA (Opción A)
# ------------------------------------------------------------
# Izquierda: líneas (más grande que la versión mínima)
line_left, line_right = st.columns([0.60, 1.40], gap="small")  # 30% más largo que 0.45 aprox.

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
            mode='lines', name=col, line=dict(width=1.4)
        ))
    # Ocultar eje X por tema UTC/UTC+1
    fig_line.update_xaxes(showgrid=False, showticklabels=False, ticks="", zeroline=False, visible=True)
    fig_line.update_yaxes(showgrid=True)
    fig_line.update_layout(
        height=LINE_HEIGHT,                # 216 px (confirmado)
        margin=dict(l=0, r=0, t=2, b=0),
        legend=dict(orientation="h", y=1.02, x=0, font=dict(size=10))
    )
    st.plotly_chart(fig_line, use_container_width=True)

# Derecha: 4 bloques en una sola fila (Opción A)
with line_right:
    cont = st.container()
    bc_cols = cont.columns(4, gap="small")
    # Render de cada bloque usando los alias confirmados:
    render_bloque_equipo(
        bc_cols[0],
        "BC FELIPE",
        alias_marcha="BC FELIPE",
        alias_carga="CARGA BC FELIPE",
        alias_cop="COP BC FELIPE",
        altura_px=LINE_HEIGHT
    )
    render_bloque_equipo(
        bc_cols[1],
        "BC CARLOS",
        alias_marcha="BC CARLOS",
        alias_carga="CARGA BC CARLOS",
        alias_cop="COP BC CARLOS",
        altura_px=LINE_HEIGHT
    )
    render_bloque_equipo(
        bc_cols[2],
        "GF1",
        alias_marcha="GF1",
        alias_carga="CARGA GF1",
        alias_cop="COP GF1",
        altura_px=LINE_HEIGHT
    )
    render_bloque_equipo(
        bc_cols[3],
        "GF2",
        alias_marcha="GF2",
        alias_carga="CARGA GF2",
        alias_cop="COP GF2",
        altura_px=LINE_HEIGHT
    )

# ------------------------------------------------------------
# AUTO REFRESH
# ------------------------------------------------------------
time.sleep(60)
st.rerun()
