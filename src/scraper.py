"""
RSS Scraper - Récupère les articles des dernières 24h depuis les flux RSS configurés.

- Flux scrapés en parallèle (ThreadPoolExecutor)
- Extraction du contenu complet via trafilatura (fallback BeautifulSoup)
- Déduplication par URL et par titre normalisé (même sujet couvert par 2 sources)
- Exclusion des articles déjà publiés dans un digest précédent (seen_urls.json sur GitHub Pages)
"""

import csv
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import mktime

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

try:
    import trafilatura
except ImportError:
    trafilatura = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "feeds.yaml"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_CSV = DATA_DIR / "articles_raw.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (PersonalDigest/1.0; +https://github.com/personal-digest)"
}

# Scraping de sites publics (aucun secret ne transite) : SSL desactive pour ne JAMAIS
# bloquer la recolte d'articles a cause d'un certificat capricieux ou du proxy local.
VERIFY_SSL = False

# Nb de flux recuperes en parallele
MAX_WORKERS = 8


def load_feeds_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_pages_base_url() -> str:
    """URL de base GitHub Pages, deduite de GITHUB_REPOSITORY ou surchargee par PAGES_URL."""
    explicit = os.environ.get("PAGES_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "enriquealves02-jpg/projet_PODCAST_perso")
    owner, _, name = repo.partition("/")
    return f"https://{owner}.github.io/{name}"


def load_published_urls() -> set[str]:
    """URLs deja publiees dans les digests precedents (pour eviter les redites)."""
    url = f"{get_pages_base_url()}/seen_urls.json"
    try:
        resp = requests.get(url, timeout=10, verify=VERIFY_SSL)
        if resp.status_code == 404:
            return set()
        resp.raise_for_status()
        urls = set(resp.json().get("urls", []))
        logger.info(f"{len(urls)} URLs deja publiees chargees depuis {url}")
        return urls
    except Exception as e:
        logger.warning(f"seen_urls.json indisponible ({e}) - pas d'exclusion inter-jours")
        return set()


def parse_published_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            return datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
    return None


def extract_content(entry) -> str:
    if hasattr(entry, "content") and entry.content:
        return BeautifulSoup(entry.content[0].value, "html.parser").get_text(separator=" ", strip=True)
    if hasattr(entry, "summary") and entry.summary:
        return BeautifulSoup(entry.summary, "html.parser").get_text(separator=" ", strip=True)
    return ""


def fetch_full_content(url: str, max_length: int = 3000) -> str:
    """Recupere le contenu complet d'un article. trafilatura d'abord (extraction
    d'article de qualite), fallback sur l'heuristique BeautifulSoup."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, verify=VERIFY_SSL)
        resp.raise_for_status()

        if trafilatura is not None:
            text = trafilatura.extract(resp.text, include_comments=False, include_tables=False)
            if text and len(text) > 200:
                return text[:max_length]

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        article = soup.find("article") or soup.find("main") or soup.find("body")
        if article:
            text = article.get_text(separator=" ", strip=True)
            return text[:max_length]
    except Exception as e:
        logger.debug(f"Could not fetch full content from {url}: {e}")
    return ""


def scrape_single_feed(feed_info: dict, category_key: str, category_name: str, cutoff: datetime) -> list[dict]:
    feed_url = feed_info["url"]
    feed_name = feed_info["name"]
    articles = []

    try:
        feed = feedparser.parse(feed_url, agent=HEADERS["User-Agent"])

        if feed.bozo and not feed.entries:
            logger.warning(f"  Failed to parse {feed_name}: {feed.bozo_exception}")
            return []

        for entry in feed.entries:
            pub_date = parse_published_date(entry)

            if pub_date and pub_date < cutoff:
                continue

            title = entry.get("title", "Sans titre")
            link = entry.get("link", "")
            content = extract_content(entry)

            if len(content) < 100 and link:
                full = fetch_full_content(link)
                if full:
                    content = full

            articles.append({
                "title": title,
                "date": pub_date.isoformat() if pub_date else "",
                "content": content[:5000],
                "url": link,
                "category": category_key,
                "category_name": category_name,
                "source": feed_name,
            })

        logger.info(f"  {feed_name}: {len(articles)} articles")

    except Exception as e:
        logger.error(f"  Error scraping {feed_name}: {e}")

    return articles


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def deduplicate(articles: list[dict], published_urls: set[str]) -> list[dict]:
    """Supprime les doublons (URL, titre normalise) et les articles deja publies."""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    result = []
    skipped_published = skipped_dup = 0

    for a in articles:
        url = a.get("url", "")
        norm = normalize_title(a.get("title", ""))
        if url and url in published_urls:
            skipped_published += 1
            continue
        if url and url in seen_urls:
            skipped_dup += 1
            continue
        if norm and norm in seen_titles:
            skipped_dup += 1
            continue
        if url:
            seen_urls.add(url)
        if norm:
            seen_titles.add(norm)
        result.append(a)

    if skipped_published or skipped_dup:
        logger.info(
            f"Deduplication : {skipped_published} deja publies, {skipped_dup} doublons ecartes"
        )
    return result


def scrape_feeds(hours_back: int = 24) -> list[dict]:
    config = load_feeds_config()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    articles = []

    tasks = []
    for category_key, category_data in config["categories"].items():
        for feed_info in category_data["feeds"]:
            tasks.append((feed_info, category_key, category_data["name"]))

    logger.info(f"Scraping {len(tasks)} feeds ({MAX_WORKERS} en parallele)...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(scrape_single_feed, feed_info, cat_key, cat_name, cutoff): feed_info["name"]
            for feed_info, cat_key, cat_name in tasks
        }
        for future in as_completed(futures):
            articles.extend(future.result())

    logger.info(f"Total articles scraped: {len(articles)}")
    return articles


def save_to_csv(articles: list[dict]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = ["title", "date", "content", "url", "category", "category_name", "source"]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(articles)

    logger.info(f"Saved {len(articles)} articles to {OUTPUT_CSV}")
    return OUTPUT_CSV


def run() -> list[dict]:
    from src.scrapers_custom import run_all_custom_scrapers

    published_urls = load_published_urls()
    articles = scrape_feeds()
    custom_articles = run_all_custom_scrapers()
    articles.extend(custom_articles)
    articles = deduplicate(articles, published_urls)
    logger.info(f"Total with custom scrapers (after dedup): {len(articles)} articles")
    save_to_csv(articles)
    return articles


if __name__ == "__main__":
    run()
