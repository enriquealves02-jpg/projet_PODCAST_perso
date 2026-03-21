"""
LLM Summarizer - Génère des résumés personnalisés pour les articles sélectionnés.
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
MODEL = "llama-3.3-70b-versatile"
MAX_ARTICLES_PER_BATCH = 5


def load_prompts() -> dict:
    with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_client() -> Groq:
    import httpx
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set")
    return Groq(api_key=api_key, http_client=httpx.Client(verify=False))


def build_summary_prompt(prompts: dict) -> str:
    return prompts["summarize_system_prompt"].replace(
        "{user_profile}", prompts["user_profile"]
    )


def format_articles_for_summary(articles: list[dict], offset: int = 0) -> str:
    lines = []
    for i, article in enumerate(articles):
        idx = offset + i
        content = article.get("content", "")[:2000]
        date = article.get("date", "Date inconnue")
        lines.append(
            f"--- Article {idx} ---\n"
            f"Titre: {article['title']}\n"
            f"Date de publication: {date}\n"
            f"Source: {article['source']} ({article['category_name']})\n"
            f"Contenu: {content}\n"
        )
    return "\n".join(lines)


def summarize_batch(client: Groq, system_prompt: str, articles: list[dict], offset: int = 0) -> list[dict]:
    articles_text = format_articles_for_summary(articles, offset)
    user_prompt = (
        f"Résume les {len(articles)} articles suivants selon les instructions.\n\n"
        f"{articles_text}"
    )

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
            max_tokens=3000,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
        return result.get("summaries", [])

    except Exception as e:
        logger.error(f"Error summarizing batch: {e}")
        return []


def summarize_articles(articles: list[dict]) -> list[dict]:
    if not articles:
        logger.warning("No articles to summarize")
        return []

    prompts = load_prompts()
    system_prompt = build_summary_prompt(prompts)
    client = get_client()

    all_summaries = []
    for i in range(0, len(articles), MAX_ARTICLES_PER_BATCH):
        batch = articles[i : i + MAX_ARTICLES_PER_BATCH]
        logger.info(f"Summarizing batch {i // MAX_ARTICLES_PER_BATCH + 1} ({len(batch)} articles)")
        summaries = summarize_batch(client, system_prompt, batch, offset=i)
        all_summaries.extend(summaries)

    summary_map = {s["id"]: s for s in all_summaries}

    enriched = []
    for i, article in enumerate(articles):
        summary_info = summary_map.get(i, {})
        article["summary"] = summary_info.get("summary", "Résumé non disponible.")
        article["tag"] = summary_info.get("tag", "Découverte")
        article["artist"] = summary_info.get("artist", "")
        enriched.append(article)

    logger.info(f"Summarized {len(enriched)} articles")
    return enriched


def run(articles: list[dict]) -> list[dict]:
    return summarize_articles(articles)


if __name__ == "__main__":
    import csv

    csv_path = PROJECT_ROOT / "data" / "articles_raw.csv"
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        articles = list(reader)[:5]

    enriched = run(articles)
    for a in enriched:
        print(f"\n[{a['tag']}] {a['title']}")
        print(f"  {a['summary']}")
