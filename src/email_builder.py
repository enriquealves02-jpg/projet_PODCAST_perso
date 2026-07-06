"""
Email Builder - Génère le HTML du digest à partir du template Jinja2.
"""

import json
import locale
import logging
import os
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
CONFIG_PATH = PROJECT_ROOT / "config" / "feeds.yaml"
OUTPUT_HTML = PROJECT_ROOT / "data" / "digest.html"
OUTPUT_JSON = PROJECT_ROOT / "data" / "digest.json"
OUTPUT_SEEN = PROJECT_ROOT / "data" / "seen_urls.json"


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


def build_html(articles: list[dict], editorials: list[dict] | None = None) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("digest.html")

    categories = group_by_category(articles)
    editorials_by_key = {e["key"]: e for e in (editorials or [])}
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
        editorials=editorials_by_key,
        rating_url=rating_url,
    )

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"Built digest HTML: {OUTPUT_HTML}")
    return html


def build_json(articles: list[dict], editorials: list[dict] | None = None) -> Path:
    """Version JSON du digest, consommee par l'application (rendu natif)."""
    categories = group_by_category(articles)
    now = datetime.now(timezone.utc)

    payload = {
        "date": now.strftime("%Y-%m-%d"),
        "generated_at": now.isoformat(),
        "total_articles": len(articles),
        "rating_url": os.environ.get("RATING_WEBHOOK_URL", ""),
        "editorials": editorials or [],
        "categories": [
            {
                "key": cat_key,
                "name": cat_data["name"],
                "icon": cat_data["icon"],
                "articles": [
                    {
                        "title": a.get("title", ""),
                        "url": a.get("url", ""),
                        "source": a.get("source", ""),
                        "date": a.get("date", ""),
                        "date_formatted": a.get("date_formatted", ""),
                        "score": a.get("score", 0),
                        "tag": a.get("tag", ""),
                        "summary": a.get("summary", ""),
                        "artist": a.get("artist", ""),
                        "film": a.get("film", ""),
                        "category": a.get("category", ""),
                        "category_name": a.get("category_name", ""),
                    }
                    for a in cat_data["articles"]
                ],
            }
            for cat_key, cat_data in categories.items()
            if cat_data["articles"]
        ],
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # URLs publiees aujourd'hui : fusionnees dans seen_urls.json au deploiement
    seen = {"urls": [a.get("url", "") for a in articles if a.get("url")]}
    with open(OUTPUT_SEEN, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)

    logger.info(f"Built digest JSON: {OUTPUT_JSON} ({len(articles)} articles)")
    return OUTPUT_JSON


def run(articles: list[dict], editorials: list[dict] | None = None) -> str:
    html = build_html(articles, editorials)
    build_json(articles, editorials)
    return html


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
