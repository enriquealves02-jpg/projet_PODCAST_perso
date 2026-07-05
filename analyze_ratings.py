"""
Analyse des ratings du Journal d'Enrique.
Déduplique par URL (garde la dernière note) et affiche les stats.
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import openpyxl
from collections import defaultdict

EXCEL_PATH = r"C:\Users\enriq\OneDrive\Bureau\Ratings Journal Enrique.xlsx"


def load_and_deduplicate():
    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb.active

    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        date, title, source, category, url, score, rated_at = row
        if not url or not score:
            continue
        rows.append({
            "title": title,
            "source": source,
            "category": category,
            "url": url,
            "score": int(score),
            "rated_at": rated_at,
        })

    # Déduplique par URL : garde la dernière note (rated_at le plus récent)
    by_url = {}
    for r in rows:
        existing = by_url.get(r["url"])
        if not existing or (r["rated_at"] and (not existing["rated_at"] or r["rated_at"] > existing["rated_at"])):
            by_url[r["url"]] = r

    articles = list(by_url.values())
    return articles, len(rows)


def analyze(articles, total_raw):
    print("=" * 60)
    print("  ANALYSE DES RATINGS — Journal d'Enrique")
    print("=" * 60)

    # --- Nombre d'articles ---
    print(f"\n📊 Articles notés : {len(articles)} (avant dédup : {total_raw}, soit {total_raw - len(articles)} doublons supprimés)")

    # --- Distribution des notes ---
    dist = defaultdict(int)
    for a in articles:
        dist[a["score"]] += 1

    print("\n📈 Distribution des notes :")
    print("-" * 40)
    for score in range(1, 11):
        count = dist.get(score, 0)
        bar = "█" * count
        pct = (count / len(articles) * 100) if articles else 0
        print(f"  {score:2d}/10  {bar} {count} ({pct:.0f}%)")

    avg = sum(a["score"] for a in articles) / len(articles) if articles else 0
    print(f"\n  Moyenne : {avg:.1f}/10")

    # --- Sources par catégorie ---
    cat_sources = defaultdict(lambda: defaultdict(list))
    for a in articles:
        cat = a["category"] or "Inconnue"
        src = a["source"] or "Inconnue"
        cat_sources[cat][src].append(a["score"])

    print("\n🏆 Meilleures sources par catégorie :")
    print("-" * 40)
    for cat in sorted(cat_sources.keys()):
        sources = cat_sources[cat]
        ranked = []
        for src, scores in sources.items():
            ranked.append((src, sum(scores) / len(scores), len(scores)))
        ranked.sort(key=lambda x: -x[1])

        print(f"\n  [{cat}]")
        for src, avg_score, count in ranked[:3]:
            print(f"    ✅ {src} — {avg_score:.1f}/10 ({count} articles)")

    print("\n💀 Pires sources par catégorie :")
    print("-" * 40)
    for cat in sorted(cat_sources.keys()):
        sources = cat_sources[cat]
        ranked = []
        for src, scores in sources.items():
            ranked.append((src, sum(scores) / len(scores), len(scores)))
        ranked.sort(key=lambda x: x[1])

        print(f"\n  [{cat}]")
        for src, avg_score, count in ranked[:3]:
            print(f"    ❌ {src} — {avg_score:.1f}/10 ({count} articles)")


if __name__ == "__main__":
    articles, total_raw = load_and_deduplicate()
    analyze(articles, total_raw)
