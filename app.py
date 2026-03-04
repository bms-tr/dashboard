import base64
import time
import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from pathlib import Path

# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================
st.set_page_config(page_title="BMS Dashboard", layout="wide")
TZ = ZoneInfo("Europe/Madrid")
st.session_state.setdefault("auth_ok", False)

# Ruta del fondo (archivo en la raíz del repo)
BG_IMAGE_PATH = Path("FONDO_DASHBOARD.JPG")

# Márgenes de seguridad para evitar solapamientos con el fondo
SAFE_TOP_PX   = 0
SAFE_LEFT_PX  = 0
SAFE_RIGHT_PX = 0

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
# FONDO DE PANTALLA + OCULTAR HEADER/MENÚ/FOOTER
# ============================================================
def aplicar_fondo(bg_path: Path):
    try:
        with open(bg_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except Exception:
        return

    st.markdown(
        f"""
        <style>
        .stApp {{
            background: url('data:image/jpg;base64,{b64}') no-repeat center center fixed !important;
            background-size: cover !important;
        }}

        /* Ocultar menú */
        #MainMenu {{display: none !important;}}

        /* Ocultar header Streamlit */
        header[data-testid="stHeader"] {{
            display: none !important;
        }}

        /* Ocultar pie de página */
        footer {{display: none !important;}}

        /* Ocultar separador superior (decoración) */
        [data-testid="stDecoration"] {{
            display: none !important;
        }}

        /* Evitar márgenes que deja Streamlit */
        div.block-container {{
            padding-top: {SAFE_TOP_PX}px !important;
            padding-left: {SAFE_LEFT_PX}px !important;
            padding-right: {SAFE_RIGHT_PX}px !important;
        }}

        section.main > div {{
            padding-bottom: 0px !important;
            margin-bottom: 0px !important;
        }}
        </style>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# SUPABASE (últimos primero → reorden ascendente)
# ============================================================
def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def supabase_select_range(days: int = 1, punto_clave: str | None = None) -> pd.DataFrame:
    base_url = st.secrets["supabase"]["url"].rstrip("/")
    key      = st.secrets["supabase"]["key"]
    table    = st.secrets["supabase"]["table"]

    to_dt   = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(days=days)

    # Pedimos lo último primero para evitar pérdidas si hay límite
    query_parts = [
        "select=timestamp_utc,punto_alias,punto_clave,valor",
        "order=timestamp_utc.desc",
        f"timestamp_utc=gte.{iso_z(from_dt)}",
        f"timestamp_utc=lte.{iso_z(to_dt)}"
    ]

    if punto_clave:
        query_parts.append(f"punto_clave=eq.{punto_clave}")

    query = "&".join(query_parts)
    url = f"{base_url}/rest/v1/{table}?{query}"

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Cache-Control": "no-cache",
        "Range": "0-28799"   # ← hasta 28.800 lecturas / día
    }

    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()

    df = pd.DataFrame(r.json())
    if df.empty:
        return df

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["punto_alias"] = df["punto_alias"].astype(str).str.strip()

    # Reordenamos hacia arriba para gráficos
    df = df.sort_values("timestamp_utc", ascending=True).reset_index(drop=True)
    return df


# ============================================================
# TIEMPO – Estable (wttr.in)
# ============================================================
def obtener_tiempo_madrid():
    try:
        r = requests.get("https://wttr.in/Madrid?format=j1", timeout=6)
        j = r.json()
        estado     = j["current_condition"][0]["weatherDesc"][0]["value"]
        temp_c     = float(j["current_condition"][0]["temp_C"])
        feels_c    = float(j["current_condition"][0]["FeelsLikeC"])
        humedad    = int(j["current_condition"][0]["humidity"])
        viento_kmh = int(j["current_condition"][0]["windspeedKmph"])
        return estado, temp_c, feels_c, humedad, viento_kmh
    except:
        return None, None, None, None, None



# ============================================================
# APP
# ============================================================
require_login()
aplicar_fondo(BG_IMAGE_PATH)

st.title("📊 BMS Dashboard")
st.caption("Visualización TV HD • Auto‑refresh 60s • Hora local (Madrid)")


# ============================================================
# CABECERA SUPERIOR (derecha): FECHA (grande), HORA (más grande), TIEMPO
# ============================================================
col_left, col_spacer, col_right = st.columns([1, 2, 1])

with col_right:
    hoy  = datetime.now(TZ).strftime("%Y-%m-%d")
    hora = datetime.now(TZ).strftime("%H:%M")

    # Fecha + Hora
    st.markdown(
        f"""
        <div style="text-align:right;">
            <div style="font-size:38px; font-weight:800; color:#111; line-height:1.1;">
                {hoy}
            </div>
            <div style="font-size:54px; font-weight:900; color:#111; line-height:1.0;">
                {hora}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Tiempo
    estado, temp_c, feels_c, humedad, viento_kmh = obtener_tiempo_madrid()

    if estado:
        st.markdown(
            f"""
            <div style="text-align:right;
                        font-size:20px;
                        font-weight:600;
                        color:#222;
                        margin-top:4px;">
                {estado} · <b>{temp_c:.1f}°C</b><br>
                <span style="font-size:15px;">
                Sensación {feels_c:.1f}°C · Humedad {humedad}% · Viento {viento_kmh} km/h
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            "<div style='text-align:right; font-size:16px; color:#333;'>Tiempo no disponible (se reintentará)</div>",
            unsafe_allow_html=True
        )


# ============================================================
# SIDEBAR FILTROS
# ============================================================
with st.sidebar:
    st.header("Filtros")
    days = st.slider("Días a mostrar", 1, 60, 7)
    punto_clave = st.text_input("punto_clave exacto", value="")
    show_raw = st.checkbox("Mostrar tabla completa", False)


# ============================================================
# LECTURA DE SUPABASE
# ============================================================
try:
    df = supabase_select_range(days=days, punto_clave=(punto_clave or None))
except Exception as e:
    st.error(f"Error leyendo Supabase: {e}")
    st.stop()

if df.empty:
    st.info("No hay datos para este rango.")
    time.sleep(60)
    st.experimental_rerun()

df["hora_local"] = df["timestamp_utc"].dt.tz_convert(TZ)


# ============================================================
# CUERPO PRINCIPAL
# ============================================================
colL, colR = st.columns([2, 1])

with colL:
    st.subheader("Serie temporal")
    puntos = sorted(df["punto_alias"].unique().tolist())
    sel = st.multiselect("Selecciona puntos", puntos, default=puntos[:5])

    if sel:
        df_plot = df[df["punto_alias"].isin(sel)]
        pivot = df_plot.pivot_table(
            index="hora_local",
            columns="punto_alias",
            values="valor",
            aggfunc="mean"
        ).sort_index()
        st.line_chart(pivot)
    else:
        st.info("Selecciona al menos un punto.")


with colR:
    st.subheader("KPIs (último valor)")
    last_idx = df.groupby("punto_alias")["timestamp_utc"].idxmax()
    df_last = df.loc[last_idx, ["punto_alias", "valor", "hora_local"]].sort_values("punto_alias")

    for _, row in df_last.iterrows():
        st.metric(
            label=row["punto_alias"],
            value=f"{row['valor']:.2f}",
            help=row["hora_local"].strftime("%Y-%m-%d %H:%M")
        )

    st.markdown("---")
    st.subheader("Tabla")

    if show_raw:
        st.dataframe(
            df.sort_values(["punto_alias", "timestamp_utc"], ascending=[True, False]),
            height=420, use_container_width=True
        )
    else:
        n = st.slider("Últimos N", 10, 500, 100)
        df_sorted = df.sort_values(["punto_alias", "timestamp_utc"],
                                   ascending=[True, False])
        df_tail = df_sorted.groupby("punto_alias").head(n)
        st.dataframe(df_tail, height=420, use_container_width=True)


# ============================================================
# AUTO‑REFRESH
# ============================================================
time.sleep(60)
st.experimental_rerun()
