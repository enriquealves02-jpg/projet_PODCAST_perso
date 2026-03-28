"""
Custom Scrapers - Scraping HTML direct pour les sites sans flux RSS.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def scrape_cahiers_du_cinema(hours_back: int = 24) -> list[dict]:
    """Scrape les derniers articles des Cahiers du Cinéma."""
    base_url = "https://www.cahiersducinema.com"
    listing_url = f"{base_url}/fr-fr"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    articles = []

    try:
        resp = requests.get(listing_url, headers=HEADERS, timeout=15, verify=False)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/fr-fr/article/" in href and href not in links:
                links.add(href)

        logger.info(f"Cahiers du Cinéma: found {len(links)} article links")

        for href in links:
            url = href if href.startswith("http") else base_url + href
            article = _scrape_cahiers_article(url, cutoff)
            if article:
                articles.append(article)

    except Exception as e:
        logger.error(f"Error scraping Cahiers du Cinéma listing: {e}")

    logger.info(f"Cahiers du Cinéma: {len(articles)} articles from last {hours_back}h")
    return articles


def _scrape_cahiers_article(url: str, cutoff: datetime) -> dict | None:
    """Scrape un article individuel des Cahiers du Cinéma."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Extraire les données JSON-LD (plus fiable que le HTML)
        json_ld = None
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if "headline" in data:
                    json_ld = data
                    break
            except (json.JSONDecodeError, TypeError):
                continue

        if json_ld:
            title = json_ld.get("headline", "")
            date_str = json_ld.get("datePublished", "")
            author = json_ld.get("author", {}).get("name", "")
        else:
            # Fallback sur le HTML
            h1 = soup.find("h1")
            title = h1.get_text(strip=True) if h1 else ""

            date_span = soup.find("span", string=re.compile(r"Publié le"))
            date_str = ""
            if date_span:
                match = re.search(r"(\d{1,2}\s+\w+\s+\d{4})", date_span.get_text())
                if match:
                    date_str = match.group(1)
            author = ""

        # Parser la date
        pub_date = None
        if date_str:
            try:
                pub_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        # Filtre de date
        if pub_date and pub_date < cutoff:
            return None

        # Extraire le contenu
        paragraphs = soup.find_all("p", attrs={"data-start": True})
        content = " ".join(p.get_text(strip=True) for p in paragraphs)

        if not content:
            content_div = soup.find("div", class_=re.compile(r"content"))
            if content_div:
                content = content_div.get_text(separator=" ", strip=True)

        if not title:
            return None

        return {
            "title": title,
            "date": pub_date.isoformat() if pub_date else "",
            "content": content[:5000],
            "url": url,
            "category": "cinema",
            "category_name": "Cinéma",
            "source": "Cahiers du Cinéma",
        }

    except Exception as e:
        logger.debug(f"Error scraping {url}: {e}")
        return None


def scrape_tldr_ai(hours_back: int = 24) -> list[dict]:
    """Scrape la newsletter TLDR AI du jour — chaque sujet devient un article séparé."""
    today = datetime.now(timezone.utc)
    articles = []

    # Tenter aujourd'hui et hier (le pipeline tourne tôt le matin)
    dates_to_try = [
        today.strftime("%Y-%m-%d"),
        (today - timedelta(hours=hours_back)).strftime("%Y-%m-%d"),
    ]

    for date_str in dict.fromkeys(dates_to_try):  # deduplicate
        url = f"https://tldr.tech/ai/{date_str}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for article_tag in soup.find_all("article"):
                link_tag = article_tag.find("a", href=True)
                h3_tag = article_tag.find("h3")
                content_div = article_tag.find("div", class_="newsletter-html")

                if not h3_tag or not link_tag:
                    continue

                title = h3_tag.get_text(strip=True)

                # Ignorer les sponsors
                if "(Sponsor)" in title or "Sponsor" in title:
                    continue

                href = link_tag["href"]
                content = content_div.get_text(separator=" ", strip=True) if content_div else ""

                if not content or len(content) < 30:
                    continue

                articles.append({
                    "title": title,
                    "date": f"{date_str}T06:00:00+00:00",
                    "content": content[:5000],
                    "url": href,
                    "category": "tech_ia",
                    "category_name": "Tech & Intelligence Artificielle",
                    "source": "TLDR AI",
                })

            if articles:
                break  # On a trouvé des articles, pas besoin d'essayer l'autre date

        except Exception as e:
            logger.error(f"Error scraping TLDR AI for {date_str}: {e}")

    logger.info(f"TLDR AI: {len(articles)} articles scraped")
    return articles


# Registre des scrapers custom : nom -> fonction
CUSTOM_SCRAPERS = {
    "cahiers_du_cinema": scrape_cahiers_du_cinema,
    "tldr_ai": scrape_tldr_ai,
}


def run_all_custom_scrapers(hours_back: int = 24) -> list[dict]:
    """Lance tous les scrapers custom et retourne les articles combinés."""
    all_articles = []
    for name, scraper_fn in CUSTOM_SCRAPERS.items():
        logger.info(f"Running custom scraper: {name}")
        try:
            articles = scraper_fn(hours_back=hours_back)
            all_articles.extend(articles)
        except Exception as e:
            logger.error(f"Custom scraper {name} failed: {e}")
    return all_articles


if __name__ == "__main__":
    articles = scrape_cahiers_du_cinema(hours_back=720)  # 30 jours pour tester
    for a in articles:
        print(f"  [{a['date'][:10]}] {a['title']}")
        print(f"    {a['content'][:150]}...")
        print()
