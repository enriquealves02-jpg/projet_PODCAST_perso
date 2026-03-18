"""
LLM Filter - Utilise Groq API pour scorer et sélectionner les articles les plus pertinents.
"""

import json
import logging
import os
from pathlib import Path

import yaml
from groq import Groq

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
PROMPTS_PATH = PROJECT_ROOT / "config" / "prompts.yaml"
MODEL = "llama-3.1-8b-instant"
MAX_ARTICLES_PER_BATCH = 20
MIN_SCORE = 5
MAX_SELECTED = 20

# Quotas par catégorie (clé = category key dans feeds.yaml)
CATEGORY_QUOTAS = {
    "tech_ia": 5,
    "science_math": 3,
    "cinema": 3,
    "actualite": 3,
    "mode_homme": 3,
    "musique": 3,
}
DEFAULT_QUOTA = 3

# Sources prioritaires par catégorie
PRIORITY_SOURCES = {
    "tech_ia": ["TLDR AI"],
}


def load_prompts() -> dict:
    with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_client() -> Groq:
    import httpx
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set")
    return Groq(api_key=api_key, http_client=httpx.Client(verify=False))


def build_filter_prompt(prompts: dict) -> str:
    return prompts["filter_system_prompt"].replace(
        "{user_profile}", prompts["user_profile"]
    )


def format_articles_for_llm(articles: list[dict], offset: int = 0) -> str:
    lines = []
    for i, article in enumerate(articles):
        idx = offset + i
        content_preview = article["content"][:200] if article["content"] else "Pas de contenu disponible"
        lines.append(
            f"--- Article {idx} ---\n"
            f"Titre: {article['title']}\n"
            f"Source: {article['source']} ({article['category_name']})\n"
            f"Contenu: {content_preview}\n"
        )
    return "\n".join(lines)


def score_batch(client: Groq, system_prompt: str, articles: list[dict], offset: int = 0) -> list[dict]:
    articles_text = format_articles_for_llm(articles, offset)
    user_prompt = (
        f"Voici {len(articles)} articles à évaluer. "
        f"Score chaque article de 1 à 10 selon sa pertinence pour le lecteur.\n\n"
        f"{articles_text}"
    )

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
        return result.get("articles", [])

    except Exception as e:
        logger.error(f"Error scoring batch: {e}")
        return []


def filter_articles(articles: list[dict]) -> list[dict]:
    if not articles:
        logger.warning("No articles to filter")
        return []

    prompts = load_prompts()
    system_prompt = build_filter_prompt(prompts)
    client = get_client()

    all_scores = []
    for i in range(0, len(articles), MAX_ARTICLES_PER_BATCH):
        batch = articles[i : i + MAX_ARTICLES_PER_BATCH]
        logger.info(f"Scoring batch {i // MAX_ARTICLES_PER_BATCH + 1} ({len(batch)} articles)")
        scores = score_batch(client, system_prompt, batch, offset=i)
        all_scores.extend(scores)

    score_map = {s["id"]: s for s in all_scores}

    scored_articles = []
    for i, article in enumerate(articles):
        score_info = score_map.get(i, {})
        article["score"] = score_info.get("score", 0)
        article["score_reason"] = score_info.get("reason", "")
        scored_articles.append(article)

    # Group by category and select top N per category
    from collections import defaultdict
    by_category = defaultdict(list)
    for a in scored_articles:
        if a["score"] >= MIN_SCORE:
            by_category[a["category"]].append(a)

    selected = []
    for cat_key, cat_articles in by_category.items():
        quota = CATEGORY_QUOTAS.get(cat_key, DEFAULT_QUOTA)
        priority_sources = PRIORITY_SOURCES.get(cat_key, [])

        # Sort: priority sources first, then by score
        cat_articles.sort(
            key=lambda a: (a["source"] not in priority_sources, -a["score"])
        )
        selected.extend(cat_articles[:quota])

    # Sort final selection by category order then score
    cat_order = list(CATEGORY_QUOTAS.keys())
    selected.sort(key=lambda a: (
        cat_order.index(a["category"]) if a["category"] in cat_order else 99,
        -a["score"],
    ))

    logger.info(
        f"Selected {len(selected)} articles out of {len(articles)} "
        f"(by category quotas, min score: {MIN_SCORE})"
    )
    return selected


def run(articles: list[dict]) -> list[dict]:
    return filter_articles(articles)


if __name__ == "__main__":
    import csv

    csv_path = PROJECT_ROOT / "data" / "articles_raw.csv"
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        articles = list(reader)

    selected = run(articles)
    print(f"\nSelected {len(selected)} articles:")
    for a in selected:
        print(f"  [{a['score']}] {a['title']} ({a['source']})")
