import os
import re
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
AUTO_REFRESH_SECONDS = 60        # refresco cada minuto
LOOKBACK_HOURS = 48              # ampliamos a 48 horas para garantizar datos

# Ocultar menú/header/footer para modo monitor
st.markdown(
    """
    <style>
      #MainMenu {visibility: hidden;}
      header {visibility: hidden;}
      footer {visibility: hidden;}
      .big-total {font-size: 64px; font-weight: 800; line-height: 1.0; margin: 0.2rem 0 1rem 0;}
      .sub {font-size: 14px; color: #888;}
      .diag-box {background: #0f172a0f; padding: 0.75rem 1rem; border-radius: 8px; border: 1px solid #e2e8f0;}
      .small {font-size: 12px; color: #666;}
    </style>
    """,
    unsafe_allow_html=True
)

# Mantener estado de login entre refrescos de la página
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
# SUPABASE REST
# ------------------------------------------------------------
def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

@st.cache_data(ttl=50, show_spinner=False)
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
        "order": "timestamp_utc.asc",
    }
    query = urlencode(params) + f"&timestamp_utc=lte.{iso_z(to_dt)}"
    url = f"{base_url}/rest/v1/{table}?{query}"

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    r = requests.get(url, headers=headers, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"Supabase SELECT HTTP {r.status_code}: {r.text}")

    df = pd.DataFrame(r.json())
    if df.empty:
        return df

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    if "valor" in df.columns:
        df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    # Sanitizar alias
    df["punto_alias"] = df["punto_alias"].astype(str).str.strip()
    return df

# ------------------------------------------------------------
# LÓGICA DE POTENCIAS (POT T1..T5) + EXCLUSIÓN DE ALUMBRADO
# ------------------------------------------------------------
def normalize_alias(s: str | None) -> str:
    if not s:
        return ""
    s = " ".join(str(s).split())
    return s.upper()

# Patrones flexibles para mapear POT T1..T5 aunque vengan con guión, subrayado, sin espacio, etc.
# Acepta variantes: "POT T1", "POTT1", "POT-T1", "POT_T1", "Pot t1", etc.
PATTERNS = {
    "POT T1": re.compile(r"\bPOT[ _\-]*T\s*1\b|\bPOT\s*1\b|\bPOTT1\b", re.IGNORECASE),
    "POT T2": re.compile(r"\bPOT[ _\-]*T\s*2\b|\bPOT\s*2\b|\bPOTT2\b", re.IGNORECASE),
    "POT T3": re.compile(r"\bPOT[ _\-]*T\s*3\b|\bPOT\s*3\b|\bPOTT3\b", re.IGNORECASE),
    "POT T4": re.compile(r"\bPOT[ _\-]*T\s*4\b|\bPOT\s*4\b|\bPOTT4\b", re.IGNORECASE),
    "POT T5": re.compile(r"\bPOT[ _\-]*T\s*5\b|\bPOT\s*5\b|\bPOTT5\b", re.IGNORECASE),
}

def is_alumbrado(alias: str) -> bool:
    a = normalize_alias(alias)
    return "ALUMBR" in a  # ALUMBR, ALUMBRADO, etc.

def classify_alias(alias: str) -> str | None:
    """Devuelve 'POT T1'..'POT T5' si el alias coincide con alguna regex; None si no mapea."""
    if not alias:
        return None
    for label, rgx in PATTERNS.items():
        if rgx.search(alias):
            return label
    return None

# ------------------------------------------------------------
# CARGA DE DATOS, CÁLCULO Y PINTADO
# ------------------------------------------------------------
st.title("📊 FCC – DASHBOARD TEATRO REAL")

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

# Excluir solo alumbrado (sin pasarnos)
df = df[~df["punto_alias"].fillna("").apply(is_alumbrado)]

# Tomar el último valor por alias original
last_idx = df.groupby("punto_alias")["timestamp_utc"].idxmax()
df_last = df.loc[last_idx, ["punto_alias", "valor", "timestamp_utc"]].copy()

# Clasificar cada alias en uno de POT T1..T5 (si cuadra)
df_last["grupo"] = df_last["punto_alias"].apply(classify_alias)

# Nos quedamos solo con los mapeados a POT T1..T5
df_mapped = df_last.dropna(subset=["grupo"]).copy()

# Construcción estable: si falta alguno, valor 0
rows = []
for label in ["POT T1", "POT T2", "POT T3", "POT T4", "POT T5"]:
    match = df_mapped[df_mapped["grupo"] == label]
    if not match.empty:
        val = float(match["valor"].iloc[0]) if pd.notna(match["valor"].iloc[0]) else 0.0
    else:
        val = 0.0
    rows.append({"alias": label, "valor": val})

df_pie = pd.DataFrame(rows)

# Total y timestamp
total_kw = df_pie["valor"].sum()
last_ts_utc = df["timestamp_utc"].max()
last_ts_local = last_ts_utc.astimezone(LOCAL_TZ) if pd.notna(last_ts_utc) else None

# ------------------------------------------------------------
# CABECERA: TOTAL + ÚLTIMA ACTUALIZACIÓN
# ------------------------------------------------------------
st.markdown(f"<div class='big-total'>{total_kw:,.2f} kW</div>", unsafe_allow_html=True)
if last_ts_local:
    st.markdown(f"<div class='sub'>Última actualización: {last_ts_local.strftime('%Y-%m-%d %H:%M:%S %Z')}</div>", unsafe_allow_html=True)
st.markdown("---")

# ------------------------------------------------------------
# GRÁFICO DE TARTA
# ------------------------------------------------------------
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

# ------------------------------------------------------------
# TABLA RESUMEN
# ------------------------------------------------------------
st.markdown("#### Valores actuales (kW)")
st.dataframe(
    df_pie.sort_values("alias").assign(valor=lambda d: d["valor"].round(2)),
    use_container_width=True, height=240
)

# ------------------------------------------------------------
# DIAGNÓSTICO (plegable, no afecta a nada)
# ------------------------------------------------------------
with st.expander("Diagnóstico (ayuda a encontrar las potencias si no aparecen)"):
    st.markdown("<div class='diag-box'>", unsafe_allow_html=True)
    st.write("**Total filas recibidas en ventana:**", len(df))
    st.write("**Aliases únicos (muestra hasta 30):**", sorted(df['punto_alias'].dropna().unique().tolist()[:30]))
    st.write("**Últimos por alias (muestra 10):**")
    st.dataframe(df_last.sort_values("timestamp_utc", ascending=False).head(10), use_container_width=True)
    st.write("**Mapeo encontrado a POT T1..T5:**")
    st.dataframe(df_mapped[["punto_alias", "grupo", "valor", "timestamp_utc"]].sort_values("grupo"), use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

st.caption(f"© FCC Dashboard • FCC Industrial • Refresco automático cada {AUTO_REFRESH_SECONDS} s • Ventana {LOOKBACK_HOURS} h")

# ------------------------------------------------------------
# AUTO-REFRESH
# ------------------------------------------------------------
time.sleep(AUTO_REFRESH_SECONDS)
st.experimental_rerun()
