import time
import streamlit as st
import pandas as pd
import requests
import plotly.express as px
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo  # Python 3.11 OK

# ------------------------------------------------------------
# CONFIGURACIÓN GENERAL
# ------------------------------------------------------------
st.set_page_config(page_title="BMS Dashboard", layout="wide")
LOCAL_TZ = ZoneInfo("Europe/Madrid")
AUTO_REFRESH_SECONDS = 60  # refresco cada minuto

# Ocultar menú/header/footer para modo monitor
st.markdown(
    """
    <style>
      #MainMenu {visibility: hidden;}
      header {visibility: hidden;}
      footer {visibility: hidden;}
      .big-total {font-size: 64px; font-weight: 800; line-height: 1.0; margin: 0.2rem 0 1rem 0;}
      .sub {font-size: 14px; color: #888;}
    </style>
    """,
    unsafe_allow_html=True
)

# Mantener estado de login entre refrescos de la página
st.session_state.setdefault("auth_ok", False)

# ------------------------------------------------------------
# LOGIN (solo lo justo para no volver a pedirlo en cada refresh)
# ------------------------------------------------------------
def require_login():
    # Si ya se autenticó en esta pestaña, no pedimos nada más
    if st.session_state.get("auth_ok"):
        return True

    st.title("🔐 Acceso")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")

    if st.button("Entrar"):
        try:
            if u == st.secrets["auth"]["user"] and p == st.secrets["auth"]["password"]:
                st.session_state["auth_ok"] = True
                st.experimental_rerun()  # vuelve a cargar ya autenticado
            else:
                st.error("Credenciales incorrectas.")
        except Exception:
            # Si no encuentra secretos, muestra error claro
            st.error("No se han encontrado secretos. Revisa el secrets.toml.")
    st.stop()

require_login()

# ------------------------------------------------------------
# SUPABASE REST
# ------------------------------------------------------------
def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

@st.cache_data(ttl=50, show_spinner=False)
def supabase_select_last_hours(hours: int = 24) -> pd.DataFrame:
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
        "order": "timestamp_utc.asc",
    }
    query = urlencode(params) + f"&timestamp_utc=lte.{iso_z(to_dt)}"
    url = f"{base_url}/rest/v1/{table}?{query}"

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code >= 400:
        raise RuntimeError(f"Supabase SELECT HTTP {r.status_code}: {r.text}")

    df = pd.DataFrame(r.json())
    if df.empty:
        return df

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    if "valor" in df.columns:
        df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    return df

# ------------------------------------------------------------
# LÓGICA DE POTENCIAS (POT T1..T5) Y EXCLUSIÓN DE ALUMBRADO
# ------------------------------------------------------------
def normalize_alias(s: str | None) -> str:
    if not s:
        return ""
    s = " ".join(str(s).split())
    return s.upper()

TARGET_ALIASES = ["POT T1", "POT T2", "POT T3", "POT T4", "POT T5"]
TARGET_ALIASES_NORM = [normalize_alias(x) for x in TARGET_ALIASES]

def is_excluded(alias: str) -> bool:
    a = normalize_alias(alias)
    return "ALUMBR" in a  # excluye ALUMBR/ALUMBRADO

# ------------------------------------------------------------
# CARGA DE DATOS, CÁLCULO Y PINTADO
# ------------------------------------------------------------
st.title("📊 BMS – Distribución de Potencias (T1–T5)")

with st.spinner("Cargando datos…"):
    try:
        df = supabase_select_last_hours(hours=24)
    except Exception as e:
        st.error(f"Error leyendo Supabase: {e}")
        time.sleep(AUTO_REFRESH_SECONDS)
        st.experimental_rerun()

if df.empty:
    st.info("No hay datos en las últimas 24 horas.")
    time.sleep(AUTO_REFRESH_SECONDS)
    st.experimental_rerun()

# Excluir alumbrado
df = df[~df["punto_alias"].fillna("").apply(is_excluded)]

# Último valor por alias
last_idx = df.groupby("punto_alias")["timestamp_utc"].idxmax()
df_last = df.loc[last_idx, ["punto_alias", "valor", "timestamp_utc"]].copy()
df_last["alias_norm"] = df_last["punto_alias"].apply(normalize_alias)

# Construcción estable de T1..T5 (si falta alguno, valor 0)
rows = []
for wanted_norm, wanted_original in zip(TARGET_ALIASES_NORM, TARGET_ALIASES):
    match = df_last[df_last["alias_norm"] == wanted_norm]
    val = float(match["valor"].iloc[0]) if not match.empty and pd.notna(match["valor"].iloc[0]) else 0.0
    rows.append({"alias": wanted_original, "valor": val})
df_pie = pd.DataFrame(rows)

# Total y timestamp
total_kw = df_pie["valor"].sum()
last_ts_utc = df["timestamp_utc"].max()
last_ts_local = last_ts_utc.astimezone(LOCAL_TZ) if pd.notna(last_ts_utc) else None

# Cabecera grande
st.markdown(f"<div class='big-total'>{total_kw:,.2f} kW</div>", unsafe_allow_html=True)
if last_ts_local:
    st.markdown(f"<div class='sub'>Última actualización: {last_ts_local.strftime('%Y-%m-%d %H:%M:%S %Z')}</div>", unsafe_allow_html=True)
st.markdown("---")

# Tarta POT T1..T5
if (df_pie["valor"] > 0).any():
    fig = px.pie(
        df_pie,
        names="alias",
        values="valor",
        hole=0.35,
        title=None
    )
    fig.update_traces(
        textposition="inside",
        textinfo="label+percent",
        hovertemplate="%{label}: %{value:.2f} kW<br>%{percent}"
    )
    fig.update_layout(
        showlegend=True,
        legend_title_text="Potencias",
        margin=dict(l=10, r=10, t=10, b=10)
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No hay valores distintos de 0 para POT T1..T5 en el último periodo.")

# Tabla informativa
st.markdown("#### Valores actuales (kW)")
st.dataframe(
    df_pie.sort_values("alias").assign(valor=lambda d: d["valor"].round(2)),
    use_container_width=True, height=240
)

st.caption("© BMS Dashboard • Streamlit + Supabase • Refresco automático cada 60 s")

# ------------------------------------------------------------
# AUTO-REFRESH CADA MINUTO (manteniendo la sesión)
# ------------------------------------------------------------
time.sleep(AUTO_REFRESH_SECONDS)
st.experimental_rerun()
