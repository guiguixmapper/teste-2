"""
gemini_coach.py
===============
Module IA — génère un briefing cycliste complet via Google Gemini.
"""

import google.generativeai as genai
import logging

logger = logging.getLogger(__name__)


def generer_briefing(
    api_key:         str,
    dist_tot:        float,
    d_plus:          float,
    temps_s:         float,
    calories:        int,
    score:           dict,
    ascensions:      list,
    analyse_meteo:   dict,
    resultats:       list,
    heure_depart:    str,
    heure_arrivee:   str,
    vitesse_moyenne: float,
    infos_soleil:    dict,
    contexte_date:   str,
    nb_points_eau:   int  = 0,
    uv_pollen:       dict = None,
) -> str | None:
    if not api_key:
        return None

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        dist_km  = round(dist_tot / 1000, 1)
        d_plus_m = int(d_plus)
        duree_h  = round(temps_s / 3600, 2)
        dh       = int(duree_h)
        dm       = int((duree_h % 1) * 60)

        lever_str   = infos_soleil["lever"].strftime("%H:%M")   if infos_soleil else "inconnue"
        coucher_str = infos_soleil["coucher"].strftime("%H:%M") if infos_soleil else "inconnue"

        if ascensions:
            cols_str = "\n".join([
                f"  • {a.get('Nom','—')} ({a['Catégorie']}) — "
                f"Km {a['Départ (km)']}→{a['Sommet (km)']}, "
                f"{a['Longueur']}, D+ {a['Dénivelé']}, "
                f"pente moy. {a['Pente moy.']}, max {a['Pente max']}, "
                f"sommet {a.get('Alt. sommet','?')}, "
                f"arrivée sommet vers {a.get('Arrivée sommet','?')}"
                for a in ascensions
            ])
        else:
            cols_str = "  Aucune ascension catégorisée — parcours principalement roulant."

        valides = [cp for cp in resultats if cp.get("temp_val") is not None]
        if valides:
            t_min = min(cp["temp_val"] for cp in valides)
            t_max = max(cp["temp_val"] for cp in valides)
            t_moy = round(sum(cp["temp_val"] for cp in valides) / len(valides), 1)
            temp_txt = f"{t_min}°C min / {t_moy}°C moy / {t_max}°C max"
            ressentis = [cp["ressenti"] for cp in valides if cp.get("ressenti") is not None]
            ressenti_txt = (f"Wind chill : {min(ressentis)}°C à {max(ressentis)}°C"
                            if ressentis else "Pas de wind chill significatif")
        else:
            t_min = t_max = t_moy = None
            temp_txt = ressenti_txt = "Données indisponibles"

        if analyse_meteo:
            pct_face = analyse_meteo['pct_face']
            pct_dos  = analyse_meteo['pct_dos']
            pct_cote = analyse_meteo['pct_cote']
            vent_txt = f"{pct_face}% face / {pct_dos}% dos / {pct_cote}% côté"
            segs = analyse_meteo.get("segments_face", [])
            if segs:
                vent_txt += " — segments face : " + ", ".join(f"Km {s[0]}→{s[1]}" for s in segs)
            if analyse_meteo.get("premier_pluie"):
                cp_p = analyse_meteo["premier_pluie"]
                pluie_txt = f"RISQUE à {cp_p['Heure']} (Km {cp_p['Km']}, {cp_p.get('pluie_pct','?')}%)"
            else:
                pluie_txt = "Aucun risque >50% prévu"
        else:
            vent_txt = pluie_txt = "Indisponible"

        vents   = [cp.get("vent_val") for cp in valides if cp.get("vent_val") is not None]
        vent_max = max(vents) if vents else 0

        if uv_pollen:
            uv_txt    = uv_pollen.get("uv_label", "Inconnu")
            uv_max_val = uv_pollen.get("uv_max")
            pollen_txt = ", ".join(uv_pollen.get("pollens", [])) or "Aucune alerte"
        else:
            uv_txt = pollen_txt = "Indisponible"
            uv_max_val = None

        eau_txt = (f"{nb_points_eau} point(s) d'eau sur le tracé (OSM)"
                   if nb_points_eau > 0
                   else "Aucun point d'eau identifié — prévoir toute l'autonomie")

        if t_max is not None and t_max >= 25:
            eau_h = 1.0; eau_conseil = "1 bidon/heure + électrolytes (chaleur)"
        elif t_max is not None and t_max >= 15:
            eau_h = 0.7; eau_conseil = "700 ml/heure"
        else:
            eau_h = 0.5; eau_conseil = "500 ml/heure"
        eau_total = round(eau_h * duree_h, 1)

        carbs_h = 70 if (d_plus_m > 1500 or duree_h > 4) else 60
        carbs_total = int(carbs_h * duree_h)
        nb_barres = round(carbs_total / 40)
        nb_gels   = round(carbs_total / 25)

        prompt = f"""
Tu es un directeur sportif cycliste expert. Tu tutoies le coureur.
Sois précis, concret et chiffré. N'utilise que les données fournies.
Ne répète jamais la même info dans deux sections différentes.
Évite les formules creuses et les encouragements vagues.

═══════════════════════════════════════════════
DONNÉES DE LA SORTIE
═══════════════════════════════════════════════
Date         : {contexte_date}
Distance     : {dist_km} km  |  D+ : {d_plus_m} m
Durée est.   : {dh}h{dm:02d}  |  Départ : {heure_depart}  |  Arrivée : {heure_arrivee}
Vitesse moy. : {vitesse_moyenne} km/h  |  Calories : {calories} kcal
Score        : {score['label']} ({score['total']}/10)

ASCENSIONS
{cols_str}

MÉTÉO
Températures : {temp_txt}
Ressenti     : {ressenti_txt}
Vent         : {vent_txt}  (max {vent_max} km/h)
Pluie        : {pluie_txt}
UV           : {uv_txt}
Pollen       : {pollen_txt}
Lever/Coucher: {lever_str} / {coucher_str}

LOGISTIQUE
Points d'eau : {eau_txt}
Eau calculée : {eau_total} L ({eau_conseil})
Glucides     : {carbs_total} g ({carbs_h}g/h) → {nb_barres} barres (40g) ou {nb_gels} gels (25g)

═══════════════════════════════════════════════
BRIEFING — RESPECTE EXACTEMENT CETTE STRUCTURE
═══════════════════════════════════════════════

## 📋 Résumé
3 phrases max. Distance, D+, durée, départ/arrivée, niveau de difficulté.
Si les noms de cols évoquent un massif ou une région identifiable, cite-le.

---

## 🌤️ Météo & Équipement

**Conditions du jour**
Synthèse temp + vent en 2 phrases.

**Tenue**
Sois très précis : liste chaque pièce vestimentaire adaptée à t_min={t_min}°C au départ.
Mentionne si les descentes nécessitent un coupe-vent (haute altitude ou vent fort).

**Alertes**
- Pluie : {pluie_txt}. Conduite à tenir si ça arrive.
- UV {uv_txt} : crème solaire SPF adapté si UV ≥ 3, renouvellement toutes les 2h.
- Pollen {pollen_txt} : conseils si alerte active.
- Éclairage : si départ avant {lever_str} ou arrivée après {coucher_str}.
- Wind chill : {ressenti_txt} — alerte si <5°C.

---

## ⚡ Plan de course

Décompose en phases avec les kilomètres et heures estimées.
Pour chaque phase indique : niveau d'effort, raison (vent/pente/chaleur), conseil tactique.
Pour chaque ascension : heure d'attaque estimée, stratégie de montée, gestion de la descente.
Identifie les 2 moments où il peut "appuyer" et les 2 moments où il doit "lever le pied".

---

## 🍌 Ravitaillement

**Eau** : {eau_total} L — {eau_conseil}
{"⚠️ Électrolytes obligatoires (chaleur)." if t_max is not None and t_max >= 25 else ""}
{eau_txt}
Si points d'eau disponibles : stratégie de remplissage aux km précis.

**Énergie** : {carbs_total} g de glucides sur {dh}h{dm:02d}
Option A : {nb_barres} barres énergétiques (40g gl. chacune)
Option B : {nb_gels} gels (25g) + 1-2 bananes pour l'apport solide
Conseil : solide en 1ère moitié, gel/liquide en 2ème moitié.
Rythme : 1 prise toutes les 30 min dès la 1ère heure.

---

## ✅ Les 3 priorités de cette sortie

Exactement 3 points. Chacun doit être directement lié aux données ci-dessus.
Format : **[Thème]** — action concrète et chiffrée.
"""

        response = model.generate_content(prompt)
        return response.text

    except Exception as e:
        logger.error(f"Erreur Gemini : {e}")
        raise e
