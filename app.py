import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
st.set_page_config(page_title="BMS Dashboard", layout="wide")

# ------------------------------------------------------------
# LOGIN (simple con st.secrets)
# ------------------------------------------------------------
def require_login():
    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False
    if st.session_state.auth_ok:
        return True

    st.title("🔐 Acceso")
    u = st.text_input("Usuario", key="u")
    p = st.text_input("Contraseña", type="password", key="p")
    if st.button("Entrar"):
        if u == st.secrets["auth"]["user"] and p == st.secrets["auth"]["password"]:
            st.session_state.auth_ok = True
            st.experimental_rerun()
        else:
            st.error("Credenciales incorrectas.")
    st.stop()

# ------------------------------------------------------------
# SUPABASE REST
# ------------------------------------------------------------
def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def supabase_select_range(days: int = 1, punto_clave: str | None = None) -> pd.DataFrame:
    base_url = st.secrets["supabase"]["url"].rstrip("/")
    key      = st.secrets["supabase"]["key"]
    table    = st.secrets["supabase"]["table"]

    to_dt   = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(days=days)

    params = {
        "select": "timestamp_utc,punto_alias,punto_clave,valor",
        "timestamp_utc": f"gte.{iso_z(from_dt)}",
        "order": "timestamp_utc.asc",
    }
    query = urlencode(params)
    # 🔧 CORRECCIÓN CRÍTICA: usar & (no &amp;) en los parámetros extra
    query += f"&timestamp_utc=lte.{iso_z(to_dt)}"

    if punto_clave:
        query += f"&punto_clave=eq.{punto_clave}"

    url = f"{base_url}/rest/v1/{table}?{query}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        # Evitar respuestas cacheadas por alguna capa intermedia
        "Cache-Control": "no-cache"
    }

    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code >= 400:
        raise RuntimeError(f"Supabase SELECT HTTP {r.status_code}: {r.text}")

    df = pd.DataFrame(r.json())
    if df.empty:
        return df

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    # Convertir a numérico si aplica
    if "valor" in df.columns:
        df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    return df

# ------------------------------------------------------------
# APP
# ------------------------------------------------------------
require_login()

st.title("📊 BMS Dashboard")
st.caption("Lectura directa desde Supabase • HTTPS • Responsive")

with st.sidebar:
    st.header("Filtros")
    days = st.slider("Días a mostrar", 1, 60, 7, 1)
    punto_clave = st.text_input("punto_clave exacto (opcional)", value="")
    show_raw = st.checkbox("Mostrar tabla completa", value=False)

# Carga de datos
try:
    df = supabase_select_range(days=days, punto_clave=(punto_clave or None))
except Exception as e:
    st.error(f"Error leyendo Supabase: {e}")
    st.stop()

if df.empty:
    st.info("No hay datos para el rango/criterio seleccionado.")
    st.stop()

# Columnas principales
colL, colR = st.columns([2, 1], gap="large")

with colL:
    st.subheader("Serie temporal")
    puntos = sorted(df["punto_alias"].dropna().unique().tolist())
    sel = st.multiselect("Selecciona puntos", puntos, default=puntos[: min(5, len(puntos))])

    if sel:
        df_plot = df[df["punto_alias"].isin(sel)].dropna(subset=["timestamp_utc", "valor"])
        pivot = df_plot.pivot_table(index="timestamp_utc", columns="punto_alias", values="valor", aggfunc="mean").sort_index()
        st.line_chart(pivot)
    else:
        st.info("Selecciona al menos un punto.")

with colR:
    st.subheader("KPIs (último valor)")
    last_idx = df.groupby("punto_alias")["timestamp_utc"].idxmax()
    df_last = df.loc[last_idx, ["punto_alias", "valor", "timestamp_utc"]].sort_values("punto_alias")
    for _, row in df_last.iterrows():
        txt = f"{row['valor']:.2f}" if pd.notna(row["valor"]) else "—"
        st.metric(label=row["punto_alias"], value=txt)

    st.markdown("---")
    st.subheader("Tabla")
    if show_raw:
        st.dataframe(df.sort_values(["punto_alias", "timestamp_utc"], ascending=[True, False]), use_container_width=True, height=420)
    else:
        n = st.slider("Últimos N por punto", 10, 500, 100, 10)
        df_sorted = df.sort_values(["punto_alias", "timestamp_utc"], ascending=[True, False])
        df_tailn = df_sorted.groupby("punto_alias").head(n)
        st.dataframe(df_tailn, use_container_width=True, height=420)

st.caption("© BMS Dashboard • Streamlit + Supabase")
``
