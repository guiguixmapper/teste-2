# --- FICHIER : app.py ---

import streamlit as st
import pandas as pd
import gpxpy
from streamlit_folium import st_folium
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
import math

from climbing import detecter_ascensions, estimer_watts, calculer_calories, zones_actives, get_zone, COULEURS_CAT
from weather import recuperer_fuseau, recuperer_meteo_batch, recuperer_soleil, extraire_meteo, direction_vent_relative, recuperer_qualite_air
from overpass import enrichir_cols_v2, recuperer_points_eau
from map_builder import creer_carte
from gemini_coach import generer_briefing

st.set_page_config(page_title="Vélo & Météo", page_icon="🚴‍♂️", layout="wide", initial_sidebar_state="expanded")

# --- UI / UX APPLE STYLE CSS ---
st.markdown("""
<style>
    /* Global Typography & Background */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', -apple-system, sans-serif; }
    
    /* Header styling */
    .apple-header { text-align: center; padding: 2rem 0 3rem 0; }
    .apple-header h1 { font-weight: 700; font-size: 3rem; letter-spacing: -1px; margin-bottom: 0.5rem; background: -webkit-linear-gradient(120deg, #1d1d1f, #434344); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .apple-header p { color: #86868b; font-size: 1.1rem; font-weight: 400; }
    
    /* Custom Card Design */
    .metric-card {
        background-color: white; border-radius: 20px; padding: 24px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.04); border: 1px solid rgba(0,0,0,0.05);
        transition: transform 0.2s ease; height: 100%;
    }
    .metric-card:hover { transform: translateY(-3px); box-shadow: 0 8px 30px rgba(0,0,0,0.08); }
    .metric-title { font-size: 0.85rem; color: #86868b; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px; margin-bottom: 8px; }
    .metric-value { font-size: 2rem; font-weight: 700; color: #1d1d1f; line-height: 1.1; margin-bottom: 4px; }
    .metric-sub { font-size: 0.9rem; color: #34c759; font-weight: 500; }
    .metric-sub.neutral { color: #86868b; }
    
    /* Dark Mode Support for Cards */
    @media (prefers-color-scheme: dark) {
        .metric-card { background-color: #1c1c1e; border-color: rgba(255,255,255,0.05); }
        .apple-header h1 { background: -webkit-linear-gradient(120deg, #ffffff, #a1a1a6); -webkit-background-clip: text; }
        .metric-value { color: #f5f5f7; }
    }
</style>
""", unsafe_allow_html=True)

# Helper pour créer des jolies cartes HTML
def card(title, value, sub="", sub_class="neutral"):
    return f"""<div class="metric-card">
        <div class="metric-title">{title}</div>
        <div class="metric-value">{value}</div>
        <div class="metric-sub {sub_class}">{sub}</div>
    </div>"""

def parser_gpx(file):
    return [p for t in gpxpy.parse(file).tracks for s in t.segments for p in s.points] if file else []

# --- APP START ---
st.markdown("<div class='apple-header'><h1>Vélo & Météo Pro</h1><p>L'analyseur de tracé ultime pour préparer votre sortie.</p></div>", unsafe_allow_html=True)

# ── SIDEBAR ──
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3163/3163182.png", width=50)
    st.markdown("### Configuration")
    fichier = st.file_uploader("📂 Trace GPX", type=["gpx"])
    date_dep = st.date_input("📅 Date", value=date.today())
    heure_dep = st.time_input("🕐 Heure de départ")
    vitesse = st.number_input("⚡ Vitesse cible plat (km/h)", 15, 50, 25)
    
    st.divider()
    mode = st.radio("Physiologie", ["Puissance", "Cardio"], horizontal=True)
    ref_val = st.number_input("FTP (W)" if mode == "Puissance" else "FC Max", 50, 300, 220)
    poids = st.number_input("⚖️ Poids (Cycliste + Vélo) kg", 50, 150, 75)
    
    with st.expander("🔧 Avancé"):
        gemini_key = st.text_input("Clé API Google Gemini", type="password")

if not fichier:
    st.info("👈 Commencez par importer un fichier GPX dans le menu de gauche.")
    st.stop()

# --- TRAITEMENT DES DONNÉES (Core Logic) ---
points = parser_gpx(fichier.read())
coords = [(p.latitude, p.longitude) for p in points]
date_depart = datetime.combine(date_dep, heure_dep)

dist_tot = d_plus = temps_s = 0.0
profil_data, checkpoints = [], []
for i in range(1, len(points)):
    p1, p2 = points[i-1], points[i]
    d = p1.distance_2d(p2) or 0
    dp = max(0, p2.elevation - p1.elevation) if p1.elevation and p2.elevation else 0
    dist_tot += d
    d_plus += dp
    temps_s += (d + dp * 10) / ((vitesse * 1000) / 3600)
    profil_data.append({"Distance (km)": dist_tot/1000, "Altitude (m)": p2.elevation or 0})
    if temps_s >= len(checkpoints) * 3600: # Checkpoint chaque heure
        hp = date_depart + timedelta(seconds=temps_s)
        cap = (math.degrees(math.atan2(math.sin(math.radians(p2.longitude - p1.longitude)) * math.cos(math.radians(p2.latitude)), math.cos(math.radians(p1.latitude)) * math.sin(math.radians(p2.latitude)) - math.sin(math.radians(p1.latitude)) * math.cos(math.radians(p2.latitude)) * math.cos(math.radians(p2.longitude - p1.longitude)))) + 360) % 360
        checkpoints.append({"lat": p2.latitude, "lon": p2.longitude, "Cap": cap, "Heure": hp.strftime("%H:%M"), "Heure_API": hp.replace(minute=0, second=0).strftime("%Y-%m-%dT%H:00"), "Km": round(dist_tot/1000, 1)})

vit_moy = round((dist_tot / 1000) / (temps_s / 3600), 1)
df_profil = pd.DataFrame(profil_data)
ascensions = enrichir_cols_v2(detecter_ascensions(df_profil), coords)
points_eau = recuperer_points_eau(coords)

# Météo
frozen = tuple((cp["lat"], cp["lon"], cp["Heure_API"]) for cp in checkpoints)
rep_list = recuperer_meteo_batch(frozen, is_past=(date_dep < date.today()), date_str=date_dep.strftime("%Y-%m-%d"))
resultats, temp_moy = [], 20
if rep_list:
    for i, cp in enumerate(checkpoints):
        m = extraire_meteo(rep_list[i] if i < len(rep_list) else {}, cp["Heure_API"])
        if m["dir_deg"]: m["effet"] = direction_vent_relative(cp["Cap"], m["dir_deg"])
        cp.update(m)
        resultats.append(cp)
    valides = [c["temp_val"] for c in resultats if c.get("temp_val")]
    if valides: temp_moy = sum(valides)/len(valides)

calories = calculer_calories(max(1, poids-10), temps_s, dist_tot, d_plus, vitesse)

# NOUVEAU : Planificateur Nutritionnel Pro
duree_h = temps_s / 3600
eau_litres = round(duree_h * (0.5 if temp_moy < 15 else 0.7 if temp_moy < 25 else 1.0), 1)
carbs_g = int(duree_h * 60)

# --- UI DISPLAY ---
st.markdown("### 📊 Vue d'ensemble")

# Ligne 1 : Data de base
c1, c2, c3, c4 = st.columns(4)
c1.markdown(card("Distance", f"{round(dist_tot/1000, 1)} <span style='font-size:1rem'>km</span>", f"Arrivée à {(date_depart + timedelta(seconds=temps_s)).strftime('%H:%M')}"), unsafe_allow_html=True)
c2.markdown(card("Dénivelé", f"{int(d_plus)} <span style='font-size:1rem'>m</span>", f"{len(ascensions)} cols catégorisés"), unsafe_allow_html=True)
c3.markdown(card("Temps estimé", f"{int(duree_h)}h {int((temps_s%3600)//60):02d}m", f"Moyenne : {vit_moy} km/h"), unsafe_allow_html=True)
c4.markdown(card("Météo", f"{int(temp_moy)}°C", "Conditions favorables", "metric-sub"), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Ligne 2 : Planificateur Nutritionnel
st.markdown("### 🔋 Planificateur Nutrition")
n1, n2, n3 = st.columns(3)
n1.markdown(card("💧 Hydratation requise", f"{eau_litres} L", f"Base de {round(eau_litres/duree_h, 2)}L / heure. Points d'eau sur la route : {len(points_eau)}"), unsafe_allow_html=True)
n2.markdown(card("⚡ Glucides requis", f"{carbs_g} g", "Soit environ " + str(int(carbs_g/30)) + " barres/gels"), unsafe_allow_html=True)
n3.markdown(card("🔥 Dépense totale", f"{calories} kcal", "Énergie métabolique totale"), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ONGLETS
t_map, t_profil, t_coach = st.tabs(["🗺️ Carte Interactive", "⛰️ Profil & Cols", "🤖 Coach IA"])

with t_map:
    st_folium(creer_carte(points, resultats, ascensions, points_eau), width="100%", height=600)

with t_profil:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_profil["Distance (km)"], y=df_profil["Altitude (m)"], fill="tozeroy", line=dict(color="#007AFF", width=2), name="Profil"))
    fig.update_layout(height=400, margin=dict(l=0,r=0,t=0,b=0), template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)
    if ascensions:
        st.dataframe(pd.DataFrame(ascensions)[["Catégorie", "Nom", "Longueur", "Dénivelé", "Pente moy."]], use_container_width=True, hide_index=True)

with t_coach:
    if gemini_key and st.button("Demander le briefing du Directeur Sportif"):
        with st.spinner("Analyse par l'IA..."):
            ctx = f"le {date_dep.strftime('%d/%m/%Y')}"
            st.success(generer_briefing(gemini_key, dist_tot, d_plus, temps_s, calories, {"total":8}, ascensions, None, resultats, heure_dep.strftime('%H:%M'), "12:00", vit_moy, None, ctx, len(points_eau), {}, False))
    elif not gemini_key:
        st.warning("Veuillez entrer une clé API Gemini dans le menu de gauche.")
