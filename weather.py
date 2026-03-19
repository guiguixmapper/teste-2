# --- FICHIER : weather.py ---
import requests
from datetime import datetime, timedelta
import logging
import streamlit as st
import time

logger = logging.getLogger(__name__)

def recuperer_fuseau(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m&timezone=auto"
    try:
        return requests.get(url, timeout=10).json().get("timezone", "UTC")
    except: return "UTC"

def recuperer_soleil(lat, lon, date_str):
    url = f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&date={date_str}&formatted=0"
    try:
        data = requests.get(url, timeout=10).json().get("results", {})
        return {"lever": datetime.fromisoformat(data["sunrise"]), "coucher": datetime.fromisoformat(data["sunset"])}
    except: return None

@st.cache_data(ttl=3600, show_spinner=False)
def recuperer_qualite_air(lat, lon, date_str):
    url_aq = "https://air-quality-api.open-meteo.com/v1/air-quality"
    url_uv = "https://api.open-meteo.com/v1/forecast"
    res = {"uv_max": None, "pollen_alerte": "Aucune"}
    try:
        data_aq = requests.get(url_aq, params={"latitude": lat, "longitude": lon, "hourly": "grass_pollen,birch_pollen,olive_pollen", "start_date": date_str, "end_date": date_str, "timezone": "auto"}, timeout=10).json().get("hourly", {})
        pollens = [lbl for p_type, lbl in [("grass_pollen", "Graminées"), ("birch_pollen", "Bouleau"), ("olive_pollen", "Olivier")] if any(v > 50 for v in data_aq.get(p_type, []) if v)]
        if pollens: res["pollen_alerte"] = f"Élevé ({', '.join(pollens)})"
        data_uv = requests.get(url_uv, params={"latitude": lat, "longitude": lon, "daily": "uv_index_max", "start_date": date_str, "end_date": date_str, "timezone": "auto"}, timeout=10).json().get("daily", {})
        if data_uv.get("uv_index_max"): res["uv_max"] = round(data_uv["uv_index_max"][0], 1)
    except: pass
    return res

@st.cache_data(ttl=1800, show_spinner=False)
def recuperer_meteo_batch(checkpoints_figes, is_past=False, date_str=None):
    if not checkpoints_figes: return []
    lats = ",".join(str(cp[0]) for cp in checkpoints_figes)
    lons = ",".join(str(cp[1]) for cp in checkpoints_figes)
    url = "https://archive-api.open-meteo.com/v1/archive" if is_past else "https://api.open-meteo.com/v1/forecast"
    params = {"latitude": lats, "longitude": lons, "timezone": "auto"}
    if is_past:
        params.update({"start_date": date_str, "end_date": date_str, "hourly": "temperature_2m,precipitation,weathercode,wind_speed_10m,wind_direction_10m,wind_gusts_10m"})
    else:
        params.update({"hourly": "temperature_2m,precipitation_probability,weathercode,wind_speed_10m,wind_direction_10m,wind_gusts_10m"})
    for _ in range(3):
        try:
            req = requests.get(url, params=params, timeout=10)
            if req.status_code == 429: time.sleep(2); continue
            data = req.json()
            return data if isinstance(data, list) else [data]
        except: break
    return None

def extraire_meteo(data_json, heure_api):
    vide = {"Ciel": "—", "temp_val": None, "Pluie": "—", "pluie_pct": None, "vent_val": None, "rafales_val": None, "Dir": "—", "dir_deg": None, "effet": "—"}
    if not data_json or "hourly" not in data_json: return vide
    hourly, times = data_json["hourly"], data_json["hourly"].get("time", [])
    try: idx = times.index(heure_api)
    except ValueError: return vide
    t = hourly.get("temperature_2m", [])[idx]
    pp = hourly.get("precipitation_probability", hourly.get("precipitation", []))[idx]
    if "precipitation" in hourly and pp > 0: pp = 100
    w, wd, wg = hourly.get("wind_speed_10m", [])[idx], hourly.get("wind_direction_10m", [])[idx], hourly.get("wind_gusts_10m", [])[idx]
    CODES = {0: "☀️ Clair", 1: "🌤️ Peu nuageux", 2: "⛅ Mi-couvert", 3: "☁️ Couvert", 45: "🌫️ Brouillard", 51: "🌧️ Bruine", 61: "🌧️ Pluie", 71: "❄️ Neige", 80: "🌧️ Averses", 95: "⛈️ Orage"}
    DIR_WIND = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSO","SO","OSO","O","ONO","NO","NNO"]
    return {"Ciel": CODES.get(hourly.get("weathercode", [])[idx], "❓"), "temp_val": t, "Pluie": f"{pp}%", "pluie_pct": pp, "vent_val": w, "rafales_val": wg, "Dir": DIR_WIND[int((wd / 22.5) + 0.5) % 16] if wd is not None else "—", "dir_deg": wd}

def direction_vent_relative(cap_velo, dir_vent):
    if cap_velo is None or dir_vent is None: return "—"
    diff = (dir_vent - cap_velo) % 360
    if diff > 180: diff -= 360
    if -45 <= diff <= 45: return "⬇️ Face"
    elif 135 <= diff or diff <= -135: return "⬆️ Dos"
    elif 45 < diff < 135: return "↙️ Côté (D)"
    else: return "↘️ Côté (G)"
