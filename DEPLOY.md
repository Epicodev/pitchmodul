# Deployment til Railway

Trin-for-trin guide til at få Pitch Composer live.

## 1. Push til GitHub

Repo'et ligger på `Epicodev/pitchmodul`. Hvis du ikke allerede har pushed:

```bash
cd epico-pitch-deck
git init
git add .
git commit -m "Initial pitch composer"
git branch -M main
git remote add origin https://github.com/Epicodev/pitchmodul.git
git push -u origin main
```

## 2. Opret Railway-projekt

1. Gå til [railway.com](https://railway.com) og log ind
2. Klik **"New Project"** → **"Deploy from GitHub repo"**
3. Vælg `Epicodev/pitchmodul`
4. Railway begynder automatisk at builde ud fra `Dockerfile.chromium` i roden (se afsnittet om Chromium nedenfor)

## 3. Sæt miljøvariabler

I Railway-projektets **Variables**-tab:

| Variabel | Værdi |
|----------|-------|
| `ANTHROPIC_API_KEY` | Din Claude API-key (sk-ant-api03-...) |

Railway sætter automatisk `$PORT` — du behøver ikke gøre noget.

## 4. Tjek deployment

Railway giver dig en URL som `pitchmodul-production.up.railway.app`.

Test:
- `https://[din-url]/api/health` → skal returnere `{"status":"ok","anthropic_key_set":true,...}`
- `https://[din-url]/` → skal vise composer-UI'en

## 5. Chromium, Docker og rollback til Nixpacks

PDF (`POST /agent/deck/pdf`) og miniaturer (`render_thumbs.py`) renderes med
Playwright/Chromium. Chromium findes ikke i Nixpacks' standard-image, derfor
bygger Railway nu fra `Dockerfile.chromium` i roden (`railway.toml`: `builder = "DOCKERFILE"`).
Basisimaget er `mcr.microsoft.com/playwright/python:v1.63.0-jammy`, og
`playwright==1.63.0` i `requirements.txt` skal matche tag'et. Opgraderes den ene,
opgraderes den anden.

Healthcheck (`/api/health`) og start-kommando er de samme som foer.

### Rul tilbage til Nixpacks hvis Docker-buildet fejler

1. Ret `railway.toml`:

   ```toml
   [build]
   builder = "NIXPACKS"
   ```

   (fjern eller udkommentér `dockerfilePath`). Resten af filen er uaendret.
2. Push til `main`. Railway bygger igen med Nixpacks som foer.
3. Konsekvens: `POST /agent/deck/pdf` svarer `503 {"detail": "PDF kræver Chromium på serveren"}`.
   Alt andet virker, ogsaa miniaturerne, fordi de er renderet paa forhaand og
   ligger i repoet (`backend/master_deck/{da,en}/thumbs/`).

Vil man beholde Nixpacks permanent, kan `playwright` blive staaende i
`requirements.txt`; pakken installeres fint uden browser, og importen sker
foerst inde i PDF-kaldet.

### Miniaturer lokalt (efter ny masterfil)

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/playwright install chromium
cd backend && ../.venv/bin/python import_master.py "/sti/til/Epico Salgsdeck DK.html" --lang=da
```

`import_master.py` renderer miniaturerne som sidste trin. Mangler Chromium,
skriver den en advarsel, og `python render_thumbs.py --lang=da` kan koeres
bagefter. Miniaturerne committes sammen med de nye slides.

## 6. (Valgfrit) Custom domain

I Railway → Settings → Networking → Custom Domain.
Pege fx `pitch.epico.dk` til Railway's CNAME.

---

## Struktur Railway ser

```
/
├── Dockerfile.chromium                Playwright-image med Chromium (builder på Railway)
├── Procfile                  Start-kommando (bruges kun ved Nixpacks)
├── railway.toml              Builder, healthcheck + restart policy
├── requirements.txt          Python deps (Nixpacks finder denne automatisk)
├── runtime.txt               Python 3.12
├── .gitignore                Holder venv/, .env, generated/ ude af repo
├── backend/                  FastAPI app
│   ├── main.py
│   ├── claude_client.py
│   ├── cvr.py
│   ├── pdf_reader.py
│   ├── deck_gen.py
│   ├── knowledge_loader.py
│   ├── knowledge/            Markdown-vidensbase
│   └── templates/            Jinja2 deck template
├── composer/                 Frontend (serveres af FastAPI)
│   ├── index.html
│   ├── composer.css
│   └── composer.js
├── index.html, styles.css, app.js   Master deck assets
└── assets/
```

## Lokal udvikling vs. Railway

| | Lokal | Railway |
|---|-------|---------|
| Port | 8000 | `$PORT` (Railway sætter denne) |
| Host | 127.0.0.1 | 0.0.0.0 (alle interfaces) |
| API-key | `backend/.env` | Railway Variables |
| Generated decks | `backend/generated/` | Ephemeral disk (forsvinder ved deploy) — overvej S3 hvis I vil bevare dem |
| Hot reload | `--reload` flag | Nej, restart ved push til main |

## ⚠️ Vigtigt om persistens

Railway's filsystem er **ephemeral** — alle filer i `generated/` forsvinder hver gang appen genstarter (fx ved næste deploy). Hvis I vil bevare genererede pitches på tværs af deploys, skal vi tilføje:

- **S3 / Cloudflare R2** til at gemme HTML-filer
- **Postgres** til at logge "hvilke pitches er genereret hvornår, til hvilken kunde"

Indtil videre er det fint — sælgeren downloader bare HTML'en og gemmer den lokalt.

## Fejlfinding

**Build fejler:**
- Tjek logs i Railway → Deployments → klik på den fejlede deployment → "Build Logs"
- Mest sandsynlige årsag: en pakke i `requirements.txt` virker ikke med Python 3.12

**App svarer ikke:**
- Tjek "Deploy Logs" — er der startup-fejl?
- Verificér at `ANTHROPIC_API_KEY` er sat i Variables
- Test `/api/health` først

**Composer UI vises ikke:**
- Tjek browser console — er der CORS-fejl?
- Tjek at `/composer-assets/composer.css` returnerer 200

**Claude returnerer fejl:**
- Tjek backend-logs for stack trace
- Mest sandsynligvis: API-key ugyldig, eller knowledge-filer mangler i deploy

---

## Næste skridt efter deploy

1. **Custom domain** (`pitch.epico.dk` eller `composer.epico.dk`)
2. **Auth** — Lige nu er API'en åben. Vi bør tilføje login før den går i produktion (Google SSO via Cloudflare Access, eller HTTP Basic Auth som start)
3. **Persistens** — Hvis sælgerne vil have historik, gem til Postgres/S3
4. **Rate limiting** — beskyt mod misbrug af /api/research-endpointet (Claude koster penge pr. kald)
