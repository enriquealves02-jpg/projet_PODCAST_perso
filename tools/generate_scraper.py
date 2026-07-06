# -*- coding: utf-8 -*-
"""
Generation d'un scraper par IA (Groq) pour un site SANS flux RSS.

Usage :
    python tools/generate_scraper.py <url_page_liste> <nom_du_site> <categorie>

Exemple :
    python tools/generate_scraper.py https://www.site.com/articles "Le Site" cinema

Deroulement :
1. Telecharge la page de liste du site
2. Demande au LLM (Groq) une config DECLARATIVE de selecteurs CSS - jamais de code
3. Teste la config immediatement (vrai scraping, apercu des articles)
4. Si echec, retente en donnant l'erreur au LLM (3 tentatives)
5. Si tu valides l'apercu, la config est enregistree dans
   config/custom_scrapers.yaml : elle est utilisee par tous les digests suivants.
"""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests
import yaml
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

if os.environ.get("INSECURE_SSL") == "1":
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context

from src.scraper_engine import HEADERS, VERIFY_SSL, test_config

CUSTOM_SCRAPERS_PATH = PROJECT_ROOT / "config" / "custom_scrapers.yaml"
# gpt-oss-120b : meilleur modele Groq pour cette tache (valide sur sites reels)
MODEL = os.environ.get("SCRAPER_GEN_MODEL", "openai/gpt-oss-120b")
MAX_ATTEMPTS = 3

SYSTEM_PROMPT = """Tu es un expert en scraping web. On te donne la carte des liens d'une page qui liste des articles : pour chaque lien <a>, son URL, son texte, et son contexte DOM (chaine des parents avec balises et classes).
Ta mission : identifier le selecteur CSS qui capture les liens vers les VRAIS articles (pas les rubriques, menus, tags ou pages de navigation).

Reponds UNIQUEMENT en JSON valide avec ce format exact :
{
  "article_link_selector": "<selecteur CSS matchant les liens <a> vers les articles>",
  "url_include_pattern": "<regex que les URLs d'articles doivent matcher, ou null>"
}

Regles :
- Prefere des selecteurs robustes (balises article/h2/h3, classes semantiques) aux classes generees aleatoirement
- Le selecteur doit matcher l'element <a> lui-meme ou un conteneur qui contient un <a>
- url_include_pattern aide a exclure la navigation (ex: "/article/", "/\\\\d{4}/") - mets null si le selecteur suffit
- Les liens d'articles ont generalement un texte long (le titre) et une URL profonde"""


def get_client():
    import httpx
    from groq import Groq

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        sys.exit("GROQ_API_KEY manquante (fichier .env)")
    verify = os.environ.get("INSECURE_SSL") != "1"
    return Groq(api_key=api_key, http_client=httpx.Client(verify=verify))


def build_links_digest(html: str, base_url: str, max_links: int = 110) -> str:
    """Carte compacte des liens de la page : href + texte + contexte DOM.
    C'est tout ce dont le LLM a besoin pour choisir un selecteur, et ca tient
    dans la limite de 8000 tokens/minute du tier gratuit Groq."""
    from urllib.parse import urljoin

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "svg", "noscript"]):
        tag.decompose()

    lines = []
    seen_hrefs = set()
    anchors = soup.find_all("a", href=True)
    # Les liens au texte long d'abord (probablement des titres d'articles)
    anchors.sort(key=lambda a: -len(a.get_text(strip=True)))

    for a in anchors:
        href = urljoin(base_url, a["href"])
        if href in seen_hrefs or href.startswith(("javascript:", "mailto:")):
            continue
        seen_hrefs.add(href)

        text = a.get_text(strip=True)[:70]
        parents = []
        node = a
        for _ in range(3):
            node = node.parent
            if node is None or node.name in ("body", "html", "[document]"):
                break
            classes = ".".join((node.get("class") or [])[:2])
            parents.append(f"{node.name}{'.' + classes if classes else ''}")
        a_classes = ".".join((a.get("class") or [])[:2])
        a_desc = f"a{'.' + a_classes if a_classes else ''}"

        lines.append(f'{a_desc} href="{href[:110]}" text="{text}" parents={" < ".join(parents)}')
        if len(lines) >= max_links:
            break

    return "\n".join(lines)


def ask_llm(client, list_url: str, links_digest: str, feedback: str) -> dict:
    user = f"URL de la page de liste : {list_url}"
    if feedback:
        user += f"\n\nTENTATIVE PRECEDENTE ECHOUEE : {feedback}\nPropose un selecteur different."
    user += f"\n\nCarte des liens de la page :\n{links_digest}"

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=800,
        response_format={"type": "json_object"},
    )
    answer = json.loads(response.choices[0].message.content)
    return answer if isinstance(answer, dict) else {}


def to_config(name: str, category: str, list_url: str, answer: dict) -> dict:
    config = {
        "name": name,
        "category": category,
        "list_url": list_url,
        "article_link_selector": answer.get("article_link_selector") or "a",
    }
    # Titre/date/contenu : le moteur a des fallbacks robustes (h1, JSON-LD,
    # trafilatura) - seul le selecteur de liens est demande au LLM.
    if answer.get("url_include_pattern"):
        config["url_include_pattern"] = answer["url_include_pattern"]
    return config


def save_config(config: dict) -> None:
    data = {"scrapers": []}
    if CUSTOM_SCRAPERS_PATH.exists():
        with open(CUSTOM_SCRAPERS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {"scrapers": []}
    scrapers = [s for s in data.get("scrapers", []) if s.get("list_url") != config["list_url"]]
    scrapers.append(config)
    data["scrapers"] = scrapers
    with open(CUSTOM_SCRAPERS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    list_url, name, category = sys.argv[1], sys.argv[2], sys.argv[3]

    print(f"[1/3] Telechargement de {list_url} ...")
    html = requests.get(list_url, headers=HEADERS, timeout=15, verify=VERIFY_SSL).text
    links_digest = build_links_digest(html, list_url)

    client = get_client()
    feedback = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"[2/3] Generation des selecteurs par {MODEL} (tentative {attempt}/{MAX_ATTEMPTS}) ...")
        try:
            answer = ask_llm(client, list_url, links_digest, feedback)
        except Exception as e:
            feedback = f"erreur LLM: {e}"
            continue

        config = to_config(name, category, list_url, answer)
        print(f"      Selecteurs proposes : {json.dumps(answer, ensure_ascii=False)}")

        print("[3/3] Test des selecteurs (vrai scraping) ...")
        result = test_config(config)

        if result["ok"]:
            print(f"\nSUCCES - {len(result['articles'])} articles extraits :")
            for a in result["articles"]:
                date = a["date"][:10] if a["date"] else "date inconnue"
                print(f"  - [{date}] {a['title'][:80]}")
                print(f"    {a['content'][:120]}...")
            confirm = input("\nEnregistrer ce scraper pour tous les prochains digests ? [o/N] ").strip().lower()
            if confirm == "o":
                save_config(config)
                print(f"Enregistre dans {CUSTOM_SCRAPERS_PATH}")
                print("Pense a commit + push pour qu'il soit utilise par GitHub Actions.")
            else:
                print("Abandonne (rien n'a ete enregistre).")
            return

        feedback = result["error"] or "aucun article extrait"
        print(f"      Echec : {feedback}")

    sys.exit(f"\nECHEC apres {MAX_ATTEMPTS} tentatives. Le site est peut-etre trop dynamique (JavaScript).")


if __name__ == "__main__":
    main()
