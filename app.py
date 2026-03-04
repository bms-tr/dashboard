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

# Mantener login entre refrescos
st.session_state.setdefault("auth_ok", False)

# Zona horaria Madrid
TZ = ZoneInfo("Europe/Madrid")

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
            st.error("Error: no se encontraron secretos.")

    st.stop()


# ------------------------------------------------------------
# SUPABASE REST (CONSULTA FINAL CORRECTA + RANGE)
# ------------------------------------------------------------
def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def supabase_select_range(days: int = 1, punto_clave: str | None = None) -> pd.DataFrame:
    base_url = st.secrets["supabase"]["url"].rstrip("/")
    key = st.secrets["supabase"]["key"]
    table = st.secrets["supabase"]["table"]

    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(days=days)

    # Construcción explícita (sin duplicar timestamp_utc)
    query_parts = [
        "select=timestamp_utc,punto_alias,punto_clave,valor",
        "order=timestamp_utc.asc",
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
        # ← Lectura hasta 28.800 registros
        "Range": "0-28799"
    }

    r = requests.get(url, headers=headers, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"ERROR SUPABASE {r.status_code}: {r.text}")

    df = pd.DataFrame(r.json())
    if df.empty:
        return df

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["punto_alias"] = df["punto_alias"].astype(str).str.strip()

    return df


# ------------------------------------------------------------
# TIEMPO EN MADRID (DATOS REALES DE MSN WEATHER)
# ------------------------------------------------------------
def obtener_tiempo_madrid():
    # Fuente: MSN Weather (datos actuales en tiempo real)
    url = "https://a.msn.com/54/EN-US/ct40.4167,-3.7003?pageocid=ansmsnweather"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()["Weather"][0]["responses"][0]["weather"][0]["current"]

        estado = data["cap"]            # Ej. "Mayormente soleado" [1](https://community.weweb.io/t/how-do-i-create-a-supabase-collection-with-a-limit-and-pagination/10113)
        temp_f = data["temp"]           # °F
        feels_f = data["feels"]         # °F
        humedad = data["rh"]            # %
        viento_mph = data["windSpd"]    # mph

        # Convertir a grados centígrados
        temp_c = round((temp_f - 32) * 5/9, 1)
        feels_c = round((feels_f - 32) * 5/9, 1)
        viento_kmh = round(viento_mph * 1.60934)

        return estado, temp_c, feels_c, humedad, viento_kmh

    except Exception:
        return None, None, None, None, None


# ------------------------------------------------------------
# APP
# ------------------------------------------------------------
require_login()

st.title("📊 BMS Dashboard (Lectura Supabase)")
st.caption("Actualización automática cada minuto — Hora local Madrid")


# ------------------------------------------------------------
# MOSTRAR FECHA/HORA ARRIBA DERECHA
# ------------------------------------------------------------
ahora_local = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
st.markdown(
    f"""
    <div style="
        position:absolute;
        top:10px; right:20px;
        font-size:18px; font-weight:700; color:#222;">
        {ahora_local}
    </div>
    """,
    unsafe_allow_html=True
)


# ------------------------------------------------------------
# MOSTRAR TIEMPO DEBAJO DE LA HORA
# ------------------------------------------------------------
estado, temp_c, feels_c, humedad, viento_kmh = obtener_tiempo_madrid()

if estado:
    st.markdown(
        f"""
        <div style="
            position:absolute;
            top:45px; right:20px;
            font-size:15px; font-weight:600; color:#333;
            background:rgba(255,255,255,0.60);
            padding:6px 12px;
            border-radius:6px;">
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
    st.stop()

# Añadir columna hora local
df["hora_local"] = df["timestamp_utc"].dt.tz_convert(TZ)


# ------------------------------------------------------------
# COLUMNAS PRINCIPALES (TU DASHBOARD ORIGINAL)
# ------------------------------------------------------------
colL, colR = st.columns([2, 1], gap="large")

with colL:
    st.subheader("Serie temporal")
    puntos = sorted(df["punto_alias"].dropna().unique().tolist())
    sel = st.multiselect(
        "Selecciona puntos", 
        puntos, 
        default=puntos[: min(5, len(puntos))]
    )

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
        hora_txt = row["hora_local"].strftime("%Y-%m-%d %H:%M:%S")
        st.metric(label=row["punto_alias"], value=txt, help=f"{hora_txt} (Madrid)")

    st.markdown("---")
    st.subheader("Tabla")

    if show_raw:
        st.dataframe(
            df.sort_values(["punto_alias", "timestamp_utc"], ascending=[True, False]),
            use_container_width=True,
            height=420
        )
    else:
        n = st.slider("Últimos N por punto", 10, 500, 100, 10)
        df_sorted = df.sort_values(["punto_alias", "timestamp_utc"], ascending=[True, False])
        df_tailn = df_sorted.groupby("punto_alias").head(n)
        st.dataframe(df_tailn, use_container_width=True, height=420)


st.caption("© BMS Dashboard — Supabase — Auto‑refresh cada 60 s")


# ------------------------------------------------------------
# AUTO REFRESH (mantiene sesión)
# ------------------------------------------------------------
time.sleep(60)
st.experimental_rerun()
