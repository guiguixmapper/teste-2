"""
🚴‍♂️ Vélo & Météo — V12.1 (Carte Propre XXL + Vitesse Réelle + IA)
================================
Analyse de tracé GPX : météo en temps réel, cols UCI, profil interactif,
zones d'entraînement, score de conditions et Coach IA complet.
"""

import streamlit as st
import pandas as pd
import gpxpy
import folium
from streamlit_folium import st_folium
import requests
from datetime import datetime, timedelta, date
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import math
import logging
import base64
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==============================================================================
# STYLE GLOBAL
# ==============================================================================

CSS = """
<style>
  :root {
    --bleu: #2563eb; --bleu-l: #dbeafe;
    --gris: #6b7280; --border: #e2e8f0; --radius: 12px;
  }
  .app-header {
    background: linear-gradient(135deg, #1e40af 0%, #2563eb 55%, #0ea5e9 100%);
    border-radius: var(--radius); padding: 24px 32px 20px;
    margin-bottom: 20px; color: white;
  }
  .app-header h1 { font-size: 1.9rem; font-weight: 800; margin: 0; letter-spacing: -.5px; }
  .app-header p  { font-size: .9rem; margin: 5px 0 0; opacity: .85; }
  .soleil-row {
    display: flex; gap: 14px; flex-wrap: wrap;
    background: linear-gradient(90deg, #fef3c7, #fde68a);
    border-radius: var(--radius); padding: 12px 18px; margin: 10px 0; align-items: center;
  }
  .soleil-item .s-val { font-size: 1.05rem; font-weight: 700; color: #92400e; }
  .soleil-item .s-lbl { font-size: .7rem; color: #b45309; }
  @media (max-width: 640px) { .app-header h1 { font-size: 1.35rem; } }
</style>
"""

# ==============================================================================
# IMPORTS MODULES
# ==============================================================================

import climbing as climbing_module
from climbing import (
    detecter_ascensions, categoriser_uci, estimer_watts, estimer_fc,
    estimer_temps_col, calculer_calories, get_zone, zones_actives,
    COULEURS_CAT, LEGENDE_UCI,
)
from weather import (
    recuperer_fuseau, recuperer_meteo_batch, recuperer_soleil,
    extraire_meteo, direction_vent_relative, wind_chill,
    label_wind_chill, obtenir_icone_meteo,
)
from overpass import enrichir_cols
from gemini_coach import generer_briefing

@st.cache_data(ttl=1800, show_spinner=False)
def memoire_meteo(frozen, is_past=False, date_str=None):
    return recuperer_meteo_batch(frozen, is_past=is_past, date_str=date_str)


# ==============================================================================
# UTILITAIRES GPS & HTML
# ==============================================================================

def calculer_cap(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


@st.cache_data(show_spinner=False)
def parser_gpx(data):
    try:
        gpx = gpxpy.parse(data)
        return [p for t in gpx.tracks for s in t.segments for p in s.points]
    except Exception as e:
        logger.error(f"GPX : {e}"); return []


def generer_html_resume(score, ascensions, resultats, dist_tot, d_plus, d_moins,
                        temps_s, heure_depart, heure_arr, vitesse_plat, vit_moy_reelle, 
                        calories, carte, df_profil, ref_val, mode, poids, briefing_ia=None):
    
    dh = int(temps_s // 3600); dm = int((temps_s % 3600) // 60)
    
    # --- TABLEAUX ---
    cols_html = ""
    for a in ascensions:
        nom = a.get("Nom", "—")
        cols_html += (
            f"<tr><td>{a['Catégorie']}</td><td>{nom if nom != '—' else ''}</td>"
            f"<td>{a['Départ (km)']} km</td><td>{a['Longueur']}</td><td>{a['Dénivelé']}</td>"
            f"<td>{a['Pente moy.']}</td><td>{a.get('Temps col','—')}</td>"
            f"<td>{a.get('Arrivée sommet','—')}</td></tr>"
        )
        
    meteo_html = ""
    valides = [cp for cp in resultats if cp.get("temp_val") is not None]
    for cp in valides:
        t = cp.get('temp_val')
        meteo_html += (
            f"<tr><td>{cp['Heure']}</td><td>{cp['Km']} km</td>"
            f"<td>{cp.get('Ciel','—')}</td><td>{f'{t}°C' if t else '—'}</td>"
            f"<td>{cp.get('Pluie','—')}</td><td>{cp.get('vent_val','—')} km/h</td>"
            f"<td>{cp.get('effet','—')}</td></tr>"
        )

    # --- INTEGRATION DE LA CARTE FOLIUM (XXL) ---
    b64_map = base64.b64encode(carte.get_root().render().encode('utf-8')).decode('utf-8')
    iframe_map = f'<iframe src="data:text/html;base64,{b64_map}" style="width:100%; height:800px; border:1px solid #e2e8f0; border-radius:8px;"></iframe>'

    # --- INTEGRATION DES GRAPHIQUES PLOTLY ---
    fig_profil = creer_figure_profil(df_profil, ascensions, vitesse_plat, ref_val, mode, poids)
    html_profil = fig_profil.to_html(full_html=False, include_plotlyjs='cdn')
    
    html_profils_cols = ""
    if ascensions:
        html_profils_cols = "<h2>🔍 Profils des montées</h2>"
        for asc in ascensions:
            fig_col = creer_figure_col(df_profil, asc)
            if fig_col:
                html_profils_cols += fig_col.to_html(full_html=False, include_plotlyjs=False)

    # --- FORMATAGE DU BRIEFING IA ---
    html_briefing = ""
    if briefing_ia:
        texte_formate = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', briefing_ia)
        texte_formate = texte_formate.replace('\n', '<br>')
        html_briefing = f"""
        <h2>🎙️ Le Briefing du Coach IA</h2>
        <div class="ia-box">
            {texte_formate}
        </div>
        """

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Roadbook Velo</title>
<style>
  /* Élargissement du max-width de 1000px à 1200px pour une carte plus grande */
  body{{font-family:Arial,sans-serif;padding:32px;color:#1e293b;max-width:1200px;margin:auto}}
  h1{{color:#1e40af;border-bottom:3px solid #1e40af;padding-bottom:8px; margin-top: 0;}}
  h2{{color:#1e40af;margin-top:35px}}
  .score{{background:#1e40af;color:white;border-radius:10px;padding:14px 20px;
          font-size:1.1rem;font-weight:700;margin:12px 0;display:inline-block}}
  .grid{{display:flex;gap:14px;flex-wrap:wrap;margin:14px 0}}
  .card{{background:#f1f5f9;border-radius:8px;padding:12px 18px;text-align:center;flex:1;min-width:120px}}
  .card .v{{font-size:1.4rem;font-weight:700;color:#1e40af}}
  .card .l{{font-size:.72rem;color:#64748b;margin-top:3px}}
  .ia-box{{background-color:#f8fafc; padding:25px; border-radius:12px; border-left:6px solid #22c55e; color:#1e293b; font-size:1.05rem; line-height:1.6; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-top: 15px;}}
  table{{width:100%;border-collapse:collapse;margin-top:10px;font-size:.83rem}}
  th{{background:#1e40af;color:white;padding:8px;text-align:left}}
  td{{padding:6px 8px;border-bottom:1px solid #e2e8f0}}
  tr:nth-child(even) td{{background:#f8fafc}}
  
  .btn-print {{
      background-color: #2563eb; color: white; border: none; padding: 12px 24px;
      font-size: 1.1rem; border-radius: 8px; cursor: pointer; font-weight: bold;
      float: right; box-shadow: 0 4px 6px rgba(0,0,0,0.1); transition: background-color 0.2s;
  }}
  .btn-print:hover {{ background-color: #1e40af; }}
  
  @media print {{
      .btn-print {{ display: none !important; }}
      body {{ padding: 0; max-width: 100%; }}
      .score, .card, th, .ia-box {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
      table {{ page-break-inside: auto; }}
      tr {{ page-break-inside: avoid; page-break-after: auto; }}
      h2 {{ page-break-after: avoid; }}
      .ia-box, iframe, .js-plotly-plot {{ page-break-inside: avoid; }}
  }}
</style></head><body>

<button onclick="window.print()" class="btn-print">📄 Enregistrer en PDF</button>

<h1>🚴‍♂️ Carnet de route détaillé</h1>
<p>Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')} · Départ prévu : {heure_depart.strftime('%d/%m/%Y %H:%M')}</p>

<div class="score">{score['label']} — {score['total']}/10 &nbsp;|&nbsp;
  🌤️ {score['score_meteo']}/6 &nbsp;|&nbsp; 🏔️ {score['score_cols']}/4</div>
  
<div class="grid">
  <div class="card"><div class="v">{round(dist_tot/1000,1)} km</div><div class="l">📏 Distance</div></div>
  <div class="card"><div class="v">{int(d_plus)} m</div><div class="l">⬆️ D+</div></div>
  <div class="card"><div class="v">{int(d_moins)} m</div><div class="l">⬇️ D−</div></div>
  <div class="card"><div class="v">{dh}h{dm:02d}m</div><div class="l">⏱️ Durée estimée</div></div>
  <div class="card"><div class="v">{heure_arr.strftime('%H:%M')}</div><div class="l">🏁 Arrivée</div></div>
  <div class="card"><div class="v" style="color:#059669">{vit_moy_reelle} km/h</div><div class="l">🚴 Moy. réelle<br>(Plat: {vitesse_plat} km/h)</div></div>
  <div class="card"><div class="v">{calories} kcal</div><div class="l">🔥 Calories</div></div>
</div>

<h2>🗺️ Carte du parcours</h2>
{iframe_map}

<h2>⛰️ Profil global</h2>
{html_profil}

<h2>🏔️ Liste des ascensions</h2>
{"<p>Aucune difficulté catégorisée.</p>" if not ascensions else
 "<table><tr><th>Cat.</th><th>Nom</th><th>Départ</th><th>Long.</th><th>D+</th>"
 "<th>Pente</th><th>Temps</th><th>Arrivée</th></tr>" + cols_html + "</table>"}

{html_profils_cols}

<h2>🌤️ Météo détaillée</h2>
{"<p>Données météo indisponibles.</p>" if not meteo_html else
 "<table><tr><th>Heure</th><th>Km</th><th>Ciel</th><th>Temp</th>"
 "<th>Pluie</th><th>Vent</th><th>Effet</th></tr>" + meteo_html + "</table>"}

{html_briefing}

</body></html>""".encode("utf-8")


# ==============================================================================
# SCORE GLOBAL ET ANALYSE
# ==============================================================================

def analyser_meteo_detaillee(resultats, dist_tot):
    valides = [cp for cp in resultats if cp.get("temp_val") is not None]
    if not valides:
        return None

    cps_pluie = [cp for cp in valides if (cp.get("pluie_pct") or 0) >= 50]
    pct_pluie = len(cps_pluie) / len(valides) * 100

    premier_pluie = None
    for cp in valides:
        if (cp.get("pluie_pct") or 0) >= 50:
            premier_pluie = cp
            break

    compteur_effet = {"⬇️ Face": 0, "⬆️ Dos": 0, "↙️ Côté (D)": 0, "↘️ Côté (G)": 0, "—": 0}
    for cp in valides:
        effet = cp.get("effet", "—")
        compteur_effet[effet] = compteur_effet.get(effet, 0) + 1

    total_v = len(valides)
    pct_face  = round(compteur_effet["⬇️ Face"]    / total_v * 100)
    pct_dos   = round(compteur_effet["⬆️ Dos"]     / total_v * 100)
    pct_cote  = round((compteur_effet["↙️ Côté (D)"] + compteur_effet["↘️ Côté (G)"]) / total_v * 100)

    segments_face = []
    en_face = False
    debut_face = None
    for cp in valides:
        if cp.get("effet") == "⬇️ Face":
            if not en_face:
                en_face    = True
                debut_face = cp["Km"]
        else:
            if en_face:
                segments_face.append((debut_face, cp["Km"]))
                en_face = False
    if en_face:
        segments_face.append((debut_face, valides[-1]["Km"]))

    return {
        "pct_pluie":       round(pct_pluie),
        "premier_pluie":   premier_pluie,
        "pct_face":        pct_face,
        "pct_dos":         pct_dos,
        "pct_cote":        pct_cote,
        "segments_face":   segments_face,
        "n_valides":       total_v,
    }

def calculer_score(resultats, ascensions, d_plus, vitesse, ref_val, mode, poids):
    valides = [cp for cp in resultats if cp.get("temp_val") is not None]

    if valides:
        tm = sum(cp["temp_val"] for cp in valides) / len(valides)
        if   15 <= tm <= 22: s_temp = 2.0
        elif 10 <= tm <= 27: s_temp = 1.5
        elif  5 <= tm <= 32: s_temp = 0.8
        elif  0 <= tm:       s_temp = 0.3
        else:                s_temp = 0.0

        POIDS_EFFET = { "⬇️ Face": 1.5, "↙️ Côté (D)": 0.7, "↘️ Côté (G)": 0.7, "⬆️ Dos": -0.3, "—": 0.5 }
        ve_moy = sum((cp.get("vent_val") or 0) * POIDS_EFFET.get(cp.get("effet", "—"), 0.5) for cp in valides) / len(valides)
        if   ve_moy <= 8:  s_vent = 2.0
        elif ve_moy <= 18: s_vent = 1.5
        elif ve_moy <= 30: s_vent = 0.8
        elif ve_moy <= 45: s_vent = 0.3
        else:              s_vent = 0.0

        pm = sum(cp.get("pluie_pct") or 0 for cp in valides) / len(valides)
        s_pluie = round(max(0.0, 2.0 * (1 - pm / 100)), 2)
        sm = s_temp + s_vent + s_pluie
    else:
        sm = 3.0   

    dist_km = sum(cp.get("Km", 0) for cp in resultats[-1:])
    if   dist_km < 30:  s_dist = 0.5
    elif dist_km < 80:  s_dist = 0.7
    elif dist_km < 150: s_dist = 0.9
    else:               s_dist = 1.0

    if   d_plus < 300:  s_dplus = 0.5
    elif d_plus < 1000: s_dplus = 0.7
    elif d_plus < 2500: s_dplus = 0.9
    else:               s_dplus = 1.0

    s_parcours = s_dist + s_dplus

    if ascensions and ref_val > 0:
        wm  = sum(estimer_watts(a["_pente_moy"], vitesse, poids) for a in ascensions) / len(ascensions)
        pct = wm / ref_val if mode == "⚡ Puissance" else 0.85
        if   pct <= 0.50: s_effort = 0.8
        elif pct <= 0.70: s_effort = 1.2
        elif pct <= 0.90: s_effort = 2.0
        elif pct <= 1.05: s_effort = 1.5
        else:             s_effort = 0.8
    else:
        s_effort = 1.0

    sc = max(2.0, s_parcours + s_effort)
    total = round(min(10.0, max(0.0, sm + sc)), 1)
    lbl   = ("🔴 Déconseillé"       if total < 3.5 else
             "🟠 Conditions difficiles" if total < 5.0 else
             "🟡 Conditions correctes"  if total < 6.5 else
             "🟢 Bonne sortie"          if total < 8.0 else
             "⭐ Conditions idéales")

    return {
        "total":        total,
        "label":        lbl,
        "score_meteo":  round(max(0.0, sm), 1),
        "score_cols":   round(sc, 1),
        "score_effort": round(s_effort, 1),
    }


# ==============================================================================
# GRAPHIQUES
# ==============================================================================

def creer_figure_profil(df, ascensions, vitesse, ref_val, mode, poids, idx_survol=None):
    fig   = go.Figure()
    dists = df["Distance (km)"].tolist()
    alts  = df["Altitude (m)"].tolist()
    zones = zones_actives(mode)
    fig.add_trace(go.Scatter(
        x=dists, y=alts, fill="tozeroy", fillcolor="rgba(59,130,246,0.12)",
        line=dict(color="#3b82f6", width=2),
        hovertemplate="<b>Km %{x:.1f}</b><br>Altitude : %{y:.0f} m<extra></extra>",
        name="Profil"))
    for i, asc in enumerate(ascensions):
        d0, d1 = asc["_debut_km"], asc["_sommet_km"]
        cat    = asc["Catégorie"]
        nom    = asc.get("Nom", "—")
        coul   = COULEURS_CAT.get(cat, "#94a3b8")
        op     = 1.0 if idx_survol is None or idx_survol == i else 0.2
        sx     = [d for d in dists if d0 <= d <= d1]
        sy     = [alts[j] for j, d in enumerate(dists) if d0 <= d <= d1]
        if not sx: continue
        w = estimer_watts(asc["_pente_moy"], vitesse, poids)
        _, zlbl, zcoul = get_zone(w, ref_val, zones)
        r, g, b = int(zcoul[1:3],16), int(zcoul[3:5],16), int(zcoul[5:7],16)
        hover_extra = (f"FC est. : {estimer_fc(w, ref_val, ref_val)}bpm"
                       if mode == "🫀 Fréquence Cardiaque"
                       else f"Puissance est. : {w} W ({round(w/ref_val*100) if ref_val>0 else '?'}% FTP)")
        fig.add_trace(go.Scatter(
            x=sx, y=sy, fill="tozeroy",
            fillcolor=f"rgba({r},{g},{b},{round(op*0.35,2)})",
            line=dict(color=coul, width=3 if idx_survol==i else 2), opacity=op,
            hovertemplate=(f"<b>{cat}{' — '+nom if nom!='—' else ''}</b>"
                           f"<br>Km %{{x:.1f}}<br>Alt : %{{y:.0f}} m<br>{hover_extra}<extra></extra>"),
            name=nom if nom != "—" else cat, showlegend=True, legendgroup=cat))
        fig.add_annotation(
            x=d1, y=sy[-1] if sy else 0,
            text=f"▲ {nom if nom != '—' else cat.split()[0]}",
            showarrow=True, arrowhead=2, arrowsize=.8,
            arrowcolor=coul, font=dict(size=10, color=coul),
            bgcolor="white", bordercolor=coul, borderwidth=1, opacity=op)
    fig.update_layout(
        height=500, margin=dict(l=50,r=20,t=30,b=40),
        xaxis=dict(title="Distance (km)", showgrid=True, gridcolor="#e2e8f0",
                   title_font=dict(color="#1e293b"), tickfont=dict(color="#1e293b")),
        yaxis=dict(title="Altitude (m)", showgrid=True, gridcolor="#e2e8f0",
                   title_font=dict(color="#1e293b"), tickfont=dict(color="#1e293b")),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(color="#1e293b"), bgcolor="rgba(255,255,255,0.9)",
                    bordercolor="#e2e8f0", borderwidth=1),
        hovermode="x unified", plot_bgcolor="white", paper_bgcolor="white",
        font=dict(color="#1e293b"))
    return fig

def creer_figure_col(df_profil, asc, nb_segments=None):
    d0, d1 = asc["_debut_km"], asc["_sommet_km"]
    dk     = d1 - d0
    mask      = [d0 <= d <= d1 for d in df_profil["Distance (km)"]]
    dists_col = [d for d, m in zip(df_profil["Distance (km)"], mask) if m]
    alts_col  = [a for a, m in zip(df_profil["Altitude (m)"], mask) if m]
    if len(dists_col) < 2: return None
    seg_km = dk / nb_segments if nb_segments else (0.5 if dk < 5 else 1.0 if dk < 15 else 2.0)

    def couleur_pente(p):
        if p < 3:    return "#22c55e"
        elif p < 6:  return "#84cc16"
        elif p < 8:  return "#eab308"
        elif p < 10: return "#f97316"
        elif p < 12: return "#ef4444"
        else:        return "#7f1d1d"

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dists_col, y=alts_col, fill="tozeroy",
        fillcolor="rgba(203,213,225,0.2)", line=dict(color="#94a3b8", width=1),
        hoverinfo="skip", showlegend=False))
    km_d = dists_col[0]
    while km_d < dists_col[-1] - 0.05:
        km_f = min(km_d + seg_km, dists_col[-1])
        sx = [d for d in dists_col if km_d <= d <= km_f]
        sy = [alts_col[j] for j, d in enumerate(dists_col) if km_d <= d <= km_f]
        if len(sx) >= 2:
            dist_m = (sx[-1] - sx[0]) * 1000
            pente  = (max(0, sy[-1]-sy[0]) / dist_m * 100) if dist_m > 0 else 0
            coul   = couleur_pente(pente)
            r, g, b = int(coul[1:3],16), int(coul[3:5],16), int(coul[5:7],16)
            fig.add_trace(go.Scatter(
                x=sx, y=sy, fill="tozeroy", fillcolor=f"rgba({r},{g},{b},0.4)",
                line=dict(color=coul, width=3),
                hovertemplate=f"<b>{round(pente,1)}%</b><br>Km %{{x:.1f}}<br>Alt : %{{y:.0f}} m<extra></extra>",
                showlegend=False))
            if dist_m > 300:
                fig.add_annotation(
                    x=(sx[0]+sx[-1])/2, y=sy[len(sy)//2],
                    text=f"<b>{round(pente,1)}%</b>", showarrow=False,
                    font=dict(size=10, color=coul), bgcolor="rgba(255,255,255,0.8)",
                    bordercolor=coul, borderwidth=1, yshift=12)
        km_d = km_f
    fig.add_trace(go.Scatter(x=dists_col, y=alts_col, mode="lines",
        line=dict(color="#1e293b", width=2),
        hovertemplate="Km %{x:.1f} — Alt : %{y:.0f} m<extra></extra>",
        showlegend=False))
    nom   = asc.get("Nom", "—")
    titre = (f"{nom+' — ' if nom != '—' else ''}{asc['Catégorie']} — "
             f"{asc['Longueur']} · {asc['Dénivelé']} · {asc['Pente moy.']} moy. · {asc['Pente max']} max")
    fig.update_layout(
        height=380, margin=dict(l=50,r=20,t=40,b=40),
        xaxis=dict(title="Distance (km)", showgrid=True, gridcolor="#f1f5f9",
                   title_font=dict(color="#1e293b"), tickfont=dict(color="#1e293b")),
        yaxis=dict(title="Altitude (m)", showgrid=True, gridcolor="#f1f5f9",
                   title_font=dict(color="#1e293b"), tickfont=dict(color="#1e293b")),
        plot_bgcolor="white", paper_bgcolor="white", font=dict(color="#1e293b"),
        hovermode="x unified",
        title=dict(text=titre, font=dict(size=13, color="#1e293b"), x=0))
    return fig

def creer_figure_meteo(resultats):
    kms, temps, vents, rafales, pluies, cv, cp_ = [], [], [], [], [], [], []
    for r in resultats:
        t = r.get("temp_val"); v = r.get("vent_val")
        if t is None or v is None: continue
        kms.append(r["Km"]); temps.append(t); vents.append(v)
        rafales.append(r.get("rafales_val") or v); pluies.append(r.get("pluie_pct") or 0)
        cv.append("#ef4444" if v>=40 else "#f97316" if v>=25 else "#eab308" if v>=10 else "#22c55e")
        p = r.get("pluie_pct") or 0
        cp_.append("#1d4ed8" if p>=70 else "#2563eb" if p>=40 else "#60a5fa" if p>=20 else "#bfdbfe")
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.40, 0.33, 0.27], vertical_spacing=0.06,
        subplot_titles=["🌡️ Température (°C)", "💨 Vent moyen & Rafales (km/h)", "🌧️ Probabilité de pluie (%)"])
    if kms:
        ct = ["#8b5cf6" if t<5 else "#3b82f6" if t<15 else "#22c55e" if t<22
              else "#f97316" if t<30 else "#ef4444" for t in temps]
        fig.add_trace(go.Scatter(x=kms, y=temps, mode="lines+markers",
            line=dict(color="#f97316", width=2.5),
            marker=dict(color=ct, size=9, line=dict(color="white", width=1.5)),
            hovertemplate="<b>Km %{x}</b><br>Temp : %{y}°C<extra></extra>",
            name="Température"), row=1, col=1)
        fig.add_hrect(y0=15, y1=22, row=1, col=1, fillcolor="rgba(34,197,94,0.10)", line_width=0,
            annotation_text="Zone idéale (15–22°C)", annotation_font_size=9,
            annotation_font_color="#16a34a", annotation_position="top left")
        fig.add_trace(go.Bar(x=kms, y=vents, marker_color=cv, name="Vent moyen",
            hovertemplate="<b>Km %{x}</b><br>Vent : %{y} km/h<extra></extra>"), row=2, col=1)
        fig.add_trace(go.Scatter(x=kms, y=rafales, mode="lines+markers",
            line=dict(color="#475569", width=1.8, dash="dot"),
            marker=dict(size=5, color="#475569"), name="Rafales",
            hovertemplate="<b>Km %{x}</b><br>Rafales : %{y} km/h<extra></extra>"), row=2, col=1)
        fig.add_trace(go.Bar(x=kms, y=pluies, marker_color=cp_, name="Pluie",
            hovertemplate="<b>Km %{x}</b><br>Pluie : %{y}%<extra></extra>"), row=3, col=1)
        fig.add_hline(y=50, row=3, col=1, line_dash="dot", line_color="#64748b", line_width=1.5,
            annotation_text="Seuil 50%", annotation_font_size=9,
            annotation_font_color="#64748b", annotation_position="top right")
    fig.update_layout(height=620, margin=dict(l=55,r=20,t=45,b=40),
        hovermode="x unified", plot_bgcolor="white", paper_bgcolor="white",
        showlegend=False, dragmode=False, font=dict(color="#1e293b"),
        annotationdefaults=dict(font=dict(color="#1e293b")))
    for ann in fig.layout.annotations:
        ann.font.color = "#1e293b"; ann.font.size = 13
    fig.update_yaxes(showgrid=True, gridcolor="#f1f5f9", row=1, col=1, title_text="°C")
    fig.update_yaxes(showgrid=True, gridcolor="#f1f5f9", row=2, col=1, title_text="km/h", rangemode="tozero")
    fig.update_yaxes(showgrid=True, gridcolor="#f1f5f9", row=3, col=1, title_text="%", range=[0,105])
    fig.update_xaxes(showgrid=True, gridcolor="#f1f5f9", row=1, col=1)
    fig.update_xaxes(showgrid=True, gridcolor="#f1f5f9", row=2, col=1)
    fig.update_xaxes(showgrid=True, gridcolor="#f1f5f9", title_text="Distance (km)", row=3, col=1)
    return fig


# ==============================================================================
# CARTE
# ==============================================================================

def creer_carte(points_gpx, resultats, ascensions, tiles="CartoDB positron", attr=None):
    kwargs = dict(location=[points_gpx[0].latitude, points_gpx[0].longitude],
                  zoom_start=11, tiles=tiles, scrollWheelZoom=True)
    if attr: kwargs["attr"] = attr
    carte = folium.Map(**kwargs)
    
    fg_meteo = folium.FeatureGroup(name="🌤️ Météo",      show=True)
    fg_cols  = folium.FeatureGroup(name="🏔️ Ascensions", show=True)
    fg_trace = folium.FeatureGroup(name="📍 Parcours",   show=True)
    
    folium.PolyLine([[p.latitude, p.longitude] for p in points_gpx],
                    color="#2563eb", weight=5, opacity=0.9).add_to(fg_trace)
    folium.Marker([points_gpx[0].latitude, points_gpx[0].longitude], tooltip="🚦 Départ",
                  icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(fg_trace)
    folium.Marker([points_gpx[-1].latitude, points_gpx[-1].longitude], tooltip="🏁 Arrivée",
                  icon=folium.Icon(color="red", icon="flag", prefix="fa")).add_to(fg_trace)
    
    COULEUR_COL = {"🔴 HC":"red","🟠 1ère Cat.":"orange",
                   "🟡 2ème Cat.":"beige","🟢 3ème Cat.":"green","🔵 4ème Cat.":"blue"}
    
    for asc in ascensions:
        lat_s = asc.get("_lat_sommet")
        lon_s = asc.get("_lon_sommet")
        if lat_s is None or lon_s is None:
            continue
        nom     = asc.get("Nom", "—")
        coul    = COULEUR_COL.get(asc["Catégorie"], "blue")
        alt_osm = asc.get("Nom OSM alt")
        alt_line = (f'<div>⛰️ Sommet GPX : {asc["Alt. sommet"]}'
                    + (f' &nbsp;·&nbsp; OSM : {alt_osm} m' if alt_osm else '') + '</div>')
        popup_col = (
            '<div style="font-family:sans-serif;font-size:12px;min-width:180px">'
            f'<div style="font-weight:700;font-size:14px;margin-bottom:6px">'
            f'{nom+" — " if nom != "—" else ""}{asc["Catégorie"]}</div>'
            f'<div>📏 {asc["Longueur"]} &nbsp;·&nbsp; D+ {asc["Dénivelé"]}</div>'
            f'<div>📐 {asc["Pente moy."]} moy. &nbsp;·&nbsp; {asc["Pente max"]} max</div>'
            + alt_line
            + (f'<div style="margin-top:5px">⏱️ {asc.get("Temps col","—")} &nbsp;·&nbsp; arr. {asc.get("Arrivée sommet","—")}</div>'
               if asc.get("Temps col") else "")
            + '</div>')
        folium.Marker([lat_s, lon_s],
            popup=folium.Popup(popup_col, max_width=260),
            tooltip=folium.Tooltip(f'▲ {nom if nom != "—" else asc["Catégorie"]} — {asc["Alt. sommet"]}', sticky=True),
            icon=folium.Icon(color=coul, icon="chevron-up", prefix="fa")).add_to(fg_cols)
            
    for cp in resultats:
        t = cp.get("temp_val")
        if t is None: continue
        dd = cp.get("dir_deg"); vv = cp.get("vent_val", 0) or 0
        fc  = "#ef4444" if vv>=40 else "#f97316" if vv>=25 else "#eab308" if vv>=10 else "#22c55e"
        rot = (dd + 180) % 360 if dd is not None else 0
        svg = (f'<svg width="16" height="16" viewBox="0 0 28 28" style="vertical-align:middle">'
               f'<g transform="rotate({rot},14,14)"><polygon points="14,2 20,22 14,18 8,22" fill="{fc}"/>'
               f'</g></svg>') if dd is not None else "💨"
        pp = cp.get("pluie_pct")
        if pp is not None:
            pc    = "#1d4ed8" if pp>=70 else "#2563eb" if pp>=40 else "#60a5fa"
            barre = (f'<div style="margin:4px 0 2px;font-size:11px">&#127783; Pluie : <b>{pp}%</b></div>'
                     '<div style="background:#e2e8f0;border-radius:4px;height:6px;width:100%">'
                     f'<div style="background:{pc};width:{pp}%;height:6px;border-radius:4px"></div></div>')
        else:
            barre = '<div style="font-size:11px">&#127783; Pluie : —</div>'
        res    = cp.get("ressenti")
        popup  = (
            '<div style="font-family:sans-serif;font-size:12px;min-width:200px">'
            f'<div style="font-weight:700;font-size:13px;border-bottom:1px solid #e2e8f0;'
            f'padding-bottom:4px;margin-bottom:6px">{cp["Heure"]} — Km {cp["Km"]}</div>'
            f'<div style="color:#6b7280;margin-bottom:5px">⛰️ Alt : {cp["Alt (m)"]} m</div>'
            f'<div style="font-size:15px;margin-bottom:3px">{cp["Ciel"]} <b>{t}°C</b>'
            + (f' <span style="color:#6b7280;font-size:11px">(ressenti {res}°C)</span>' if res else "")
            + f'</div>{barre}'
            f'<div style="margin-top:7px;padding-top:5px;border-top:1px solid #f1f5f9">'
            f'<div style="display:flex;align-items:center;gap:5px;margin-bottom:2px">'
            f'{svg} <b>{vv} km/h</b> <span style="color:#6b7280">du {cp["Dir"]}</span></div>'
            f'<div style="color:#6b7280;font-size:11px">Rafales : {cp.get("rafales_val","—")} km/h</div>'
            f'<div style="margin-top:3px;font-size:11px">🚴 <b>{cp.get("effet","—")}</b></div>'
            '</div></div>')
        folium.Marker([cp["lat"], cp["lon"]],
            popup=folium.Popup(popup, max_width=280),
            tooltip=folium.Tooltip(
                f"{cp['Heure']} | {cp['Ciel']} {t}°C | "
                f'<svg width="12" height="12" viewBox="0 0 28 28" style="vertical-align:middle">'
                f'<g transform="rotate({rot},14,14)"><polygon points="14,2 20,22 14,18 8,22" fill="{fc}"/></g></svg>'
                f" {vv} km/h", sticky=True),
            icon=folium.Icon(color="blue", icon="info-sign")).add_to(fg_meteo)

    fg_meteo.add_to(carte)
    fg_cols.add_to(carte)
    fg_trace.add_to(carte)

    folium.LayerControl(collapsed=False, position="topright").add_to(carte)

    css_legende = """
    <style>
    .leaflet-control-layers {
        border-radius: 10px !important;
        border: none !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.15) !important;
        padding: 0 !important;
        overflow: hidden;
        font-family: Arial, sans-serif !important;
    }
    .leaflet-control-layers-expanded {
        padding: 10px 14px !important;
        min-width: 160px !important;
    }
    .leaflet-control-layers-list {
        margin: 0 !important;
    }
    .leaflet-control-layers label {
        display: flex !important;
        align-items: center !important;
        gap: 6px !important;
        font-size: 13px !important;
        color: #1e293b !important;
        margin: 4px 0 !important;
        cursor: pointer !important;
    }
    .leaflet-control-layers-separator {
        display: none !important;
    }
    .leaflet-control-layers-overlays {
        display: flex !important;
        flex-direction: column !important;
        gap: 2px !important;
    }
    .leaflet-control-layers-expanded::before {
        content: "🗺️ Calques";
        display: block;
        font-weight: 700;
        font-size: 11px;
        color: #64748b;
        letter-spacing: .5px;
        text-transform: uppercase;
        margin-bottom: 8px;
        padding-bottom: 6px;
        border-bottom: 1px solid #e2e8f0;
    }
    </style>
    """
    carte.get_root().html.add_child(folium.Element(css_legende))

    return carte


# ==============================================================================
# APPLICATION PRINCIPALE
# ==============================================================================

def main():
    st.set_page_config(page_title="Vélo & Météo", page_icon="🚴‍♂️", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("""
    <div class="app-header">
      <h1>🚴‍♂️ Vélo &amp; Météo</h1>
      <p>Analysez votre tracé GPX : météo en temps réel, cols UCI, profil interactif et zones d'entraînement.</p>
    </div>""", unsafe_allow_html=True)

    # ── SIDEBAR ───────────────────────────────────────────────────────────────
    st.sidebar.header("⚙️ Paramètres")
    fichier   = st.sidebar.file_uploader("📂 Fichier GPX", type=["gpx"])
    st.sidebar.divider()
    date_dep  = st.sidebar.date_input("📅 Date de départ", value=date.today())
    heure_dep = st.sidebar.time_input("🕐 Heure de départ")
    vitesse   = st.sidebar.number_input("🚴 Vitesse moy. plat (km/h)", 5, 60, 25)
    st.sidebar.divider()
    mode = st.sidebar.radio("📊 Mode d'analyse",
                             ["⚡ Puissance", "🫀 Fréquence Cardiaque"], horizontal=True)
    if mode == "⚡ Puissance":
        ref_val = st.sidebar.number_input("⚡ FTP (W)", 50, 500, 220)
        fc_max  = None; ftp_fc = ref_val
        poids   = st.sidebar.number_input("⚖️ Poids cycliste + vélo (kg)", 40, 150, 75)
    else:
        ref_val = st.sidebar.number_input("❤️ FC max (bpm)", 100, 220, 185)
        fc_max  = ref_val
        ftp_fc  = st.sidebar.number_input("⚡ FTP estimé (W)", 50, 500, 220)
        poids   = st.sidebar.number_input("⚖️ Poids cycliste + vélo (kg)", 40, 150, 75)
    st.sidebar.divider()
    intervalle = st.sidebar.selectbox("⏱️ Intervalle checkpoints météo",
                    options=[5,10,15], index=1, format_func=lambda x: f"Toutes les {x} min")
    intervalle_sec = intervalle * 60

    # ── DÉTECTION DES MONTÉES ─────────────────────────────────────────────────
    st.sidebar.divider()
    with st.sidebar.expander("🏔️ Détection des montées", expanded=False):

        if "sensibilite" not in st.session_state:
            st.session_state.sensibilite = 3
        if "seuil_debut" not in st.session_state:
            st.session_state.seuil_debut = float(climbing_module.SEUIL_DEBUT)
        if "seuil_fin" not in st.session_state:
            st.session_state.seuil_fin = float(climbing_module.SEUIL_FIN)
        if "fusion_m" not in st.session_state:
            st.session_state.fusion_m = int(climbing_module.MAX_DESCENTE_FUSION_M)

        SENSIBILITE_LABELS = {
            1: "🔵 Strict — grands cols seulement",
            2: "🟢 Conservateur",
            3: "🟡 Équilibré (défaut)",
            4: "🟠 Sensible",
            5: "🔴 Maximum — toutes les côtes",
        }
        SENSIBILITE_PARAMS = {
            1: (4.0, 2.0,  20),
            2: (3.0, 1.5,  35),
            3: (2.0, 1.0,  50),
            4: (1.5, 0.5,  70),
            5: (0.5, 0.0, 100),
        }

        st.slider("🎚️ Sensibilité de détection", 1, 5, step=1,
            key="sensibilite",
            help="Bas = seulement les vraies montées. Haut = capte toutes les côtes.")
        niv = st.session_state.sensibilite
        st.caption(SENSIBILITE_LABELS[niv])

        if st.button("↺ Réinitialiser", width="stretch"):
            st.session_state["_reset_demande"] = True
            st.rerun()

        if st.session_state.pop("_reset_demande", False):
            st.session_state.pop("sensibilite", None)
            st.session_state.pop("seuil_debut", None)
            st.session_state.pop("seuil_fin", None)
            st.session_state.pop("fusion_m", None)
            st.session_state.pop("_last_sensibilite", None)
            st.rerun()

        with st.expander("⚙️ Réglages fins", expanded=False):
            st.caption("Synchronisés avec la sensibilité — modifiez pour affiner.")

            sd_sync, sf_sync, fm_sync = SENSIBILITE_PARAMS[niv]
            if st.session_state.get("_last_sensibilite") != niv:
                st.session_state.seuil_debut = sd_sync
                st.session_state.seuil_fin   = sf_sync
                st.session_state.fusion_m    = fm_sync
                st.session_state["_last_sensibilite"] = niv

            st.slider("Seuil de départ (%)", 0.5, 5.0, step=0.5,
                key="seuil_debut",
                help="Pente minimale pour démarrer une montée.")
            st.slider("Seuil de fin (%)", 0.0, 3.0, step=0.5,
                key="seuil_fin",
                help="Pente en dessous de laquelle la montée est terminée.")
            st.slider("Fusion (D− max, m)", 10, 200, step=10,
                key="fusion_m",
                help="Descente max pour fusionner deux runs en une seule montée.")

        climbing_module.SEUIL_DEBUT           = st.session_state.seuil_debut
        climbing_module.SEUIL_FIN             = st.session_state.seuil_fin
        climbing_module.MAX_DESCENTE_FUSION_M = st.session_state.fusion_m

    # ── OPTIONS AVANCÉES ──────────────────────────────────────────────────────
    st.sidebar.divider()
    with st.sidebar.expander("🔧 Options avancées", expanded=False):
        noms_osm = st.toggle("🗺️ Nommer les cols (OpenStreetMap)", value=False,
            help="Recherche le nom officiel de chaque col sur OpenStreetMap. "
                 "Peut être lent ou indisponible selon l'hébergement.")
        if noms_osm:
            st.sidebar.warning(
                "⚠️ Les serveurs Overpass sont souvent surchargés ou bloqués "
                "sur Streamlit Cloud. La recherche peut échouer ou être lente."
            )
        gemini_key = st.text_input(
            "🤖 Clé API Gemini",
            value="",
            type="password",
            help="Génère un résumé intelligent de ta sortie. "
                 "Clé gratuite sur aistudio.google.com."
        )

    ph_fuseau = st.sidebar.empty()
    ph_fuseau.info("🌍 Fuseau : en attente…")

    if fichier is None:
        st.info("👈 Importez un fichier GPX dans la barre latérale pour commencer l'analyse.")
        return

    # ── CHARGEMENT ────────────────────────────────────────────────────────────
    etapes = st.empty()
    with etapes.container():
        with st.spinner("📍 Lecture du fichier GPX…"):
            points_gpx = parser_gpx(fichier.read())
    if not points_gpx:
        st.error("❌ Fichier GPX vide ou corrompu."); return

    with etapes.container():
        with st.spinner("🌍 Fuseau horaire…"):
            fuseau = recuperer_fuseau(points_gpx[0].latitude, points_gpx[0].longitude)
    ph_fuseau.success(f"🌍 **{fuseau}**")
    date_depart = datetime.combine(date_dep, heure_dep)

    with etapes.container():
        with st.spinner("🌅 Lever/coucher du soleil…"):
            infos_soleil = recuperer_soleil(
                points_gpx[0].latitude, points_gpx[0].longitude,
                date_dep.strftime("%Y-%m-%d"))

    # ── CALCULS PARCOURS & VITESSE RÉELLE ────────────────────────────────────
    with etapes.container():
        with st.spinner("📐 Calcul du parcours…"):
            checkpoints = []; profil_data = []
            dist_tot = d_plus = d_moins = temps_s = prochain = cap = 0.0
            vms = (vitesse * 1000) / 3600
            for i in range(1, len(points_gpx)):
                p1, p2 = points_gpx[i-1], points_gpx[i]
                d  = p1.distance_2d(p2) or 0.0; dp = 0.0
                if p1.elevation is not None and p2.elevation is not None:
                    dif = p2.elevation - p1.elevation
                    if dif > 0: dp = dif; d_plus += dif
                    else: d_moins += abs(dif)
                dist_tot += d; temps_s += (d + dp * 10) / vms
                cap = calculer_cap(p1.latitude, p1.longitude, p2.latitude, p2.longitude)
                profil_data.append({"Distance (km)": round(dist_tot/1000, 3),
                                    "Altitude (m)": p2.elevation or 0})
                if temps_s >= prochain:
                    hp = date_depart + timedelta(seconds=temps_s)
                    checkpoints.append({
                        "lat": p2.latitude, "lon": p2.longitude, "Cap": cap,
                        "Heure": hp.strftime("%d/%m %H:%M"),
                        "Heure_API": hp.replace(minute=0, second=0).strftime("%Y-%m-%dT%H:00"),
                        "Km": round(dist_tot/1000, 1),
                        "Alt (m)": int(p2.elevation) if p2.elevation else 0,
                    })
                    prochain += intervalle_sec

    # Calcul de la vitesse moyenne globale (vitesse réelle avec dénivelé)
    if temps_s > 0:
        vit_moy_reelle = round((dist_tot / 1000) / (temps_s / 3600), 1)
    else:
        vit_moy_reelle = vitesse

    heure_arr = date_depart + timedelta(seconds=temps_s)
    pf = points_gpx[-1]
    checkpoints.append({
        "lat": pf.latitude, "lon": pf.longitude, "Cap": cap,
        "Heure": heure_arr.strftime("%d/%m %H:%M") + " 🏁",
        "Heure_API": heure_arr.replace(minute=0, second=0).strftime("%Y-%m-%dT%H:00"),
        "Km": round(dist_tot/1000, 1),
        "Alt (m)": int(pf.elevation) if pf.elevation else 0,
    })
    df_profil = pd.DataFrame(profil_data)

    # ── ASCENSIONS ────────────────────────────────────────────────────────────
    with etapes.container():
        with st.spinner("⛰️ Détection des ascensions…"):
            ascensions = detecter_ascensions(df_profil)

    if ascensions:
        dist_cum = 0.0
        pt_par_km = {} 
        for i in range(1, len(points_gpx)):
            p1, p2 = points_gpx[i-1], points_gpx[i]
            dist_cum += p1.distance_2d(p2) or 0.0
            km = round(dist_cum / 1000, 3)
            pt_par_km[km] = p2

        def coords_au_km(km_cible):
            if not pt_par_km:
                return None, None
            km_proche = min(pt_par_km.keys(), key=lambda k: abs(k - km_cible))
            pt = pt_par_km[km_proche]
            return pt.latitude, pt.longitude

        for asc in ascensions:
            lat_s, lon_s = coords_au_km(asc["_sommet_km"])
            lat_d, lon_d = coords_au_km(asc["_debut_km"])
            asc["_lat_sommet"] = lat_s
            asc["_lon_sommet"] = lon_s
            asc["_lat_debut"]  = lat_d
            asc["_lon_debut"]  = lon_d

    # ── NOMS OSM ──────────────────────────────────────────────────────────────
    if noms_osm and ascensions:
        with etapes.container():
            with st.spinner("🗺️ Recherche des noms de cols (OpenStreetMap)…"):
                ascensions = enrichir_cols(ascensions, points_gpx)

    for asc in ascensions:
        asc.setdefault("Nom", "—")
        asc.setdefault("Nom OSM alt", None)

    # ── MÉTÉO (AVEC MÉMOIRE LOCALE) ───────────────────────────────────────────
    with etapes.container():
        with st.spinner("📡 Récupération météo..."):
            frozen   = tuple((cp["lat"], cp["lon"], cp["Heure_API"]) for cp in checkpoints)
            is_past  = date_dep < date.today()
            rep_list = memoire_meteo(frozen, is_past=is_past, date_str=date_dep.strftime("%Y-%m-%d"))
                
    etapes.empty()

    resultats = []; err_meteo = rep_list is None
    if err_meteo:
        st.warning("⚠️ Météo indisponible. Open-Meteo vous a temporairement bloqué (Erreur 429). Patientez 2 minutes.")
        for cp in checkpoints:
            cp.update(Ciel="—", temp_val=None, Pluie="—", pluie_pct=None,
                      vent_val=None, rafales_val=None, Dir="—",
                      dir_deg=None, effet="—", ressenti=None)
            resultats.append(cp)
    else:
        for i, cp in enumerate(checkpoints):
            m = extraire_meteo(rep_list[i] if i < len(rep_list) else {}, cp["Heure_API"])
            if m["dir_deg"] is not None:
                m["effet"] = direction_vent_relative(cp["Cap"], m["dir_deg"])
            cp.update(m); resultats.append(cp)

    # ── SCORE + MÉTRIQUES ─────────────────────────────────────────────────────
    dh = int(temps_s // 3600); dm = int((temps_s % 3600) // 60)
    score    = calculer_score(resultats, ascensions, d_plus, vitesse, ref_val, mode, poids)
    calories = calculer_calories(max(1, poids - 10), temps_s, dist_tot, d_plus, vitesse)

    analyse_meteo = analyser_meteo_detaillee(resultats, dist_tot)

    for asc in ascensions:
        temps_jusqu_debut = (asc["_debut_km"] / vitesse) * 3600
        mins_col, vit_col = estimer_temps_col(
            asc["_sommet_km"] - asc["_debut_km"], asc["_pente_moy"], vitesse)
        heure_sommet = date_depart + timedelta(seconds=temps_jusqu_debut) + timedelta(minutes=mins_col)
        asc["Temps col"]      = f"{mins_col} min ({vit_col} km/h)"
        asc["Arrivée sommet"] = heure_sommet.strftime("%H:%M")

    # ── AFFICHAGE HAUT DE PAGE ──
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#1e3a5f,#1e40af);border-radius:12px;
                padding:16px 24px;color:white;margin:12px 0;
                display:flex;align-items:center;gap:0;flex-wrap:wrap">
      <div style="min-width:160px;padding-right:24px;border-right:1px solid rgba(255,255,255,0.25)">
        <div style="font-size:2.8rem;font-weight:900;line-height:1">{score['total']}<span style="font-size:1.2rem">/10</span></div>
        <div style="font-size:.95rem;font-weight:600;margin-top:2px">{score['label']}</div>
        <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">
          <span style="background:rgba(255,255,255,.2);border-radius:20px;padding:3px 10px;font-size:.75rem">🌤️ {score['score_meteo']}/6</span>
          <span style="background:rgba(255,255,255,.2);border-radius:20px;padding:3px 10px;font-size:.75rem">🏔️ {score['score_cols']}/4</span>
        </div>
      </div>
      <div style="display:flex;gap:0;flex:1;flex-wrap:wrap;padding-left:8px">
        <div style="flex:1;min-width:90px;text-align:center;padding:6px 12px;border-right:1px solid rgba(255,255,255,0.2)">
          <div style="font-size:1.9rem;font-weight:800">{round(dist_tot/1000,1)}</div>
          <div style="font-size:.9rem;color:rgba(255,255,255,0.85)">km</div>
          <div style="font-size:.75rem;color:rgba(255,255,255,0.6)">📏 Distance</div>
        </div>
        <div style="flex:1;min-width:90px;text-align:center;padding:6px 12px;border-right:1px solid rgba(255,255,255,0.2)">
          <div style="font-size:1.9rem;font-weight:800">{int(d_plus)}</div>
          <div style="font-size:.9rem;color:rgba(255,255,255,0.85)">m</div>
          <div style="font-size:.75rem;color:rgba(255,255,255,0.6)">⬆️ D+</div>
        </div>
        <div style="flex:1;min-width:90px;text-align:center;padding:6px 12px;border-right:1px solid rgba(255,255,255,0.2)">
          <div style="font-size:1.9rem;font-weight:800">{int(d_moins)}</div>
          <div style="font-size:.9rem;color:rgba(255,255,255,0.85)">m</div>
          <div style="font-size:.75rem;color:rgba(255,255,255,0.6)">⬇️ D−</div>
        </div>
        <div style="flex:1;min-width:90px;text-align:center;padding:6px 12px;border-right:1px solid rgba(255,255,255,0.2)">
          <div style="font-size:1.9rem;font-weight:800">{dh}h{dm:02d}</div>
          <div style="font-size:.9rem;color:rgba(255,255,255,0.85)">min</div>
          <div style="font-size:.75rem;color:rgba(255,255,255,0.6)">⏱️ Durée</div>
        </div>
        <div style="flex:1;min-width:110px;text-align:center;padding:6px 12px;border-right:1px solid rgba(255,255,255,0.2)">
          <div style="font-size:1.9rem;font-weight:800;color:#34d399">{vit_moy_reelle}</div>
          <div style="font-size:.9rem;color:rgba(255,255,255,0.85)">km/h</div>
          <div style="font-size:.75rem;color:rgba(255,255,255,0.6)">🚴 Moy. Réelle</div>
        </div>
        <div style="flex:1;min-width:90px;text-align:center;padding:6px 12px;border-right:1px solid rgba(255,255,255,0.2)">
          <div style="font-size:1.9rem;font-weight:800">{heure_arr.strftime('%H:%M')}</div>
          <div style="font-size:.9rem;color:rgba(255,255,255,0.85)">&nbsp;</div>
          <div style="font-size:.75rem;color:rgba(255,255,255,0.6)">🏁 Arrivée</div>
        </div>
        <div style="flex:1;min-width:90px;text-align:center;padding:6px 12px;border-left:1px solid rgba(255,255,255,0.2)">
          <div style="font-size:1.9rem;font-weight:800">{calories}</div>
          <div style="font-size:.9rem;color:rgba(255,255,255,0.85)">kcal</div>
          <div style="font-size:.75rem;color:rgba(255,255,255,0.6)">🔥 Calories</div>
        </div>
      </div>
    </div>""", unsafe_allow_html=True)

    # ── ONGLETS ───────────────────────────────────────────────────────────────
    tab_carte, tab_profil, tab_meteo, tab_cols, tab_detail, tab_analyse = st.tabs([
        "🗺️ Carte", "⛰️ Profil & Cols", "🌤️ Météo", "🏔️ Ascensions", "📋 Détail", "🤖 Coach IA"
    ])

    with tab_carte:
        if infos_soleil:
            ls = infos_soleil["lever"].strftime("%H:%M")
            cs = infos_soleil["coucher"].strftime("%H:%M")
            ds = infos_soleil["coucher"] - infos_soleil["lever"]
            hj, mj = int(ds.seconds // 3600), int((ds.seconds % 3600) // 60)
            st.markdown(f"""
            <div class="soleil-row">
              <span style="font-size:1.3rem">☀️</span>
              <div class="soleil-item"><div class="s-val">🌅 {ls}</div><div class="s-lbl">Lever (UTC)</div></div>
              <div class="soleil-item"><div class="s-val">🌇 {cs}</div><div class="s-lbl">Coucher (UTC)</div></div>
              <div class="soleil-item"><div class="s-val">{hj}h{mj:02d}m</div><div class="s-lbl">Durée du jour</div></div>
            </div>""", unsafe_allow_html=True)
            tz = infos_soleil["lever"].tzinfo
            if date_depart.replace(tzinfo=tz) < infos_soleil["lever"]:
                st.warning(f"⚠️ Départ avant le lever du soleil ({ls} UTC) — prévoyez un éclairage.")
            if heure_arr.replace(tzinfo=tz) > infos_soleil["coucher"]:
                st.warning(f"⚠️ Arrivée après le coucher ({cs} UTC) — prévoyez un éclairage.")
        FONDS_CARTE = {
            "🗺️ CartoDB Positron (épuré)": ("CartoDB positron", None),
            "🌍 OpenStreetMap (classique)": ("OpenStreetMap", None),
            "🏔️ OpenTopoMap (relief)": (
                "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
                "Map data © OpenStreetMap contributors, SRTM | Map style © OpenTopoMap (CC-BY-SA)",
            ),
        }
        fond_choisi = st.selectbox("🖼️ Fond de carte", options=list(FONDS_CARTE.keys()), index=0)
        tiles, attr = FONDS_CARTE[fond_choisi]
        carte = creer_carte(points_gpx, resultats, ascensions, tiles, attr)
        st_folium(carte, width="100%", height=700, returned_objects=[])
        st.divider()
        
        # BOUTON D'EXPORT MAGIQUE
        if st.button("📤 Télécharger le Carnet de Route (HTML / PDF)", width="stretch"):
            with st.spinner("Génération du fichier interactif en cours..."):
                briefing_actuel = st.session_state.get("briefing_ia", None)
                
                # Création d'une carte TOUTE NEUVE pour l'export (évite le bug de superposition de Streamlit)
                carte_export = creer_carte(points_gpx, resultats, ascensions, tiles, attr)

                html_bytes = generer_html_resume(
                    score, ascensions, resultats, dist_tot, d_plus, d_moins, temps_s, 
                    date_depart, heure_arr, vitesse, vit_moy_reelle, calories, 
                    carte_export, df_profil, ref_val, mode, poids, briefing_ia=briefing_actuel
                )
                    
                nom_f = f"Roadbook_{date_dep.strftime('%Y%m%d')}.html"
                b64   = base64.b64encode(html_bytes).decode()
                st.markdown(
                    f'<a href="data:text/html;base64,{b64}" download="{nom_f}" '
                    f'style="display:block;text-align:center;background:#1e40af;color:white;'
                    f'padding:10px;border-radius:8px;text-decoration:none;font-weight:600;margin-top:8px">'
                    f'⬇️ Télécharger {nom_f}</a>', unsafe_allow_html=True)
                st.success("✅ Fichier prêt ! Ouvrez-le et cliquez sur le bouton bleu 'Enregistrer en PDF' situé en haut de la page.")

    with tab_profil:
        lbl_mode = "FTP" if mode == "⚡ Puissance" else "FC max"
        st.caption(f"Segments colorés selon les zones {lbl_mode}.")
        idx_survol = None
        if ascensions:
            noms_liste = ["(toutes les côtes)"] + [
                f"{a.get('Nom','') + ' — ' if a.get('Nom','—') != '—' else ''}"
                f"{a['Catégorie']} — Km {a['Départ (km)']}→{a['Sommet (km)']} ({a['Longueur']})"
                for a in ascensions]
            choix = st.selectbox("🔍 Mettre en avant :", options=noms_liste, index=0)
            if choix != "(toutes les côtes)":
                idx_survol = noms_liste.index(choix) - 1
        if not df_profil.empty:
            st.plotly_chart(
                creer_figure_profil(df_profil, ascensions, vitesse, ref_val, mode, poids, idx_survol),
                width='stretch')
        st.markdown(f"**Zones d'entraînement ({lbl_mode}) :**")
        cols_z = st.columns(6)
        for j, (_, _, num, lbl, coul) in enumerate(zones_actives(mode)):
            cols_z[j].markdown(
                f'<div style="background:{coul};color:white;border-radius:6px;'
                f'padding:6px;text-align:center;font-size:.72rem"><b>{lbl}</b></div>',
                unsafe_allow_html=True)

    with tab_meteo:
        if err_meteo:
            st.warning("⚠️ Données météo indisponibles.")
        else:
            st.caption("Température · Vent & Rafales · Probabilité de pluie.")
            st.plotly_chart(creer_figure_meteo(resultats), width='stretch')
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Température** — 🟣 <5° · 🔵 5–15° · 🟢 15–22° (idéal) · 🟠 22–30° · 🔴 >30°C")
            with c2:
                st.markdown("**Vent** — 🟢 <10 · 🟡 10–25 · 🟠 25–40 · 🔴 >40 km/h | **Pluie** — clair→foncé")

            if analyse_meteo:
                st.divider()
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**💨 Répartition du vent**")
                    def barre(pct, couleur, label, emoji):
                        st.markdown(f"""
                        <div style="margin-bottom:8px">
                            <div style="display:flex;justify-content:space-between;font-size:.85rem;margin-bottom:3px">
                                <span>{emoji} {label}</span>
                                <span style="font-weight:700">{pct}%</span>
                            </div>
                            <div style="background:#e2e8f0;border-radius:4px;height:8px">
                                <div style="background:{couleur};width:{pct}%;height:8px;border-radius:4px"></div>
                            </div>
                        </div>""", unsafe_allow_html=True)
                    barre(analyse_meteo["pct_face"], "#ef4444", "Face", "⬇️")
                    barre(analyse_meteo["pct_cote"], "#eab308", "Côté", "↔️")
                    barre(analyse_meteo["pct_dos"],  "#22c55e", "Dos",  "⬆️")
                    if analyse_meteo["segments_face"]:
                        st.caption("Segments avec vent de face :")
                        for d, f in analyse_meteo["segments_face"]:
                            st.caption(f"  • Km {d:.0f} → {f:.0f} ({f-d:.0f} km)")
                with c2:
                    st.markdown("**🌧️ Risque de pluie**")
                    pp = analyse_meteo["pct_pluie"]
                    couleur_pp = "#ef4444" if pp > 60 else "#f97316" if pp > 30 else "#22c55e"
                    st.markdown(f"""
                    <div style="text-align:center;padding:16px;background:#f8fafc;
                                border-radius:10px;margin-bottom:12px">
                        <div style="font-size:2.5rem;font-weight:900;color:{couleur_pp}">{pp}%</div>
                        <div style="font-size:.85rem;color:#64748b">du parcours avec risque > 50%</div>
                    </div>""", unsafe_allow_html=True)
                    if analyse_meteo["premier_pluie"]:
                        cp_p = analyse_meteo["premier_pluie"]
                        st.markdown(f"""
                        <div style="background:#fef3c7;border-radius:8px;padding:10px 14px;font-size:.85rem">
                            🕐 Premier risque à <b>{cp_p['Heure']}</b> — Km {cp_p['Km']}<br>
                            Probabilité : <b>{cp_p.get('pluie_pct','?')}%</b>
                        </div>""", unsafe_allow_html=True)
                    else:
                        st.markdown("""
                        <div style="background:#dcfce7;border-radius:8px;padding:10px 14px;font-size:.85rem">
                            ✅ Aucun risque de pluie significatif sur le parcours
                        </div>""", unsafe_allow_html=True)

    with tab_cols:
        st.caption(LEGENDE_UCI)
        if ascensions:
            for a in ascensions:
                w   = estimer_watts(a["_pente_moy"], vitesse, poids)
                _, zlbl, _ = get_zone(w, ref_val, zones_actives(mode))
                pct = round(w / ref_val * 100) if ref_val > 0 else 0
                a["Puissance"]  = f"{w} W"
                fc_est = estimer_fc(w, ftp_fc, ref_val)
                a["Effort val"] = (f"{pct}% FTP" if mode == "⚡ Puissance"
                                   else f"~{fc_est} bpm" if fc_est else "—")
                a["Zone"]   = zlbl
                a["Effort"] = ("🔴 Max" if pct>105 else "🟠 Très dur" if pct>95
                               else "🟡 Difficile" if pct>80 else "🟢 Modéré" if pct>60
                               else "🔵 Endurance")
            cols_aff = ["Catégorie","Nom","Départ (km)","Sommet (km)","Longueur",
                        "Dénivelé","Pente moy.","Pente max","Alt. sommet",
                        "Score UCI","Temps col","Arrivée sommet","Puissance","Effort val","Zone","Effort"]
            st.dataframe(pd.DataFrame(ascensions)[cols_aff],
                width='stretch', hide_index=True,
                column_config={
                    "Nom":            st.column_config.TextColumn("🏔️ Nom OSM"),
                    "Effort val":     st.column_config.TextColumn("% FTP" if mode=="⚡ Puissance" else "FC estimée"),
                    "Temps col":      st.column_config.TextColumn("⏱️ Temps col"),
                    "Arrivée sommet": st.column_config.TextColumn("🏁 Arrivée sommet"),
                    "Zone":           st.column_config.TextColumn("Zone"),
                    "Effort":         st.column_config.TextColumn("Effort"),
                })
            st.divider()
            st.subheader("🔍 Profil détaillé d'une montée")
            noms_cols = [
                f"{a.get('Nom','') + ' — ' if a.get('Nom','—') != '—' else ''}"
                f"{a['Catégorie']} — Km {a['Départ (km)']}→{a['Sommet (km)']} ({a['Longueur']}, {a['Dénivelé']})"
                for a in ascensions]
            col_choix = st.selectbox("Choisir une montée :", options=noms_cols, index=0)
            asc_sel   = ascensions[noms_cols.index(col_choix)]
            dk_sel    = asc_sel["_sommet_km"] - asc_sel["_debut_km"]
            seg_defaut = 0.5 if dk_sel < 5 else 1.0 if dk_sel < 15 else 2.0
            col_ctrl1, col_ctrl2 = st.columns([3, 1])
            with col_ctrl1:
                seg_km = st.slider("Longueur des segments (km)", 0.25,
                                   min(5.0, dk_sel / 2), float(seg_defaut), 0.25)
            with col_ctrl2:
                nb_segs = max(2, int(dk_sel / seg_km))
                st.metric("Segments", nb_segs)
            if not df_profil.empty:
                fig_col = creer_figure_col(df_profil, asc_sel, nb_segments=nb_segs)
                if fig_col:
                    st.plotly_chart(fig_col, width='stretch')
                st.markdown("**Intensité de pente :** 🟢 <3% · 🟡 3–6% · 🟠 6–8% · 🔴 8–12% · 🟤 >12%")
        else:
            st.success("🚴‍♂️ Aucune difficulté catégorisée — parcours roulant !")

    with tab_detail:
        st.caption(f"Un point toutes les **{intervalle} min**. Wind Chill si temp ≤ 10°C et vent > 4.8 km/h.")
        lignes = []
        for cp in resultats:
            t = cp.get("temp_val")
            v = cp.get("vent_val")
            rg = cp.get("rafales_val")
            lignes.append({
                "Heure": cp["Heure"], "Km": cp["Km"], "Alt (m)": cp["Alt (m)"],
                "Ciel": cp.get("Ciel","—"),
                "Temp (°C)": f"{t}°C" if t is not None else "—",
                "Ressenti": label_wind_chill(cp.get("ressenti")),
                "Pluie": cp.get("Pluie","—"),
                "Vent (km/h)": f"{v} km/h" if v is not None else "—",
                "Rafales": f"{rg} km/h" if rg is not None else "—",
                "Direction": cp.get("Dir","—"),
                "Effet vent": cp.get("effet","—"),
            })
        st.dataframe(pd.DataFrame(lignes), width='stretch', hide_index=True,
            column_config={
                "Heure":       st.column_config.TextColumn("🕐 Heure"),
                "Km":          st.column_config.NumberColumn("📏 Km"),
                "Alt (m)":     st.column_config.NumberColumn("⛰️ Alt"),
                "Ciel":        st.column_config.TextColumn("🌤️ Ciel"),
                "Temp (°C)":   st.column_config.TextColumn("🌡️ Temp"),
                "Ressenti":    st.column_config.TextColumn("🥶 Ressenti"),
                "Pluie":       st.column_config.TextColumn("🌧️ Pluie"),
                "Vent (km/h)": st.column_config.TextColumn("💨 Vent"),
                "Rafales":     st.column_config.TextColumn("🌬️ Rafales"),
                "Direction":   st.column_config.TextColumn("🧭 Direction"),
                "Effet vent":  st.column_config.TextColumn("🚴 Effet"),
            })

    # ── ANALYSE IA ───────────────────────────────────────────────────────────
    with tab_analyse:
        st.subheader("🎙️ Le Briefing du Pote de Sortie")
        st.markdown("Obtenez une analyse personnalisée générée par l'Intelligence Artificielle de Google (Gemini) : infos météo, gestion de l'effort, équipement conseillé et calcul de votre ravitaillement.")
        
        if not gemini_key:
            st.info("👈 **Pour activer l'analyse**, entrez votre clé API Gemini dans le menu '🔧 Options avancées' situé dans la barre latérale gauche.")
        else:
            if "briefing_ia" not in st.session_state:
                st.session_state.briefing_ia = None

            if st.button("💬 Générer ou Actualiser le briefing", width='stretch'):
                with st.spinner("Analyse du parcours et préparation des conseils en cours..."):
                    try:
                        jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
                        mois_fr = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
                        delta_jours = (date_dep - date.today()).days
                        
                        if delta_jours == 0:
                            contexte_date = "Aujourd'hui"
                        elif delta_jours == 1:
                            contexte_date = "Demain"
                        else:
                            contexte_date = f"le {jours_fr[date_dep.weekday()]} {date_dep.day} {mois_fr[date_dep.month]} {date_dep.year}"

                        # On passe la VITESSE RÉELLE calculée à l'IA
                        briefing = generer_briefing(
                            api_key=gemini_key, 
                            dist_tot=dist_tot, 
                            d_plus=d_plus, 
                            temps_s=temps_s,
                            calories=calories,
                            score=score, 
                            ascensions=ascensions, 
                            analyse_meteo=analyse_meteo,
                            resultats=resultats,
                            heure_depart=heure_dep.strftime('%H:%M'),
                            heure_arrivee=heure_arr.strftime('%H:%M'),
                            vitesse_moyenne=vit_moy_reelle,
                            infos_soleil=infos_soleil,
                            contexte_date=contexte_date
                        )
                        if briefing:
                            st.session_state.briefing_ia = briefing
                    except Exception as e:
                        st.error(f"❌ Erreur lors de la communication avec l'API Gemini. (Détail: {e})")

            if st.session_state.briefing_ia:
                st.success("✅ Briefing prêt !")
                st.markdown(f"""
                <div style="background-color:#f8fafc; padding:25px; border-radius:12px; border-left:6px solid #22c55e; color:#1e293b; font-size:1.05rem; line-height:1.6; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
                    {st.session_state.briefing_ia}
                </div>
                """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
