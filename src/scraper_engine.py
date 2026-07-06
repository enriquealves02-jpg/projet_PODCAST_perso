"""
Moteur de scrapers declaratifs : execute une config de selecteurs CSS
(generee par IA via tools/generate_scraper.py, ou ecrite a la main dans
config/custom_scrapers.yaml). Aucun code genere n'est execute - uniquement
des selecteurs.

Format d'une config :
  name: "Nom du site"
  category: "cinema"                  # cle de categorie de feeds.yaml
  list_url: "https://site.com/articles"
  article_link_selector: "article h2 a"
  url_include_pattern: "/article/"    # optionnel (regex)
  title_selector: "h1"                # optionnel (defaut : h1 / <title>)
  date_selector: "time"               # optionnel
  date_attribute: "datetime"          # optionnel (defaut : texte de l'element)
  content_selector: ".article-body"   # optionnel (defaut : trafilatura)
"""

import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    import trafilatura
except ImportError:
    trafilatura = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
VERIFY_SSL = False


def _fetch(url: str, timeout: int = 15) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=timeout, verify=VERIFY_SSL)
    resp.raise_for_status()
    return resp.text


def _parse_date(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _jsonld_date(soup: BeautifulSoup) -> datetime | None:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if isinstance(item, dict) and item.get("datePublished"):
                parsed = _parse_date(str(item["datePublished"]))
                if parsed:
                    return parsed
    return None


def _extract_content(html: str, soup: BeautifulSoup, config: dict) -> str:
    selector = config.get("content_selector")
    if selector:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(separator=" ", strip=True)
            if len(text) >= 100:
                return text
    if trafilatura is not None:
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text and len(text) >= 100:
            return text
    body = soup.find("article") or soup.find("main") or soup.find("body")
    return body.get_text(separator=" ", strip=True) if body else ""


def scrape_article(url: str, config: dict) -> dict | None:
    """Extrait un article individuel selon la config. None si inexploitable."""
    try:
        html = _fetch(url)
        soup = BeautifulSoup(html, "html.parser")

        title = None
        if config.get("title_selector"):
            el = soup.select_one(config["title_selector"])
            title = el.get_text(strip=True) if el else None
        if not title:
            h1 = soup.find("h1")
            title = h1.get_text(strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else "")

        pub_date = None
        if config.get("date_selector"):
            el = soup.select_one(config["date_selector"])
            if el:
                raw = el.get(config["date_attribute"]) if config.get("date_attribute") else el.get_text(strip=True)
                pub_date = _parse_date(str(raw or ""))
        if not pub_date:
            pub_date = _jsonld_date(soup)

        content = _extract_content(html, soup, config)

        if not title or len(content) < 100:
            return None

        return {
            "title": title,
            "date": pub_date.isoformat() if pub_date else "",
            "content": content[:5000],
            "url": url,
        }
    except Exception as e:
        logger.debug(f"Article inexploitable {url}: {e}")
        return None


def run_config(config: dict, max_articles: int = 10) -> list[dict]:
    """Execute une config complete : page de liste -> liens -> articles."""
    html = _fetch(config["list_url"])
    soup = BeautifulSoup(html, "html.parser")

    pattern = re.compile(config["url_include_pattern"]) if config.get("url_include_pattern") else None
    urls: list[str] = []
    seen: set[str] = set()

    for el in soup.select(config["article_link_selector"]):
        a = el if el.name == "a" else el.find("a")
        href = a.get("href") if a else None
        if not href:
            continue
        abs_url = urljoin(config["list_url"], href)
        if pattern and not pattern.search(abs_url):
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        urls.append(abs_url)
        if len(urls) >= max_articles:
            break

    articles = []
    for url in urls:
        article = scrape_article(url, config)
        if article:
            articles.append(article)
    return articles


def test_config(config: dict, max_articles: int = 5) -> dict:
    """Teste une config et retourne {ok, articles, error} (pour la generation IA)."""
    try:
        articles = run_config(config, max_articles=max_articles)
        if not articles:
            return {"ok": False, "articles": [], "error": "Aucun article extrait avec ces selecteurs."}
        return {"ok": True, "articles": articles, "error": None}
    except Exception as e:
        return {"ok": False, "articles": [], "error": str(e)}
