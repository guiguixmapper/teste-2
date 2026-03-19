# --- FICHIER : overpass.py ---
import requests
import logging
import streamlit as st
import math
import time
import copy

logger = logging.getLogger(__name__)

def distance_haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2, dphi, dlambda = map(math.radians, [lat1, lat2, lat2 - lat1, lon2 - lon1])
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

@st.cache_data(ttl=86400, show_spinner=False)
def enrichir_cols_v2(ascensions, coords_gpx): 
    if not ascensions: return ascensions
    lats, lons = [lat for lat, lon in coords_gpx], [lon for lat, lon in coords_gpx]
    s, n, w, e = min(lats)-0.02, max(lats)+0.02, min(lons)-0.02, max(lons)+0.02
    query = f"""[out:json][timeout:30];(node["natural"~"saddle|peak|hill|ridge"]["name"]({s},{w},{n},{e});node["mountain_pass"]["name"]({s},{w},{n},{e}););out body;"""
    urls = ["https://overpass.openstreetmap.fr/api/interpreter", "https://overpass-api.de/api/interpreter"]
    
    asc_enrichies = [dict(a) for a in ascensions]
    data = None
    for url in urls:
        try:
            req = requests.post(url, data={"data": query}, timeout=15)
            if req.status_code == 200: data = req.json(); break
        except: continue

    if data:
        cols_osm = [{"lat": n["lat"], "lon": n["lon"], "nom": n["tags"]["name"], "ele": n["tags"].get("ele")} for n in data.get("elements", []) if "name" in n.get("tags", {})]
        for asc in asc_enrichies:
            lat_a, lon_a = asc.get("_lat_sommet"), asc.get("_lon_sommet")
            if not lat_a: continue
            best_nom, best_dist, ele_osm = None, float('inf'), None
            for c in cols_osm:
                if abs(lat_a - c["lat"]) < 0.03 and abs(lon_a - c["lon"]) < 0.03:
                    d = distance_haversine(lat_a, lon_a, c["lat"], c["lon"])
                    if d < 2500 and d < best_dist: best_dist, best_nom, ele_osm = d, c["nom"], c["ele"]
            if best_nom: asc["Nom"], asc["Nom OSM alt"] = best_nom, ele_osm
    return copy.deepcopy(asc_enrichies)

@st.cache_data(ttl=86400, show_spinner=False)
def recuperer_points_eau(coords_gpx):
    if not coords_gpx: return []
    lats, lons = [lat for lat, lon in coords_gpx], [lon for lat, lon in coords_gpx]
    pts = coords_gpx[::30] 
    s, n, w, e = min(lats)-0.02, max(lats)+0.02, min(lons)-0.02, max(lons)+0.02
    query = f"""[out:json][timeout:25];(node["amenity"~"drinking_water|water_point"]({s},{w},{n},{e});node["natural"="spring"]({s},{w},{n},{e}););out body;"""
    urls = ["https://overpass.openstreetmap.fr/api/interpreter", "https://overpass-api.de/api/interpreter"]
    
    eau = []
    data = None
    for url in urls:
        try:
            req = requests.post(url, data={"data": query}, timeout=20)
            if req.status_code == 200: data = req.json(); break
        except: continue

    if data:
        for node in data.get("elements", []):
            lat_w, lon_w = node["lat"], node["lon"]
            for lat_p, lon_p in pts:
                if abs(lat_w - lat_p) < 0.003 and abs(lon_w - lon_p) < 0.004:
                    eau.append({"lat": lat_w, "lon": lon_w, "nom": node.get("tags", {}).get("name", "Point d'eau")})
                    break
    return copy.deepcopy(eau)
