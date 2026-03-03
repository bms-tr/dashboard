import time
import re
import streamlit as st
import pandas as pd
import requests
import plotly.express as px
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo  # Python 3.11 OK

# ------------------------------------------------------------
# CONFIGURACIÓN
# ------------------------------------------------------------
st.set_page_config(page_title="DASHBOARD FCC- TEATRO REAL INFRAESTRUCTURAS", layout="wide")
LOCAL_TZ = ZoneInfo("Europe/Madrid")

AUTO_REFRESH_SECONDS = 60   # refresco cada minuto
LOOKBACK_HOURS = 24         # ventana: ahora - 24 h (ajústalo si quieres)

# Estilos para modo monitor y aspecto sobrio
st.markdown(
    """
    <style>
      #MainMenu {visibility: hidden;}
      header {visibility: hidden;}
      footer {visibility: hidden;}
      .big-total {font-size: 64px; font-weight: 800; line-height: 1.0; margin: 0.2rem 0 1rem 0;}
      .sub {font-size: 14px; color: #666;}
    </style>
    """,
    unsafe_allow_html=True
)

# Mantener estado de login en la pestaña
st.session_state.setdefault("auth_ok", False)

# ------------------------------------------------------------
# LOGIN (persistente mientras la pestaña siga abierta)
# ------------------------------------------------------------
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
            st.error("No se han encontrado secretos. Revisa el secrets.toml.")
    st.stop()

require_login()

# ------------------------------------------------------------
# LECTURA SUPABASE (REST)
# ------------------------------------------------------------
def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def supabase_select_last_hours(hours: int = LOOKBACK_HOURS) -> pd.DataFrame:
    """
    Trae lecturas del rango [now-hrs, now] y devuelve:
      timestamp_utc (UTC), punto_alias, punto_clave, valor (float)
    """
    base_url = st.secrets["supabase"]["url"].rstrip("/")
    key      = st.secrets["supabase"]["key"]
    table    = st.secrets["supabase"]["table"]

    to_dt   = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(hours=hours)

    params = {
        "select": "timestamp_utc,punto_alias,punto_clave,valor",
        "timestamp_utc": f"gte.{iso_z(from_dt)}",
        "order": "timestamp_utc.asc"
    }
    query = urlencode(params) + f"&timestamp_utc=lte.{iso_z(to_dt)}"
    url = f"{base_url}/rest/v1/{table}?{query}"

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()

    df = pd.DataFrame(r.json())
    if df.empty:
        return df

    # Tipar
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["punto_alias"] = df["punto_alias"].astype(str).str.strip()
    return df

# ------------------------------------------------------------
# UTILIDADES
# ------------------------------------------------------------
TARGET_REGEX = re.compile(r"^POT\s*T([1-5])$", re.IGNORECASE)  # POT T1..T5 exactamente
def is_target(alias: str) -> bool:
    return bool(TARGET_REGEX.match((alias or "").strip()))

def target_key(alias: str) -> str:
    """Normaliza el alias a 'POT T1'..'POT T5' para usarlo como clave estable."""
    m = TARGET_REGEX.match((alias or "").strip())
    return f"POT T{m.group(1)}" if m else ""

def is_alumbrado(alias: str) -> bool:
    return "ALUMBR" in (alias or "").upper()  # p.ej. 'POT T4 ALUMBRADO'

# Colores neutros fijos por alias (sobrios, profesionales)
COLOR_MAP = {
    "POT T1": "#4F6D7A",  # slate blue-gray
    "POT T2": "#7D98A1",  # muted blue-gray
    "POT T3": "#9FB3C8",  # soft steel
    "POT T4": "#C3CFD9",  # pale slate
    "POT T5": "#8FA999",  # muted sage
}

# Orden fijo
ORDER = ["POT T1", "POT T2", "POT T3", "POT T4", "POT T5"]

# ------------------------------------------------------------
# APP
# ------------------------------------------------------------
st.title("📊 FCC – INFRAESTRUCTURAS TR CONTROL CENTRAL")

# 1) Leer datos recientes
with st.spinner("Cargando datos…"):
    try:
        df = supabase_select_last_hours(hours=LOOKBACK_HOURS)
    except Exception as e:
        st.error(f"Error leyendo Supabase: {e}")
        time.sleep(AUTO_REFRESH_SECONDS)
        st.experimental_rerun()

if df.empty:
    st.info(f"No hay datos en las últimas {LOOKBACK_HOURS} horas.")
    time.sleep(AUTO_REFRESH_SECONDS)
    st.experimental_rerun()

# 2) Excluir cualquier registro de alumbrado (p. ej., 'POT T4 ALUMBRADO')
df = df[~df["punto_alias"].apply(is_alumbrado)]

# 3) Quedarnos solo con POT T1..POT T5 que existan en BBDD (según vengan)
df_targets = df[df["punto_alias"].apply(is_target)].copy()
if not df_targets.empty:
    # Normalizar clave 'POT T1'..'POT T5' sin tocar etiqueta original
    df_targets["target_key"] = df_targets["punto_alias"].apply(target_key)
    # Último valor por cada target_key dentro de la ventana
    last_idx = df_targets.groupby("target_key")["timestamp_utc"].idxmax()
    df_last = df_targets.loc[last_idx, ["target_key", "valor", "timestamp_utc"]].copy()
else:
    df_last = pd.DataFrame(columns=["target_key", "valor", "timestamp_utc"])

# 4) Construir serie final en orden fijo (si falta alguno, 0)
rows = []
for key in ORDER:
    match = df_last[df_last["target_key"] == key]
    val = float(match["valor"].iloc[0]) if not match.empty and pd.notna(match["valor"].iloc[0]) else 0.0
    rows.append({"alias": key, "valor": val})
df_pie = pd.DataFrame(rows)

# 5) Suma total y última actualización global
last_ts_utc = df["timestamp_utc"].max()
last_ts_local = last_ts_utc.astimezone(LOCAL_TZ) if pd.notna(last_ts_utc) else None
total_kw = df_pie["valor"].sum()

# ------------------------------------------------------------
# PINTADO
# ------------------------------------------------------------
st.markdown(f"<div class='big-total'>{total_kw:,.2f} kW</div>", unsafe_allow_html=True)
if last_ts_local:
    st.markdown(f"<div class='sub'>Última actualización: {last_ts_local.strftime('%Y-%m-%d %H:%M:%S %Z')}</div>", unsafe_allow_html=True)
st.markdown("---")

# Tarta (solo si hay algún valor > 0)
if (df_pie["valor"] > 0).any():
    # Mapeo de color solo para los presentes
    present = df_pie["alias"].tolist()
    color_map_present = {k: COLOR_MAP[k] for k in present if k in COLOR_MAP}

    fig = px.pie(
        df_pie,
        names="alias",
        values="valor",
        hole=0.35,
        title=None,
        color="alias",
        color_discrete_map=color_map_present
    )
    fig.update_traces(
        textposition="inside",
        textinfo="label+percent",
        hovertemplate="%{label}: %{value:.2f} kW<br>%{percent}"
    )
    fig.update_layout(
        template="simple_white",
        showlegend=True,
        legend_title_text="Potencias",
        margin=dict(l=10, r=10, t=10, b=10)
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No hay valores > 0 para POT T1..T5 en la última lectura de la ventana.")

# Tabla pequeña informativa (en el mismo orden)
st.markdown("#### Valores actuales (kW)")
st.dataframe(
    df_pie.assign(valor=lambda d: d["valor"].round(2)),
    use_container_width=True, height=240
)

st.caption(f"© FCC INDUSTRIAL 2026 • Refresco automático cada {AUTO_REFRESH_SECONDS} s • Ventana {LOOKBACK_HOURS} h")

# ------------------------------------------------------------
# AUTO-REFRESH
# ------------------------------------------------------------
time.sleep(AUTO_REFRESH_SECONDS)
st.experimental_rerun()
