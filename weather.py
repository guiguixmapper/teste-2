"""
weather.py
==========
Module météo pour l'app Vélo & Météo.

Fonctions publiques :
    - recuperer_fuseau(lat, lon)                → fuseau horaire (str)
    - recuperer_meteo_batch(checkpoints_frozen) → données météo brutes
    - recuperer_soleil(lat, lon, date_str)      → {"lever": datetime, "coucher": datetime}
    - extraire_meteo(api, heure)                → dict météo pour un checkpoint
    - direction_vent_relative(cap, dir_vent)    → str effet vent ressenti
    - wind_chill(temp_c, vent_kmh)              → ressenti thermique (int | None)
    - label_wind_chill(ressenti)                → str coloré du ressenti
    - obtenir_icone_meteo(code)                 → emoji + libellé météo
"""

import streamlit as st
import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ==============================================================================
# UTILITAIRES MÉTÉO
# ==============================================================================

def obtenir_icone_meteo(code: int) -> str:
    """Convertit un code météo WMO en emoji + libellé."""
    mapping = {
        0:  "☀️ Clair",
        1:  "⛅ Éclaircies", 2: "⛅ Éclaircies",
        3:  "☁️ Couvert",
        45: "🌫️ Brouillard", 48: "🌫️ Brouillard",
        51: "🌦️ Bruine", 53: "🌦️ Bruine", 55: "🌦️ Bruine",
        61: "🌧️ Pluie",  63: "🌧️ Pluie",  65: "🌧️ Pluie",
        66: "🌧️ Pluie",  67: "🌧️ Pluie",
        80: "🌧️ Pluie",  81: "🌧️ Pluie",  82: "🌧️ Pluie",
        71: "❄️ Neige",  73: "❄️ Neige",  75: "❄️ Neige",
        77: "❄️ Neige",  85: "❄️ Neige",  86: "❄️ Neige",
        95: "⛈️ Orage",  96: "⛈️ Orage",  99: "⛈️ Orage",
    }
    return mapping.get(code, "❓ Inconnu")


def direction_vent_relative(cap: float, dir_vent: float) -> str:
    """Retourne l'effet ressenti du vent selon le cap du cycliste."""
    diff = (dir_vent - cap) % 360
    if diff <= 45 or diff >= 315:  return "⬇️ Face"
    elif 135 <= diff <= 225:       return "⬆️ Dos"
    elif 45 < diff < 135:          return "↙️ Côté (D)"   # vent de droite → pousse à gauche
    else:                          return "↘️ Côté (G)"   # vent de gauche → pousse à droite


def wind_chill(temp_c: float, vent_kmh: float) -> int | None:
    """
    Indice de refroidissement éolien (formule NOAA).
    Applicable uniquement si temp <= 10°C et vent > 4.8 km/h.
    """
    if temp_c > 10 or vent_kmh <= 4.8:
        return None
    return round(
        13.12 + 0.6215 * temp_c
        - 11.37 * (vent_kmh ** 0.16)
        + 0.3965 * temp_c * (vent_kmh ** 0.16)
    )


def label_wind_chill(ressenti: int | None) -> str:
    """Retourne un label coloré selon l'indice de ressenti."""
    if ressenti is None:  return "—"
    if ressenti <= -40:   return f"🟣 {ressenti}°C (Danger extrême)"
    if ressenti <= -27:   return f"🔴 {ressenti}°C (Très dangereux)"
    if ressenti <= -10:   return f"🟠 {ressenti}°C (Dangereux)"
    if ressenti <= 0:     return f"🟡 {ressenti}°C (Froid intense)"
    return                       f"🔵 {ressenti}°C (Frais)"


# ==============================================================================
# APPELS API (avec cache Streamlit)
# ==============================================================================

@st.cache_data(show_spinner=False)
def recuperer_fuseau(lat: float, lon: float) -> str:
    """Récupère le fuseau horaire d'un point GPS via Open-Meteo."""
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current=temperature_2m&timezone=auto"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json().get("timezone", "UTC")
    except Exception as e:
        logger.warning(f"Fuseau horaire indisponible : {e}")
        return "UTC"


@st.cache_data(ttl=3600, show_spinner=False)
def recuperer_meteo_batch(checkpoints_frozen: tuple, is_past: bool = False, date_str: str = None) -> list | None:
    """
    Récupère la météo pour tous les checkpoints en un seul appel API.
    Mise en cache 1 heure. Retry avec backoff exponentiel sur 429.

    Args:
        checkpoints_frozen: tuple de (lat, lon, heure_api) — hashable pour le cache.
        is_past:   True pour utiliser l'API archive (dates passées).
        date_str:  Date au format 'YYYY-MM-DD' (requis si is_past=True).

    Returns:
        Liste de dicts météo par checkpoint, ou None en cas d'erreur.
    """
    import time as _time

    if not checkpoints_frozen:
        return []
    lats = ",".join(str(c[0]) for c in checkpoints_frozen)
    lons = ",".join(str(c[1]) for c in checkpoints_frozen)

    if is_past and date_str:
        url = (
            "https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={lats}&longitude={lons}"
            f"&start_date={date_str}&end_date={date_str}"
            "&hourly=temperature_2m,precipitation,weathercode,"
            "wind_speed_10m,wind_direction_10m,wind_gusts_10m&timezone=auto"
        )
    else:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lats}&longitude={lons}"
            "&hourly=temperature_2m,precipitation_probability,weathercode,"
            "wind_speed_10m,wind_direction_10m,wind_gusts_10m&timezone=auto"
        )

    # Retry avec backoff exponentiel : 2s, 5s, 12s
    delays = [2, 5, 12]
    for attempt, delay in enumerate(delays + [None]):
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 429:
                if delay is not None:
                    logger.warning(f"Météo 429 — tentative {attempt+1}, attente {delay}s")
                    _time.sleep(delay)
                    continue
                else:
                    logger.error("Météo 429 — toutes les tentatives épuisées")
                    return None
            r.raise_for_status()
            d = r.json()
            return d if isinstance(d, list) else [d]
        except Exception as e:
            if delay is not None:
                logger.warning(f"Météo erreur tentative {attempt+1} : {e} — retry dans {delay}s")
                _time.sleep(delay)
            else:
                logger.error(f"Erreur météo batch : {e}")
                return None
    return None


@st.cache_data(show_spinner=False)
def recuperer_soleil(lat: float, lon: float, date_str: str) -> dict | None:
    """
    Récupère les heures de lever et coucher du soleil via sunrise-sunset.org.

    Args:
        date_str: format 'YYYY-MM-DD'

    Returns:
        {"lever": datetime, "coucher": datetime} en UTC, ou None en cas d'erreur.
    """
    try:
        url = (
            f"https://api.sunrise-sunset.org/json"
            f"?lat={lat}&lng={lon}&date={date_str}&formatted=0"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "OK":
            return None
        return {
            "lever":   datetime.fromisoformat(data["results"]["sunrise"]),
            "coucher": datetime.fromisoformat(data["results"]["sunset"]),
        }
    except Exception as e:
        logger.warning(f"Soleil indisponible : {e}")
        return None


# ==============================================================================
# EXTRACTION ET TRAITEMENT DES DONNÉES
# ==============================================================================

def extraire_meteo(donnees_api: dict, heure_api: str) -> dict:
    """
    Extrait les données météo pour une heure donnée depuis la réponse API.

    Args:
        donnees_api: dict retourné par Open-Meteo pour un checkpoint.
        heure_api:   heure au format 'YYYY-MM-DDTHH:00'.

    Returns:
        Dict avec les clés : Ciel, temp_val, Pluie, pluie_pct,
        vent_val, rafales_val, Dir, dir_deg, effet, ressenti.
    """
    vide = dict(
        Ciel="—", temp_val=None, Pluie="—", pluie_pct=None,
        vent_val=None, rafales_val=None, Dir="—",
        dir_deg=None, effet="—", ressenti=None,
    )
    if not donnees_api or "hourly" not in donnees_api:
        return vide

    heures = donnees_api["hourly"].get("time", [])
    if heure_api not in heures:
        return vide

    idx = heures.index(heure_api)
    h   = donnees_api["hourly"]

    def sg(key, default=None):
        vals = h.get(key, [])
        return vals[idx] if idx < len(vals) else default

    dir_deg  = sg("wind_direction_10m")
    dirs     = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
    dir_label = dirs[round(dir_deg / 45) % 8] if dir_deg is not None else "—"

    temp = sg("temperature_2m")
    vent = sg("wind_speed_10m")

    try:
        # API prévisions → precipitation_probability (0-100%)
        # API archive   → precipitation (mm) — on considère >0.5mm comme 100%
        if "precipitation_probability" in h:
            pluie_pct = int(sg("precipitation_probability"))
        elif "precipitation" in h:
            val = sg("precipitation", 0) or 0
            pluie_pct = 100 if val > 0.5 else (50 if val > 0 else 0)
        else:
            pluie_pct = None
    except:
        pluie_pct = None

    return {
        "Ciel":        obtenir_icone_meteo(sg("weathercode", 0)),
        "temp_val":    temp,
        "Pluie":       f"{pluie_pct}%" if pluie_pct is not None else "—",
        "pluie_pct":   pluie_pct,
        "vent_val":    vent,
        "rafales_val": sg("wind_gusts_10m"),
        "Dir":         dir_label,
        "dir_deg":     dir_deg,
        "effet":       "—",
        "ressenti":    wind_chill(temp, vent) if (temp is not None and vent is not None) else None,
    }

# ==============================================================================
# UV & POLLEN
# ==============================================================================

def label_uv(uv: float) -> tuple:
    """Retourne (emoji, label, couleur) selon l'indice UV."""
    if uv is None:    return "—",  "Inconnu",       "#9ca3af"
    if uv < 3:        return "🟢", f"UV {uv} — Faible",      "#22c55e"
    if uv < 6:        return "🟡", f"UV {uv} — Modéré",      "#eab308"
    if uv < 8:        return "🟠", f"UV {uv} — Élevé",       "#f97316"
    if uv < 11:       return "🔴", f"UV {uv} — Très élevé",  "#ef4444"
    return                  "🟣", f"UV {uv} — Extrême",      "#8b5cf6"


def label_pollen(val: float | None, nom: str) -> str | None:
    """Retourne un label d'alerte pollen ou None si négligeable."""
    if val is None or val < 10:  return None
    if val < 50:   niv = "Modéré"
    elif val < 200: niv = "Élevé"
    else:           niv = "Très élevé"
    return f"{nom} — {niv} ({int(val)} grains/m³)"


@st.cache_data(ttl=3600, show_spinner=False)
def recuperer_uv_pollen(lat: float, lon: float, date_str: str) -> dict:
    """
    Récupère l'indice UV max et les alertes pollen pour la journée.

    Sources :
        - UV max      : Open-Meteo forecast (daily uv_index_max)
        - Pollen      : Open-Meteo air-quality (hourly, max de la journée)

    Returns:
        {
          "uv_max":      float | None,
          "uv_emoji":    str,
          "uv_label":    str,
          "uv_couleur":  str,
          "pollens":     [str, ...]   # liste de labels d'alerte, vide si RAS
        }
    """
    res = {
        "uv_max":     None,
        "uv_emoji":   "—",
        "uv_label":   "Données indisponibles",
        "uv_couleur": "#9ca3af",
        "pollens":    [],
    }

    # ── UV ──────────────────────────────────────────────────────────────────
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude":  lat, "longitude": lon,
                "daily":     "uv_index_max",
                "start_date": date_str, "end_date": date_str,
                "timezone":  "auto",
            }, timeout=10)
        r.raise_for_status()
        vals = r.json().get("daily", {}).get("uv_index_max", [])
        if vals and vals[0] is not None:
            uv = round(vals[0], 1)
            res["uv_max"]    = uv
            emoji, label, coul = label_uv(uv)
            res["uv_emoji"]   = emoji
            res["uv_label"]   = label
            res["uv_couleur"] = coul
    except Exception as e:
        logger.warning(f"UV indisponible : {e}")

    # ── Pollen ──────────────────────────────────────────────────────────────
    try:
        r = requests.get(
            "https://air-quality-api.open-meteo.com/v1/air-quality",
            params={
                "latitude":  lat, "longitude": lon,
                "hourly":    "grass_pollen,birch_pollen,olive_pollen,alder_pollen,mugwort_pollen,ragweed_pollen",
                "start_date": date_str, "end_date": date_str,
                "timezone":  "auto",
            }, timeout=10)
        r.raise_for_status()
        hourly = r.json().get("hourly", {})

        ESPECES = [
            ("grass_pollen",    "🌾 Graminées"),
            ("birch_pollen",    "🌳 Bouleau"),
            ("olive_pollen",    "🫒 Olivier"),
            ("alder_pollen",    "🌲 Aulne"),
            ("mugwort_pollen",  "🌿 Armoise"),
            ("ragweed_pollen",  "🌻 Ambroisie"),
        ]
        for clé, nom in ESPECES:
            vals = [v for v in hourly.get(clé, []) if v is not None]
            if vals:
                lbl = label_pollen(max(vals), nom)
                if lbl:
                    res["pollens"].append(lbl)
    except Exception as e:
        logger.warning(f"Pollen indisponible : {e}")

    return res
