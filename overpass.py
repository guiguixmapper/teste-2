"""
overpass.py — v2
================
Détection des cols, sommets et points remarquables via l'API Overpass (OSM).

Améliorations v2 vs v1 :
    - Couverture élargie : col, selle, sommet, lieu-dit montagneux, refuge
    - Rayon de recherche augmenté (800m au lieu de 500m)
    - Priorité aux nœuds de type col/selle sur les pics et refuges
    - Filtre sur l'altitude OSM : on préfère le nœud dont l'altitude est
      la plus proche de l'altitude GPX du sommet (évite les faux positifs
      plaine/village homonyme)
    - BBox large + association locale Python (une seule requête pour tout le tracé)
    - Rotation sur 3 serveurs Overpass + retry
"""

import streamlit as st
import requests
import logging
import math
import time

logger = logging.getLogger(__name__)

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

RAYON_SOMMET_M  = 800
TIMEOUT_S       = 25
MAX_RETRIES     = 4
RETRY_DELAYS    = [2, 5, 10]  # secondes entre chaque tentative (croissant)

# Priorité des types de nœuds OSM (plus bas = meilleur)
TYPES_ACCEPTES = {
    "mountain_pass": 0,
    "saddle":        1,
    "peak":          2,
    "volcano":       3,
}


def _haversine(lat1, lon1, lat2, lon2) -> float:
    """Distance en mètres entre deux points GPS."""
    R  = 6371000
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a  = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_au_km(points_gpx, km_cible) -> tuple | None:
    """Retourne (lat, lon) du point GPX le plus proche d'une distance cible (km)."""
    if not points_gpx:
        return None
    dist_cum  = 0.0
    best_pt   = points_gpx[0]
    best_diff = abs(dist_cum / 1000 - km_cible)
    for i in range(1, len(points_gpx)):
        p1, p2 = points_gpx[i-1], points_gpx[i]
        dist_cum += p1.distance_2d(p2) or 0.0
        diff = abs(dist_cum / 1000 - km_cible)
        if diff < best_diff:
            best_diff = diff
            best_pt   = p2
    return best_pt.latitude, best_pt.longitude


def _type_noeud(tags: dict) -> str:
    """Détermine le type OSM d'un nœud selon ses tags."""
    if tags.get("mountain_pass") == "yes":
        return "mountain_pass"
    nat = tags.get("natural", "")
    if nat == "saddle":   return "saddle"
    if nat == "peak":     return "peak"
    if nat == "volcano":  return "volcano"
    return "other"


@st.cache_data(ttl=86400, show_spinner=False)
def _requete_osm_cached(min_lat: float, max_lat: float,
                        min_lon: float, max_lon: float) -> list:
    """
    Requête Overpass cachée 24h — retourne la liste brute des nœuds OSM
    dans la BBox donnée. Séparée de enrichir_cols pour être hashable.
    """
    query = f"""
[out:json][timeout:{TIMEOUT_S}][bbox:{min_lat:.5f},{min_lon:.5f},{max_lat:.5f},{max_lon:.5f}];
(
  node["mountain_pass"="yes"];
  node["natural"="saddle"]["name"];
  node["natural"="peak"]["name"];
  node["natural"="volcano"]["name"];
);
out body;
"""
    headers = {
        "User-Agent":   "VeloMeteoApp/7.0 (cycliste@example.com) Streamlit",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    for tentative in range(MAX_RETRIES):
        serveur = OVERPASS_URLS[tentative % len(OVERPASS_URLS)]
        try:
            r = requests.post(serveur, data={"data": query},
                              headers=headers, timeout=TIMEOUT_S)
            if r.status_code in [429, 503, 504]:
                raise Exception(f"Serveur surchargé ({r.status_code})")
            r.raise_for_status()

            nodes = []
            for el in r.json().get("elements", []):
                tags = el.get("tags", {})
                nom  = (tags.get("name:fr")
                        or tags.get("name")
                        or tags.get("name:en"))
                if not nom:
                    continue
                alt_tag = tags.get("ele")
                try:    alt = int(float(alt_tag)) if alt_tag else None
                except: alt = None
                nodes.append({
                    "nom":      nom,
                    "alt":      alt,
                    "lat":      el["lat"],
                    "lon":      el["lon"],
                    "type":     _type_noeud(tags),
                    "priorite": TYPES_ACCEPTES.get(_type_noeud(tags), 99),
                })
            return nodes

        except Exception as e:
            logger.warning(f"Overpass tentative {tentative+1} ({serveur}) : {e}")
            if tentative < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[min(tentative, len(RETRY_DELAYS) - 1)]
                time.sleep(delay)

    st.toast("⚠️ OSM instable — noms des cols potentiellement manquants.")
    return []


def enrichir_cols(ascensions: list, points_gpx: list) -> list:
    """
    Enrichit chaque ascension avec le nom OSM du col/sommet.

    La requête Overpass est mise en cache 24h via _requete_osm_cached —
    les interactions UI (selectbox, slider) ne déclenchent plus de nouvel appel réseau.

    Ajoute les clés "Nom" et "Nom OSM alt" à chaque ascension.
    """
    if not ascensions or not points_gpx:
        return ascensions

    # Coordonnées GPX des sommets
    coords_sommets = []
    for asc in ascensions:
        coords = _point_au_km(points_gpx, asc["_sommet_km"])
        if coords:
            alt_gpx = None
            try:
                alt_str = asc.get("Alt. sommet", "").replace(" m", "").strip()
                alt_gpx = int(alt_str) if alt_str else None
            except (ValueError, AttributeError):
                pass
            coords_sommets.append((asc, coords[0], coords[1], alt_gpx))
        else:
            asc["Nom"] = "—"; asc["Nom OSM alt"] = None

    if not coords_sommets:
        return ascensions

    # BBox englobant tout le parcours + marge
    lats = [p.latitude  for p in points_gpx]
    lons = [p.longitude for p in points_gpx]
    min_lat = min(lats) - 0.05; max_lat = max(lats) + 0.05
    min_lon = min(lons) - 0.05; max_lon = max(lons) + 0.05

    # Requête cachée — ne sera pas rejouée lors des interactions UI
    osm_nodes = _requete_osm_cached(
        round(min_lat, 5), round(max_lat, 5),
        round(min_lon, 5), round(max_lon, 5)
    )

    # Association locale pour chaque sommet
    for asc, lat, lon, alt_gpx in coords_sommets:
        candidats = []
        for nd in osm_nodes:
            dist = _haversine(lat, lon, nd["lat"], nd["lon"])
            if dist <= RAYON_SOMMET_M:
                # Pénalité altitude : si l'alt OSM est disponible et diffère
                # de plus de 200m de l'alt GPX, on écarte le candidat
                if alt_gpx and nd["alt"]:
                    if abs(nd["alt"] - alt_gpx) > 200:
                        continue
                candidats.append({**nd, "dist": dist})

        if not candidats:
            asc["Nom"] = "—"; asc["Nom OSM alt"] = None
            continue

        # Tri : priorité type d'abord, distance ensuite
        candidats.sort(key=lambda c: (c["priorite"], c["dist"]))
        meilleur = candidats[0]
        asc["Nom"]         = meilleur["nom"]
        asc["Nom OSM alt"] = meilleur["alt"]

    return ascensions
