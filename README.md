# Journal personnalise - Daily Digest

Pipeline automatise qui genere chaque matin un journal personnalise a partir de flux RSS, filtre et resume par IA, puis deploye sur GitHub Pages et envoie un lien par email.

## Comment ca marche

```
RSS Feeds → Scraping → Filtrage LLM → Resume LLM → Page HTML → GitHub Pages + Email
```

1. **Scraping** : recupere les articles des dernieres 24h depuis les flux RSS configures dans `config/feeds.yaml`
2. **Filtrage** : un LLM (Llama via Groq) score chaque article selon un profil lecteur, avec des quotas par categorie
3. **Resume** : un second appel LLM genere un resume en francais de chaque article selectionne
4. **HTML** : genere une page dark theme avec les articles groupes par categorie
5. **Deploiement** : push sur GitHub Pages + envoi d'un email avec le lien

## Fonctionnalites

- **Quotas par categorie** : nombre d'articles configurable par theme (ex: 5 tech, 3 cinema, 3 musique...)
- **Notation des articles** : boutons 1-10 dans le digest, les notes sont enregistrees dans un Google Sheet via webhook
- **Bouton Spotify** : pour les articles musique, lien direct vers l'artiste sur Spotify
- **Bouton Letterboxd** : pour les articles cinema, lien direct vers le film sur Letterboxd
- **Historique** : chaque digest est archive dans `archive/` sur GitHub Pages. Pour acceder a un ancien digest, utiliser l'URL : `https://TON_USER.github.io/TON_REPO/archive/AAAA-MM-JJ.html` (ex: `https://enriquealves02-jpg.github.io/projet_PODCAST_perso/archive/2026-03-19.html`)

## Installation

### Prerequis

- Python 3.12+
- Un compte [Groq](https://console.groq.com) (gratuit)
- Un compte Gmail avec un [App Password](https://myaccount.google.com/apppasswords)
- Un repo GitHub avec GitHub Pages active

### Setup local

```bash
git clone https://github.com/TON_USER/TON_REPO.git
cd TON_REPO
python -m venv venv
venv/Scripts/activate        # Windows
# source venv/bin/activate   # Mac/Linux
pip install -r requirements.txt
```

Creer un fichier `.env` a la racine (voir `.env.example`) :

```
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxx
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=ton.email@gmail.com
EMAIL_PASSWORD=xxxx xxxx xxxx xxxx
EMAIL_TO=ton.email@gmail.com
RATING_WEBHOOK_URL=https://script.google.com/macros/s/xxx/exec
```

### Obtenir les cles

| Variable | Comment l'obtenir |
|---|---|
| `GROQ_API_KEY` | [console.groq.com/keys](https://console.groq.com/keys) - creer un compte gratuit puis "Create API Key" |
| `EMAIL_PASSWORD` | [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) - activer la 2FA puis generer un App Password |
| `RATING_WEBHOOK_URL` | Creer un Google Sheet + Apps Script (voir section ci-dessous) |

### Configurer le systeme de notation (optionnel)

1. Creer un Google Sheet avec les colonnes : `date`, `title`, `source`, `category`, `url`, `score`, `rated_at`
2. Aller dans Extensions > Apps Script
3. Coller le code de `docs/google_apps_script.js`
4. Deployer > Nouveau deploiement > Application Web > Acces : Tout le monde
5. Copier l'URL du deploiement dans `RATING_WEBHOOK_URL`

### Lancer en local

```bash
# Test sans envoi de mail
python main.py --dry-run

# Run complet avec envoi de mail
python main.py
```

Le digest genere est dans `data/digest.html`.

### Deploiement automatique (GitHub Actions)

1. Push le repo sur GitHub
2. Ajouter les secrets dans Settings > Secrets and variables > Actions :
   - `GROQ_API_KEY`, `SMTP_HOST`, `SMTP_PORT`, `EMAIL_USER`, `EMAIL_PASSWORD`, `EMAIL_TO`, `RATING_WEBHOOK_URL`
3. Activer GitHub Pages : Settings > Pages > Branch : `gh-pages` > Save
4. Le workflow tourne automatiquement tous les jours a 5h UTC (7h Paris ete / 6h hiver)
5. Lancement manuel possible depuis l'onglet Actions > Daily Digest > Run workflow

## Personnalisation

### Modifier les sources RSS

Editer `config/feeds.yaml` pour ajouter/supprimer des flux par categorie.

### Modifier le profil lecteur et les criteres de filtrage

Editer `config/prompts.yaml` :
- `user_profile` : decrit les gouts et interets du lecteur
- `filter_system_prompt` : criteres de scoring par categorie
- `summarize_system_prompt` : style et format des resumes

### Modifier les quotas par categorie

Editer `src/filter.py` : dictionnaire `CATEGORY_QUOTAS`.

## Structure du projet

```
├── config/
│   ├── feeds.yaml          # Sources RSS par categorie
│   └── prompts.yaml        # Prompts LLM (profil, filtrage, resume)
├── src/
│   ├── scraper.py          # Scraping RSS
│   ├── scrapers_custom.py  # Scrapers HTML custom (ex: Cahiers du Cinema)
│   ├── filter.py           # Filtrage LLM avec quotas
│   ├── summarizer.py       # Resume LLM
│   ├── email_builder.py    # Generation HTML
│   └── sender.py           # Envoi email
├── templates/
│   └── digest.html         # Template Jinja2 du digest
├── .github/workflows/
│   └── daily_digest.yml    # GitHub Actions (cron + deploy)
├── docs/
│   └── google_apps_script.js  # Script pour le systeme de notation
├── main.py                 # Orchestrateur principal
└── sources.txt             # Liste des sources par theme
```

## Couts

Tout est gratuit :
- **Groq API** : 100k tokens/jour gratuits (suffisant pour ~200 articles)
- **Gmail SMTP** : gratuit
- **GitHub Actions** : 2000 min/mois (repos publics)
- **GitHub Pages** : gratuit (repos publics)
