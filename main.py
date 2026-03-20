"""
Daily Digest - Orchestrateur principal.

Pipeline : RSS Scraping → LLM Filtering → LLM Summarizing → HTML Build → Email Send
"""

import logging
import os
import ssl
import sys
from pathlib import Path

import httpx

from dotenv import load_dotenv

load_dotenv()

# Fix SSL pour les réseaux d'entreprise avec proxy interceptant
os.environ["PYTHONHTTPSVERIFY"] = "0"
ssl._create_default_https_context = ssl._create_unverified_context
os.environ["GROQ_SSL_VERIFY"] = "false"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("daily-digest")

from src.scraper import run as scrape
from src.filter import run as filter_articles
from src.summarizer import run as summarize
from src.email_builder import run as build_html
from src.sender import run as send_email


def main(dry_run: bool = False) -> None:
    logger.info("=" * 60)
    logger.info("DAILY DIGEST - Starting pipeline")
    logger.info("=" * 60)

    # Step 1: Scrape RSS feeds
    logger.info("[1/5] Scraping RSS feeds...")
    articles = scrape()
    if not articles:
        logger.warning("No articles found. Aborting.")
        return
    logger.info(f"[1/5] Done - {len(articles)} articles scraped")

    # Step 2: Filter with LLM
    logger.info("[2/5] Filtering articles with LLM...")
    selected = filter_articles(articles)
    if not selected:
        logger.warning("No articles passed the filter. Aborting.")
        return
    logger.info(f"[2/5] Done - {len(selected)} articles selected")

    # Step 3: Summarize with LLM
    logger.info("[3/5] Summarizing articles with LLM...")
    enriched = summarize(selected)
    logger.info(f"[3/5] Done - {len(enriched)} articles summarized")

    # Step 4: Build HTML
    logger.info("[4/5] Building HTML digest...")
    html = build_html(enriched)
    logger.info("[4/5] Done - HTML digest generated")

    # Step 5: Send email
    if dry_run:
        logger.info("[5/5] Dry run - skipping email send")
        logger.info(f"Preview available at: {Path('data/digest.html').absolute()}")
    else:
        logger.info("[5/5] Sending email...")
        send_email(html)
        logger.info("[5/5] Done - Email sent!")

    logger.info("=" * 60)
    logger.info("DAILY DIGEST - Pipeline complete!")
    logger.info("=" * 60)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    main(dry_run=dry_run)
