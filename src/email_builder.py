"""
Email Builder - Génère le HTML du digest à partir du template Jinja2.
"""

import locale
import logging
import os
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
CONFIG_PATH = PROJECT_ROOT / "config" / "feeds.yaml"
OUTPUT_HTML = PROJECT_ROOT / "data" / "digest.html"


def load_feeds_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def format_date(date_str: str) -> str:
    if not date_str:
        return "Date inconnue"
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%d/%m à %Hh%M")
    except (ValueError, TypeError):
        return date_str[:10]


def group_by_category(articles: list[dict]) -> OrderedDict:
    config = load_feeds_config()
    categories = OrderedDict()

    for cat_key, cat_data in config["categories"].items():
        categories[cat_key] = {
            "name": cat_data["name"],
            "icon": cat_data["icon"],
            "articles": [],
        }

    for article in articles:
        cat_key = article.get("category", "")
        article["date_formatted"] = format_date(article.get("date", ""))
        if cat_key in categories:
            categories[cat_key]["articles"].append(article)

    return categories


def build_html(articles: list[dict]) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("digest.html")

    categories = group_by_category(articles)
    try:
        locale.setlocale(locale.LC_TIME, "fr_FR.UTF-8")
    except locale.Error:
        try:
            locale.setlocale(locale.LC_TIME, "French_France.1252")
        except locale.Error:
            pass
    today = datetime.now().strftime("%A %d %B %Y").capitalize()

    rating_url = os.environ.get("RATING_WEBHOOK_URL", "")

    html = template.render(
        date=today,
        total_articles=len(articles),
        categories=categories,
        rating_url=rating_url,
    )

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"Built digest HTML: {OUTPUT_HTML}")
    return html


def run(articles: list[dict]) -> str:
    return build_html(articles)


if __name__ == "__main__":
    sample = [
        {
            "title": "Test Article",
            "date": "2026-03-18T08:00:00+00:00",
            "content": "Contenu test",
            "url": "https://example.com",
            "category": "tech_ia",
            "category_name": "Tech & IA",
            "source": "Test Source",
            "score": 8,
            "score_reason": "Test",
            "summary": "Ceci est un résumé de test.",
            "why_interesting": "Test de pertinence.",
            "tag": "Découverte",
        }
    ]
    html = run(sample)
    print(f"Preview saved to {OUTPUT_HTML}")
