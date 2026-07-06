"""
Brief du jour par section : pour chaque categorie activee dans
config/briefs.yaml, un appel LLM synthetise les articles retenus en un court
edito (ce qui se passe, les debats, comment le lire avec du recul), affiche
au-dessus de la section dans le digest.
"""

import json
import logging
import os
import time
from pathlib import Path

import yaml
from groq import Groq

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
BRIEFS_PATH = PROJECT_ROOT / "config" / "briefs.yaml"
PROMPTS_PATH = PROJECT_ROOT / "config" / "prompts.yaml"

# Meme modele que les resumes (surchargeable)
MODEL = os.environ.get("BRIEF_MODEL", os.environ.get("SUMMARIZER_MODEL", "openai/gpt-oss-120b"))
MAX_RETRIES = 2
RETRY_DELAY = 5


def load_briefs_config() -> dict:
    try:
        with open(BRIEFS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("briefs", {}) or {}
    except FileNotFoundError:
        return {}


def get_client() -> Groq:
    import httpx

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set")
    verify = os.environ.get("INSECURE_SSL") != "1"
    return Groq(api_key=api_key, http_client=httpx.Client(verify=verify))


def load_user_profile() -> str:
    with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("user_profile", "")


def build_system_prompt(theme_name: str, preprompt: str) -> str:
    custom = (
        f"\nCONSIGNES SPECIFIQUES POUR CETTE SECTION (prioritaires sur la structure par defaut) :\n{preprompt.strip()}\n"
        if preprompt and preprompt.strip()
        else ""
    )
    return f"""Tu es le redacteur en chef d'une revue de presse personnelle. On te donne les publications du jour retenues pour la section "{theme_name}".
{custom}
Redige le brief du jour EN FRANCAIS, en 2 a 3 paragraphes - aussi long que le contenu du jour le justifie, et toujours mene jusqu'au bout (jamais de phrase coupee) :
1. Ce qui se passe en ce moment : les sujets recurrents, les faits marquants.
2. Les points de friction ou de debat entre ces sources, ou les mouvements qui comptent.
3. Comment lire tout ca avec du recul : ce qu'il faut retenir, ce qui est du bruit.

Contraintes de ton : sobre, precis, sans emphase. Pas de points d'exclamation, pas d'emoji. Nomme les auteurs, medias ou institutions quand tu t'appuies sur un element precis - ne fais JAMAIS reference a des numeros d'articles ("l'article 3") : le lecteur ne les voit pas.

Reponds UNIQUEMENT en JSON valide : {{"editorial": "<le brief, paragraphes separes par \\n\\n>"}}"""


def write_brief(client: Groq, theme_name: str, preprompt: str, profile: str, articles: list[dict]) -> str | None:
    if not articles:
        return None

    corpus = "\n".join(
        f"--- Element {i} ---\nSource: {a.get('source', '')}\nTitre: {a.get('title', '')}\n"
        f"Contenu: {(a.get('content') or a.get('summary') or '')[:1500]}\n"
        for i, a in enumerate(articles)
    )
    user = (
        f"Profil du lecteur (pour calibrer le niveau de detail) :\n{profile}\n\n"
        f"Les elements du jour :\n\n{corpus}"
    )

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": build_system_prompt(theme_name, preprompt)},
                    {"role": "user", "content": user},
                ],
                temperature=0.4,
                max_tokens=2500,
                response_format={"type": "json_object"},
            )
            result = json.loads(response.choices[0].message.content)
            text = result.get("editorial", "") if isinstance(result, dict) else ""
            text = text.strip() if isinstance(text, str) else ""
            return text or None
        except Exception as e:
            logger.warning(f"Brief '{theme_name}' tentative {attempt + 1}/{MAX_RETRIES} echouee: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
    return None


def run(articles: list[dict]) -> list[dict]:
    """Retourne [{key, name, text}] pour chaque categorie activee dans briefs.yaml."""
    briefs_config = load_briefs_config()
    enabled = {k: v for k, v in briefs_config.items() if (v or {}).get("enabled")}
    if not enabled:
        logger.info("Aucun brief de section active (config/briefs.yaml)")
        return []

    client = get_client()
    profile = load_user_profile()
    editorials = []

    for cat_key, settings in enabled.items():
        cat_articles = [a for a in articles if a.get("category") == cat_key]
        if not cat_articles:
            continue
        theme_name = cat_articles[0].get("category_name", cat_key)
        logger.info(f"Brief de section : {theme_name} ({len(cat_articles)} articles)")
        text = write_brief(client, theme_name, settings.get("preprompt", ""), profile, cat_articles)
        if text:
            editorials.append({"key": cat_key, "name": theme_name, "text": text})

    logger.info(f"{len(editorials)} brief(s) de section generes")
    return editorials
