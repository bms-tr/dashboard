import base64
import time
import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

# ============================================================
# CONFIG
# ============================================================
st.set_page_config(page_title="BMS Dashboard", layout="wide")
TZ = ZoneInfo("Europe/Madrid")

# Login persistente
st.session_state.setdefault("auth_ok", False)

# Ruta correcta del fondo
BG_IMAGE_PATH = Path("FONDO_DAHSBOARD.jpg")

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
        if u == st.secrets["auth"]["user"] and p == st.secrets["auth"]["password"]:
            st.session_state["auth_ok"] = True
            st.experimental_rerun()
        else:
            st.error("Credenciales incorrectas.")
    st.stop()

# ============================================================
# FONDO + ELIMINAR HEADER / FOOTER
# ============================================================
def aplicar_fondo():
    try:
        with open(BG_IMAGE_PATH, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except:
        return

    st.markdown(
        f"""
        <style>

        /* Fondo */
        .stApp {{
            background: url("data:image/jpg;base64,{b64}") no-repeat center center fixed;
            background-size: cover;
        }}

        /* Quitar header + menú */
        header[data-testid="stHeader"] {{
            display: none !important;
        }}
        #MainMenu {{visibility: hidden !important;}}

        /* Quitar barra superior */
        [data-testid="stDecoration"] {{
            display: none !important;
        }}

        /* Quitar footer */
        footer {{display: none !important;}}

        /* Quitar padding superior que deja Streamlit */
        .block-container {{
            padding-top: 0rem !important;
        }}

        </style>
        """,
        unsafe_allow_html=True
    )

# ============================================================
# TIEMPO — wttr.in con User-Agent de navegador
# ============================================================
def obtener_tiempo_madrid():
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get("https://wttr.in/Madrid?format=j1", headers=headers, timeout=5)
        j = r.json()
        estado = j["current_condition"][0]["weatherDesc"][0]["value"]
        temp_c = float(j["current_condition"][0]["temp_C"])
        feels_c = float(j["current_condition"][0]["FeelsLikeC"])
        humedad = int(j["current_condition"][0]["humidity"])
        viento_kmh = int(j["current_condition"][0]["windspeedKmph"])
        return estado, temp_c, feels_c, humedad, viento_kmh
    except:
        return None, None, None, None, None

# ============================================================
# SUPABASE
# ============================================================
def iso_z(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def supabase_select_range(days=1, punto_clave=None):
    base_url = st.secrets["supabase"]["url"].rstrip("/")
    key      = st.secrets["supabase"]["key"]
    table    = st.secrets["supabase"]["table"]

    to_dt   = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(days=days)

    q = [
        "select=timestamp_utc,punto_alias,punto_clave,valor",
        "order=timestamp_utc.desc",
        f"timestamp_utc=gte.{iso_z(from_dt)}",
        f"timestamp_utc=lte.{iso_z(to_dt)}"
    ]
    if punto_clave:
        q.append(f"punto_clave=eq.{punto_clave}")

    url = f"{base_url}/rest/v1/{table}?" + "&".join(q)

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Range": "0-28799",
        "Cache-Control": "no-cache"
    }

    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()

    df = pd.DataFrame(r.json())
    if df.empty:
        return df

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["punto_alias"] = df["punto_alias"].astype(str).str.strip()

    # Reorden ascendente
    return df.sort_values("timestamp_utc")

# ============================================================
# APP
# ============================================================
require_login()
aplicar_fondo()

# CABECERA: FECHA + HORA + TIEMPO
st.markdown("<br><br>", unsafe_allow_html=True)

col1, col2 = st.columns([2, 1])

with col2:
    fecha = datetime.now(TZ).strftime("%Y-%m-%d")
    hora  = datetime.now(TZ).strftime("%H:%M")

    st.markdown(
        f"""
        <div style="text-align:right; padding-right:10px;">
            <div style="font-size:38px; font-weight:800; color:white;">
                {fecha}
            </div>
            <div style="font-size:56px; font-weight:900; color:white; margin-top:-10px;">
                {hora}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    estado, temp_c, feels_c, humedad, viento_kmh = obtener_tiempo_madrid()
    if estado:
        st.markdown(
            f"""
            <div style="text-align:right; font-size:20px; font-weight:600; color:white;">
                {estado} · <b>{temp_c:.1f}°C</b><br>
                <span style="font-size:16px;">
                    Sensación {feels_c:.1f}°C · Humedad {humedad}% · Viento {viento_kmh} km/h
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            "<div style='text-align:right; font-size:18px; color:white;'>Tiempo no disponible</div>",
            unsafe_allow_html=True
        )

# =============================
# SIDEBAR
# =============================
with st.sidebar:
    st.header("Filtros")
    days = st.slider("Días a mostrar", 1, 60, 7)
    punto_clave = st.text_input("punto_clave exacto", "")
    show_raw = st.checkbox("Mostrar tabla completa", False)

# =============================
# DATOS
# =============================
df = supabase_select_range(days, punto_clave or None)

if df.empty:
    st.info("No hay datos.")
    time.sleep(60)
    st.experimental_rerun()

df["hora_local"] = df["timestamp_utc"].dt.tz_convert(TZ)

# =============================
# CUERPO PRINCIPAL
# =============================
colL, colR = st.columns([2, 1])

with colL:
    st.subheader("Serie temporal")
    puntos = sorted(df["punto_alias"].unique())
    sel = st.multiselect("Selecciona puntos", puntos, default=puntos[:5])

    if sel:
        dfp = df[df["punto_alias"].isin(sel)]
        pivot = dfp.pivot_table(index="hora_local", columns="punto_alias", values="valor")
        st.line_chart(pivot)

with colR:
    st.subheader("KPIs (último valor)")
    last_idx = df.groupby("punto_alias")["timestamp_utc"].idxmax()
    df_last = df.loc[last_idx].sort_values("punto_alias")

    for _, row in df_last.iterrows():
        st.metric(
            row["punto_alias"],
            f"{row['valor']:.2f}",
            help=row["hora_local"].strftime("%Y-%m-%d %H:%M")
        )

    st.markdown("---")
    if show_raw:
        st.dataframe(df)
    else:
        n = st.slider("Últimos N", 10, 500, 100)
        df_tail = df.sort_values("timestamp_utc", ascending=False).groupby("punto_alias").head(n)
        st.dataframe(df_tail)

# =============================
# AUTO REFRESH
# =============================
time.sleep(60)
st.experimental_rerun()
