"""
Fiabilisation des liens Spotify / Letterboxd.

Trois protections, dans l'ordre :
1. Verification de presence : si le nom extrait par le LLM n'apparait pas dans
   l'article (titre + contenu), c'est une hallucination -> on retire le lien.
2. Artistes : canonicalisation via MusicBrainz (API publique, sans cle) pour
   corriger l'orthographe/casse et confirmer que c'est bien un artiste.
3. Films : resolution de la page Letterboxd exacte (scrape de la recherche)
   -> lien DIRECT vers /film/<slug>/, celui qui permet d'ajouter a la
   watchlist en un clic. Fallback : lien de recherche.
"""

import logging
import re
import time
import unicodedata
from urllib.parse import quote

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

VERIFY_SSL = False
HEADERS = {
    "User-Agent": "PersonalDailyDigest/1.0 (contact: github.com/enriquealves02-jpg)"
}
# MusicBrainz demande max 1 requete/seconde
MUSICBRAINZ_DELAY = 1.1


def _normalize(text: str) -> str:
    """minuscules + accents retires + espaces normalises, pour comparer."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


def is_present_in_article(name: str, article: dict, loose: bool = False) -> bool:
    """Le nom extrait doit apparaitre dans l'article, sinon c'est une
    hallucination du LLM (confusion artiste/album, film invente...).

    loose=True (films) : on demande le titre ORIGINAL au LLM, qui peut differer
    du titre cite dans un article francais -> il suffit que la moitie des mots
    significatifs du titre apparaissent dans l'article."""
    if not name or len(name) < 2:
        return False
    haystack = _normalize(f"{article.get('title', '')} {article.get('content', '')}")
    needle = _normalize(name)
    if needle in haystack:
        return True
    if loose:
        words = [w for w in re.split(r"[^a-z0-9]+", needle) if len(w) > 3]
        if words:
            found = sum(1 for w in words if w in haystack)
            return found >= max(1, len(words) // 2)
    return False


def canonicalize_artist(name: str) -> str | None:
    """Retourne le nom canonique MusicBrainz de l'artiste, ou None si aucun
    artiste plausible ne correspond (le lien sera retire)."""
    try:
        resp = requests.get(
            "https://musicbrainz.org/ws/2/artist/",
            params={"query": f'artist:"{name}"', "fmt": "json", "limit": 1},
            headers=HEADERS,
            timeout=10,
            verify=VERIFY_SSL,
        )
        resp.raise_for_status()
        artists = resp.json().get("artists", [])
        if not artists:
            return None
        top = artists[0]
        score = int(top.get("score", 0))
        if score < 85:
            return None
        return top.get("name") or None
    except Exception as e:
        logger.debug(f"MusicBrainz indisponible pour '{name}': {e}")
        # API indisponible : on garde le nom du LLM (deja verifie present)
        return name


def resolve_letterboxd(title: str) -> str | None:
    """Resout le film via l'API de suggestion IMDb (publique, sans cle) puis
    construit l'URL de redirection officielle Letterboxd /imdb/<id>/ : elle
    mene directement a la page du film (bouton watchlist inclus).
    Letterboxd lui-meme est derriere Cloudflare, donc non scrapable — mais la
    redirection fonctionne parfaitement dans le navigateur de l'utilisateur."""
    try:
        url = f"https://v3.sg.media-imdb.com/suggestion/x/{quote(title)}.json"
        resp = requests.get(url, headers=HEADERS, timeout=10, verify=VERIFY_SSL)
        resp.raise_for_status()
        entries = resp.json().get("d", [])

        candidates = [
            e for e in entries
            if str(e.get("id", "")).startswith("tt") and e.get("q") not in ("TV series", "video game")
        ]
        if not candidates:
            return None
        # Les longs metrages d'abord, sinon premier resultat film
        features = [e for e in candidates if e.get("q") == "feature"]
        best = (features or candidates)[0]
        return f"https://letterboxd.com/imdb/{best['id']}/"
    except Exception as e:
        logger.debug(f"Resolution IMDb indisponible pour '{title}': {e}")
        return None


def run(articles: list[dict]) -> list[dict]:
    """Verifie et resout les liens artiste/film des articles enrichis.
    Ajoute artist_url / film_url (vides si rien de fiable)."""
    musicbrainz_calls = 0

    for article in articles:
        article.setdefault("artist_url", "")
        article.setdefault("film_url", "")

        # ----- Musique -----
        artist = (article.get("artist") or "").strip()
        if artist:
            if not is_present_in_article(artist, article):
                logger.info(f"Artiste '{artist}' absent de l'article -> lien retire")
                article["artist"] = ""
            else:
                if musicbrainz_calls:
                    time.sleep(MUSICBRAINZ_DELAY)
                canonical = canonicalize_artist(artist)
                musicbrainz_calls += 1
                if canonical is None:
                    logger.info(f"Artiste '{artist}' inconnu de MusicBrainz -> lien retire")
                    article["artist"] = ""
                else:
                    if canonical != artist:
                        logger.info(f"Artiste corrige : '{artist}' -> '{canonical}'")
                    article["artist"] = canonical
                    article["artist_url"] = (
                        f"https://open.spotify.com/search/{quote(canonical)}/artists"
                    )

        # ----- Cinema -----
        film = (article.get("film") or "").strip()
        if film:
            if not is_present_in_article(film, article, loose=True):
                logger.info(f"Film '{film}' absent de l'article -> lien retire")
                article["film"] = ""
            else:
                direct = resolve_letterboxd(film)
                if direct:
                    article["film_url"] = direct
                    logger.info(f"Film '{film}' -> {direct}")
                else:
                    # Introuvable sur Letterboxd : lien de recherche en secours
                    article["film_url"] = f"https://letterboxd.com/search/films/{quote(film)}/"
                    logger.info(f"Film '{film}' non resolu -> lien de recherche")

    return articles
