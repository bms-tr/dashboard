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
# SUPABASE (consulta: últimos primero → reordenar)
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
        # ← Hasta 28.800 registros (asegúrate de subir "Max rows" en Supabase)
        "Range": "0-28799"
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
# TIEMPO EN MADRID (MSN + fallback wttr.in, todo en °C/km/h)
# ------------------------------------------------------------
def obtener_tiempo_madrid():
    # MSN Weather (primario)
    msn = "https://a.msn.com/54/EN-US/ct40.4167,-3.7003?pageocid=ansmsnweather"
    try:
        r = requests.get(msn, timeout=5)
        data = r.json()["Weather"][0]["responses"][0]["weather"][0]["current"]
        estado = data["cap"]              # p.ej. "Mayormente soleado"
        temp_f = data["temp"]
        feels_f = data["feels"]
        humedad = data["rh"]
        viento_mph = data["windSpd"]

        # Convertir a °C y km/h
        temp_c   = round((temp_f  - 32) * 5/9, 1)
        feels_c  = round((feels_f - 32) * 5/9, 1)
        viento_kmh = round(viento_mph * 1.60934)
        return estado, temp_c, feels_c, humedad, viento_kmh
    except:
        # Fallback: wttr.in (sin claves)
        try:
            r = requests.get("https://wttr.in/Madrid?format=j1", timeout=5)
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

st.title("📊 BMS Dashboard")
st.caption("Actualización automática cada minuto — Hora local Madrid")

# ------------------------------------------------------------
# RELOJ ARRIBA DERECHA (sin segundos + fijado)
# ------------------------------------------------------------
hora_local = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
st.markdown(
    f"""
    <style>
    .capa-fecha {{
        position: fixed;
        top: 10px;
        right: 20px;
        z-index: 9999;
        font-size: 20px;
        font-weight: 700;
        color: #222;
    }}
    .capa-tiempo {{
        position: fixed;
        top: 40px;
        right: 20px;
        z-index: 9999;
        font-size: 14px;
        color: #333;
        background: rgba(255,255,255,0.7);
        padding: 6px 12px;
        border-radius: 6px;
    }}
    </style>
    <div class="capa-fecha">{hora_local}</div>
    """,
    unsafe_allow_html=True
)

# ------------------------------------------------------------
# TIEMPO (debajo del reloj)
# ------------------------------------------------------------
estado, temp_c, feels_c, humedad, viento_kmh = obtener_tiempo_madrid()
if estado:
    st.markdown(
        f"""
        <div class="capa-tiempo">
            {estado} · {temp_c}°C (sensación {feels_c}°C)<br>
            Humedad {humedad}% · Viento {viento_kmh} km/h
        </div>
        """,
        unsafe_allow_html=True
    )

# ------------------------------------------------------------
# SIDEBAR ORIGINAL
# ------------------------------------------------------------
with st.sidebar:
    st.header("Filtros")
    days = st.slider("Días a mostrar", 1, 60, 7, 1)
    punto_clave = st.text_input("punto_clave exacto (opcional)", value="")
    show_raw = st.checkbox("Mostrar tabla completa", value=False)

# ------------------------------------------------------------
# CARGA DE DATOS
# ------------------------------------------------------------
try:
    df = supabase_select_range(days=days, punto_clave=(punto_clave or None))
except Exception as e:
    st.error(f"Error leyendo Supabase: {e}")
    st.stop()

if df.empty:
    st.info("No hay datos en este rango.")
    time.sleep(60)
    st.experimental_rerun()

# Añadir columna hora local (Madrid)
df["hora_local"] = df["timestamp_utc"].dt.tz_convert(TZ)

# ------------------------------------------------------------
# LAYOUT ORIGINAL
# ------------------------------------------------------------
colL, colR = st.columns([2, 1], gap="large")

with colL:
    st.subheader("Serie temporal")
    puntos = sorted(df["punto_alias"].dropna().unique().tolist())
    sel = st.multiselect("Selecciona puntos", puntos, default=puntos[: min(5, len(puntos))])

    if sel:
        df_plot = df[df["punto_alias"].isin(sel)].dropna(subset=["hora_local", "valor"])
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

# ------------------------------------------------------------
# AUTO REFRESH
# ------------------------------------------------------------
time.sleep(60)
st.experimental_rerun()
