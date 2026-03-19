"""
gemini_coach.py
===============
Module dédié à l'Intelligence Artificielle (Google Gemini).
Génère le briefing ultime : Pacing, Nutrition (+rab), Chaleur, Crème solaire et Date !
"""

import google.generativeai as genai
import logging

logger = logging.getLogger(__name__)

def generer_briefing(api_key: str, dist_tot: float, d_plus: float, temps_s: float, calories: int,
                     score: dict, ascensions: list, analyse_meteo: dict, resultats: list,
                     heure_depart: str, heure_arrivee: str, vitesse_moyenne: float, 
                     infos_soleil: dict, contexte_date: str) -> str | None:
    """
    Envoie les données du parcours à Gemini pour obtenir un briefing tactique et pratique.
    """
    if not api_key:
        return None

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')

        # ── PRÉPARATION DES DONNÉES ──
        dist_km = round(dist_tot / 1000, 1)
        d_plus_m = int(d_plus)
        duree_h = round(temps_s / 3600, 1)

        # Soleil
        lever_str = infos_soleil["lever"].strftime("%H:%M") if infos_soleil else "inconnue"
        coucher_str = infos_soleil["coucher"].strftime("%H:%M") if infos_soleil else "inconnue"

        if ascensions:
            cols_str = "\n".join([
                f"- {a.get('Nom', a['Catégorie'])} (Départ: Km {a['Départ (km)']}, Longueur: {a['Longueur']}, Pente: {a['Pente moy.']})" 
                for a in ascensions
            ])
        else:
            cols_str = "Parcours roulant, aucune ascension majeure catégorisée."

        # Températures et Ressenti (Wind Chill)
        valides = [cp for cp in resultats if cp.get("temp_val") is not None]
        if valides:
            t_min = min(cp["temp_val"] for cp in valides)
            t_max = max(cp["temp_val"] for cp in valides)
            temp_txt = f"Entre {t_min}°C et {t_max}°C."
            
            ressentis = [cp["ressenti"] for cp in valides if cp.get("ressenti") is not None]
            if ressentis:
                r_min = min(ressentis)
                r_max = max(ressentis)
                ressenti_txt = f"Ressenti entre {r_min}°C et {r_max}°C avec le vent."
            else:
                ressenti_txt = "Similaire à la température réelle."
        else:
            temp_txt = "Inconnue."
            ressenti_txt = "Inconnue."

        meteo_txt = "Données météo du vent non disponibles."
        pluie_detail = "Pas de données sur la pluie."
        
        if analyse_meteo:
            meteo_txt = (
                f"Face {analyse_meteo['pct_face']}%, "
                f"Dos {analyse_meteo['pct_dos']}%, Côté {analyse_meteo['pct_cote']}%."
            )
            
            if analyse_meteo.get('premier_pluie'):
                cp = analyse_meteo['premier_pluie']
                pluie_detail = f"OUI. Risque de {cp.get('pluie_pct')}% attendu vers {cp['Heure']}, exactement au kilomètre {cp['Km']}."
            else:
                pluie_detail = "NON. Aucun risque de pluie majeur (>50%) prévu."

        # ── LE PROMPT (La consigne donnée à l'IA) ──
        prompt = f"""
        Tu es un compagnon de route cycliste expérimenté, sympa et très motivant. Tu n'es PAS un coach pro ultra-strict, mais plutôt un super pote de club de vélo qui donne d'excellents conseils pratiques. Tu tutoies le cycliste.

        Voici les données exactes de sa sortie :
        - Date de la sortie : {contexte_date}
        - Distance : {dist_km} km
        - Dénivelé positif : {d_plus_m} m
        - Heure de départ : {heure_depart}
        - Heure d'arrivée estimée : {heure_arrivee}
        - Vitesse moyenne globale estimée : {vitesse_moyenne} km/h
        - Durée de pédalage : {duree_h} heures
        - Dépense énergétique estimée : {calories} kcal
        - Températures prévues : {temp_txt}
        - Température ressentie (Wind Chill) : {ressenti_txt}
        - Horaires du soleil : Lever à {lever_str}, Coucher à {coucher_str}
        - Difficulté globale : {score['label']}
        - Liste des ascensions :
        {cols_str}
        - Résumé du vent : {meteo_txt}
        - Alerte Pluie précise : {pluie_detail}

        Rédige un briefing clair, amical et structuré qui respecte STRICTEMENT ce plan :

        **1. Le Programme du {contexte_date} 🗺️**
        Fais un récapitulatif sympa du parcours (distance, D+, heures de départ/arrivée et vitesse moyenne). Adapte ton introduction selon si c'est aujourd'hui, demain ou un autre jour. En te basant sur le nom des ascensions, essaie de deviner la région ou le massif traversé pour donner un côté "local" (si tu ne trouves pas, ne dis rien).

        **2. Météo, Chaleur & Équipement 🌤️👕**
        Fais un point global : 
        - Pluie : Donne l'heure et le kilomètre exacts de la pluie s'il y a un risque. Sinon rassure-le.
        - Alerte Forte Chaleur 🥵 : Si la température maximale dépasse 30°C, tire la sonnette d'alarme ! Dis-lui de s'arroser régulièrement la nuque, d'ouvrir le maillot dans les ascensions et de baisser son rythme cardiaque. 
        - Vent & Froid : Résume la situation du vent. Si la température ressentie est plus basse que la température réelle à cause du vent, alerte-le pour qu'il s'habille en conséquence !
        - Tenue & Matos : Conseille la tenue idéale. Rappelle le kit de réparation. Si la température maximale dépasse les 18°C et qu'il roule de jour, rappelle-lui la crème solaire. Si son départ/arrivée frôle la nuit, rappelle les lampes.

        **3. Gestion de l'Effort (Le Pacing) ⚡**
        Analyse le parcours chronologiquement. Dis-lui EXACTEMENT à quel moment il doit "gérer" (ex: vent de face, approche d'un grand col) et à quel moment il peut "forcer" (ex: vent de dos, replat). Cite les ascensions pour rythmer l'effort.

        **4. Le Ravito (Dans les poches !) 🍌💧**
        Calcule ce qu'il doit emporter pour {duree_h} heures :
        - Eau : 0.5 à 0.6 L par heure. ATTENTION : si la température maximale dépasse les 25°C, dis-lui de passer à 1 gourde pleine par heure et de rajouter des électrolytes (ou une pincée de sel) !
        - Solide : Compte 1 barre d'amande de 25g ET 1 gourde de compote "Pom'Pote" par heure, PUIS ajoute une marge de sécurité vitale de 2 barres et 1 compote au total. 
        Donne-lui les totaux précis à préparer.

        **5. Le mot de la fin 💡**
        Termine par un petit mot d'encouragement sympa pour le chauffer à bloc !
        """
        
        response = model.generate_content(prompt)
        return response.text

    except Exception as e:
        logger.error(f"Erreur lors de la génération Gemini : {e}")
        raise e
