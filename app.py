import time
import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
st.set_page_config(page_title="BMS Dashboard", layout="wide")
TZ = ZoneInfo("Europe/Madrid")

# Mantener login entre refrescos
st.session_state.setdefault("auth_ok", False)

# ------------------------------------------------------------
# LOGIN
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
            st.error("Error: secrets.toml no encontrado o incompleto.")
    st.stop()

# ------------------------------------------------------------
# SUPABASE (consulta: últimos primero → reordenar asc)
# ------------------------------------------------------------
def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def supabase_select_range(days: int = 1, punto_clave: str | None = None) -> pd.DataFrame:
    base_url = st.secrets["supabase"]["url"].rstrip("/")
    key      = st.secrets["supabase"]["key"]
    table    = st.secrets["supabase"]["table"]

    to_dt   = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(days=days)

    # Pedimos lo ÚLTIMO primero (desc) para evitar cortes por límite
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
        "Range": "0-28799"   # ← Hasta 28.800 (asegúrate de subir "Max rows" en Supabase)
    }

    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()

    df = pd.DataFrame(r.json())
    if df.empty:
        return df

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["punto_alias"] = df["punto_alias"].astype(str).str.strip()

    # Reordenamos a ascendente para pintar cronológicamente
    df = df.sort_values("timestamp_utc", ascending=True, kind="mergesort").reset_index(drop=True)
    return df

# ------------------------------------------------------------
# TIEMPO EN MADRID (solo wttr.in, °C/km/h)
# ------------------------------------------------------------
def obtener_tiempo_madrid():
    try:
        r = requests.get("https://wttr.in/Madrid?format=j1", timeout=6)
        j = r.json()
        estado = j["current_condition"][0]["weatherDesc"][0]["value"]
        temp_c = float(j["current_condition"][0]["temp_C"])
        feels_c = float(j["current_condition"][0]["FeelsLikeC"])
        humedad = int(j["current_condition"][0]["humidity"])
        viento_kmh = int(j["current_condition"][0]["windspeedKmph"])
        return estado, temp_c, feels_c, humedad, viento_kmh
    except:
        return None, None, None, None, None

# ------------------------------------------------------------
# APP
# ------------------------------------------------------------
require_login()

# CABECERA
st.title("📊 BMS Dashboard")
st.caption("Actualización automática cada minuto — Hora local Madrid")

# ======= Fila superior: a la derecha Fecha/Hora + Tiempo =======
col_left, col_spacer, col_right = st.columns([1, 2, 1], gap="large")

with col_right:
    # Hora local sin segundos
    hora_local = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    st.markdown(f"**{hora_local}**", help="Hora Madrid (sin segundos)")

    # Tiempo actual
    estado, temp_c, feels_c, humedad, viento_kmh = obtener_tiempo_madrid()
    if estado:
        st.markdown(
            f"{estado} · **{temp_c}°C** (sensación {feels_c}°C)  \n"
            f"Humedad {humedad}% · Viento {viento_kmh} km/h"
        )
    else:
        st.markdown("_Tiempo no disponible en este momento_")

# ======= Sidebar (igual que tenías) =======
with st.sidebar:
    st.header("Filtros")
    days = st.slider("Días a mostrar", 1, 60, 7, 1)
    punto_clave = st.text_input("punto_clave exacto (opcional)", value="")
    show_raw = st.checkbox("Mostrar tabla completa", value=False)

# ======= Datos =======
try:
    df = supabase_select_range(days=days, punto_clave=(punto_clave or None))
except Exception as e:
    st.error(f"Error leyendo Supabase: {e}")
    st.stop()

if df.empty:
    st.info("No hay datos en este rango.")
    time.sleep(60)
    st.experimental_rerun()

# Hora local
df["hora_local"] = df["timestamp_utc"].dt.tz_convert(TZ)

# ======= Cuerpo principal (tu layout original) =======
colL, colR = st.columns([2, 1], gap="large")

with colL:
    st.subheader("Serie temporal")
    puntos = sorted(df["punto_alias"].dropna().unique().tolist())
    sel = st.multiselect("Selecciona puntos", puntos, default=puntos[: min(5, len(puntos))])
    if sel:
        df_plot = df[df["punto_alias"].isin(sel)].dropna(subset=["hora_local", "valor"])
        pivot = df_plot.pivot_table(
            index="hora_local", columns="punto_alias", values="valor", aggfunc="mean"
        ).sort_index()
        st.line_chart(pivot)
    else:
        st.info("Selecciona al menos un punto.")

with colR:
    st.subheader("KPIs (último valor)")
    last_idx = df.groupby("punto_alias")["timestamp_utc"].idxmax()
    df_last = df.loc[last_idx, ["punto_alias", "valor", "hora_local"]].sort_values("punto_alias")

    for _, row in df_last.iterrows():
        txt = f"{row['valor']:.2f}" if pd.notna(row["valor"]) else "—"
        hora_txt = row["hora_local"].strftime("%Y-%m-%d %H:%M")
        st.metric(label=row["punto_alias"], value=txt, help=f"{hora_txt} (Madrid)")

    st.markdown("---")
    st.subheader("Tabla")
    if show_raw:
        st.dataframe(
            df.sort_values(["punto_alias", "timestamp_utc"], ascending=[True, False]),
            use_container_width=True, height=420
        )
    else:
        n = st.slider("Últimos N por punto", 10, 500, 100, 10)
        df_sorted = df.sort_values(["punto_alias", "timestamp_utc"], ascending=[True, False])
        df_tailn = df_sorted.groupby("punto_alias").head(n)
        st.dataframe(df_tailn, use_container_width=True, height=420)

st.caption("© BMS Dashboard — Auto‑refresh 60 s")

# ======= Auto‑refresh =======
time.sleep(60)
st.experimental_rerun()
