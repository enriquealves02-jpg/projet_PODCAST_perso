"""
RSS Scraper - Récupère les articles des dernières 24h depuis les flux RSS configurés.
"""

import csv
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import mktime

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "feeds.yaml"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_CSV = DATA_DIR / "articles_raw.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (PersonalDigest/1.0; +https://github.com/personal-digest)"
}


def load_feeds_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, verify=False)
        resp.raise_for_status()
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


def scrape_feeds(hours_back: int = 24) -> list[dict]:
    config = load_feeds_config()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    articles = []

    for category_key, category_data in config["categories"].items():
        category_name = category_data["name"]
        logger.info(f"Scraping category: {category_name}")

        for feed_info in category_data["feeds"]:
            feed_url = feed_info["url"]
            feed_name = feed_info["name"]
            logger.info(f"  Fetching: {feed_name}")

            try:
                feed = feedparser.parse(feed_url, agent=HEADERS["User-Agent"])

                if feed.bozo and not feed.entries:
                    logger.warning(f"  Failed to parse {feed_name}: {feed.bozo_exception}")
                    continue

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

                logger.info(f"  Found {len([a for a in articles if a['source'] == feed_name])} articles from {feed_name}")

            except Exception as e:
                logger.error(f"  Error scraping {feed_name}: {e}")

    logger.info(f"Total articles scraped: {len(articles)}")
    return articles


def save_to_csv(articles: list[dict]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = ["title", "date", "content", "url", "category", "category_name", "source"]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(articles)

    logger.info(f"Saved {len(articles)} articles to {OUTPUT_CSV}")
    return OUTPUT_CSV


def run() -> list[dict]:
    from src.scrapers_custom import run_all_custom_scrapers

    articles = scrape_feeds()
    custom_articles = run_all_custom_scrapers()
    articles.extend(custom_articles)
    logger.info(f"Total with custom scrapers: {len(articles)} articles")
    save_to_csv(articles)
    return articles


if __name__ == "__main__":
    run()
