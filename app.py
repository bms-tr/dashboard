# app.py

import base64
import time
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

LINE_HEIGHT = 216

def fmt_int(x: float) -> str:
    try:
        return f"{float(x):,.0f}".replace(",", ".")
    except:
        return "0"

def fmt_decimal_coma(x: float, ndigits: int = 1) -> str:
    try:
        return f"{float(x):.{ndigits}f}".replace(".", ",")
    except:
        return "0"

# ============================================================
# LOGIN
# ============================================================
def require_login():
    if st.session_state["auth_ok"]:
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
            background-size: contain !important;
            background-position: top center !important;
            background-repeat: no-repeat !important;
        }}

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
# SUPABASE
# ============================================================
def iso_z(dt): return dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def supabase_cargar_hoy():
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
    df["hora_local"] = df["timestamp_utc"].dt.tz_convert(TZ)
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["punto_alias"] = df["punto_alias"].astype(str).str.strip()
    return df.sort_values("timestamp_utc")


# ============================================================
# METEO
# ============================================================
def obtener_tiempo_madrid():
    try:
        r = requests.get(
            "https://wttr.in/Madrid?format=j1",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=7
        )
        j = r.json()
        return (
            j["current_condition"][0]["weatherDesc"][0]["value"],
            float(j["current_condition"][0]["temp_C"]),
            float(j["current_condition"][0]["FeelsLikeC"]),
            int(j["current_condition"][0]["humidity"]),
            int(j["current_condition"][0]["windspeedKmph"]),
        )
    except:
        return None, None, None, None, None

# ============================================================
# KPIs EQUIPOS (BC FELIPE / BC CARLOS / GF1 / GF2)
# ============================================================
def ultimo_valor(df, alias):
    rows = df[df["punto_alias"] == alias]
    if rows.empty: return None
    idx = rows["timestamp_utc"].idxmax()
    val = rows.loc[idx, "valor"]
    try:
        return float(val)
    except:
        return None

def render_bloque_equipo(col, nombre, alias_marcha, alias_carga, alias_cop, altura):
    v_marcha = ultimo_valor(df, alias_marcha)
    v_carga  = ultimo_valor(df, alias_carga)
    v_cop    = ultimo_valor(df, alias_cop)

    marcha = 1 if (v_marcha is not None and v_marcha >= 1) else 0
    carga_pct = int(max(0, min(100, v_carga if v_carga else 0)))
    cop_str = fmt_decimal_coma(v_cop if v_cop else 0)

    border_color = "#6CC04A" if marcha else "#BEBEBE"
    bar_color = "#E00707"

    outer_h = altura
    outer_w = 190
    inner_h = outer_h - 45
    inner_w = 90
    bar_h = int((carga_pct / 100) * (inner_h - 10))

    html = f"""
    <div style="
        width:{outer_w}px; height:{outer_h}px;
        background:rgba(255,255,255,0.65);
        border-radius:16px;
        box-shadow:0 0 0 3px {border_color};
        display:flex; flex-direction:row;
        padding:6px 10px;
        column-gap:10px;">
        
        <div style="display:flex; flex-direction:column; align-items:center;">
            <div style="
                width:{inner_w}px; height:{inner_h}px;
                background:white; border:2px solid #999;
                border-radius:6px; position:relative; overflow:hidden;">
                
                <div style="
                    position:absolute;
                    bottom:2px; left:2px;
                    width:{inner_w-4}px;
                    height:{bar_h}px;
                    background:{bar_color};">
                </div>
            </div>
        </div>

        <div style="display:flex; flex-direction:column;">
            <div style="font-size:18px; font-weight:900; color:#333;">{nombre}</div>

            <div style="font-size:13px; color:#555; line-height:1.1; margin-top:4px;">
                % USO
            </div>
            <div style="font-size:22px; font-weight:800; color:#222;">
                {carga_pct} %
            </div>

            <div style="font-size:13px; margin-top:6px; color:#555;">COP</div>
            <div style="font-size:24px; font-weight:900; color:#222;">
                {cop_str}
            </div>
        </div>
    </div>
    """
    col.html(html)

# ============================================================
# APP
# ============================================================
require_login()
aplicar_fondo_css()

# ============================================================
# CABECERA CENTRADA (NO TRUNCA, NO TAPA LOGO)
# ============================================================
fila = st.container()
c1, c2, c3 = fila.columns([1,1,1])

with c2:
    hoy = datetime.now(TZ).strftime("%Y-%m-%d")
    hora = datetime.now(TZ).strftime("%H:%M")
    estado,t_c,f_c,hum,v_kmh = obtener_tiempo_madrid()

    st.markdown(f"""
    <div style="text-align:center;">
        <div style="font-size:36px; font-weight:800; color:#111;">{hoy}</div>
        <div style="font-size:54px; font-weight:900; color:#111; margin-top:-8px;">{hora}</div>
        <div style="font-size:17px; font-weight:600; color:#222; margin-top:-4px;">
            {estado if estado else ""}
        </div>
    </div>
    """, unsafe_allow_html=True)

# ============================================================
# CARGA DATOS
# ============================================================
df = supabase_cargar_hoy()

if df.empty:
    st.info("Sin datos.")
    time.sleep(60); st.rerun()

last_idx = df.groupby("punto_alias")["timestamp_utc"].idxmax()
df_last = df.loc[last_idx]

inst_vals = []
for a in ALIASES_INSTANT:
    v = df_last[df_last["punto_alias"]==a]["valor"]
    inst_vals.append(float(v.iloc[0]) if not v.empty else 0)

df_instant = pd.DataFrame({"alias":ALIASES_INSTANT,"valor":inst_vals})
df_instant["valor_fmt"]=df_instant["valor"].apply(fmt_int)

df_kwh_series = (
    df[df["punto_alias"].isin(ALIASES_INSTANT)]
    .assign(kwh=lambda x:x["valor"]/60)
    .groupby("punto_alias")["kwh"].sum()
)
df_acum = pd.DataFrame({
    "alias":ALIASES_INSTANT,
    "kwh":[df_kwh_series.get(a,0) for a in ALIASES_INSTANT]
})
df_acum["kwh_fmt"]=df_acum["kwh"].apply(fmt_int)

total_inst = sum(inst_vals)
total_kwh  = float(df_acum["kwh"].sum())

# ============================================================
# TARTAS + TOTALES
# ============================================================
col_t1,col_t2,col_tot = st.columns([1.05,1.05,0.75],gap="small")

with col_t1:
    st.markdown("### Potencia instantánea")
    fig1 = px.pie(
        df_instant,names="alias",values="valor",
        color="alias",color_discrete_map=COLOR_MAP,
        hole=0.37,height=210,custom_data=["valor_fmt"]
    )
    fig1.update_traces(textposition="inside",
        texttemplate="%{label}<br>%{customdata[0]} kW<br>%{percent}")
    fig1.update_layout(showlegend=True,margin=dict(l=0,r=0,t=5,b=0))
    st.plotly_chart(fig1,use_container_width=True)

with col_t2:
    st.markdown("### Energía acumulada del día")
    fig2 = px.pie(
        df_acum,names="alias",values="kwh",
        color="alias",color_discrete_map=COLOR_MAP,
        hole=0.37,height=210,custom_data=["kwh_fmt"]
    )
    fig2.update_traces(textposition="inside",
        texttemplate="%{label}<br>%{customdata[0]} kWh<br>%{percent}")
    fig2.update_layout(showlegend=False,margin=dict(l=0,r=0,t=5,b=0))
    st.plotly_chart(fig2,use_container_width=True)

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

# ============================================================
# GRÁFICO DE LÍNEAS + 4 BLOQUES (OPCIÓN A)
# ============================================================
line_left,line_right = st.columns([0.60,1.40],gap="small")

with line_left:
    st.markdown("### Potencias del día")
    df_lines = df[df["punto_alias"].isin(ALIASES_LINES)]
    pivot = df_lines.pivot_table(index="hora_local",columns="punto_alias",values="valor").sort_index()

    for a in ALIASES_LINES:
        if a not in pivot.columns:
            pivot[a]=None
    pivot=pivot[ALIASES_LINES]

    fig = go.Figure()
    for col in ALIASES_LINES:
        fig.add_trace(go.Scatter(x=pivot.index,y=pivot[col],mode="lines",name=col,line=dict(width=1.5)))

    fig.update_xaxes(showgrid=False,showticklabels=False,ticks="",zeroline=False,visible=True)
    fig.update_yaxes(showgrid=True)

    fig.update_layout(
        height=LINE_HEIGHT,
        margin=dict(l=0,r=0,t=5,b=0),
        legend=dict(orientation="h",y=1.02,x=0,font=dict(size=10))
    )
    st.plotly_chart(fig,use_container_width=True)

with line_right:
    cA,cB,cC,cD = st.columns(4,gap="small")
    render_bloque_equipo(cA,"BC FELIPE","BC FELIPE","CARGA BC FELIPE","COP BC FELIPE",LINE_HEIGHT)
    render_bloque_equipo(cB,"BC CARLOS","BC CARLOS","CARGA BC CARLOS","COP BC CARLOS",LINE_HEIGHT)
    render_bloque_equipo(cC,"GF1","GF1","CARGA GF1","COP GF1",LINE_HEIGHT)
    render_bloque_equipo(cD,"GF2","GF2","CARGA GF2","COP GF2",LINE_HEIGHT)

# ============================================================
# AUTO REFRESH
# ============================================================
time.sleep(60)
st.rerun()
