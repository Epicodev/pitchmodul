# Epico Master Pitch Deck

Bold, moderne 18-slides salgs-pitch på dansk, bygget i HTML/CSS efter Epico Brand Guide (Januar 2026).

Dette er **master-templaten**. Den senere AI-modul vil tage denne template og fylde de klient-specifikke felter ind automatisk (på baggrund af årsrapport-research).

---

## Hurtig start

```bash
cd epico-pitch-deck
python3 -m http.server 4321
```

Åbn så: **http://localhost:4321**

### Tastatur

| Tast | Handling |
|------|----------|
| `→` / `Space` / `PageDown` | Næste slide |
| `←` / `PageUp` | Forrige slide |
| `Home` / `End` | Første / sidste slide |
| `P` | Toggle præsentationsmode (fullscreen) |
| `Esc` | Ud af præsentationsmode |
| `Cmd + P` | Eksportér til PDF |

---

## Struktur (18 slides)

| # | Slide | Type | Klient-specifik? |
|---|-------|------|------------------|
| 01 | Cover: `[KUNDE] × Epico` | Dark | ✅ |
| 02 | Hvorfor vi mødes | Light | ✅ |
| 03 | Agenda | Light | — |
| 04 | **We've done our homework** (4 research-facts) | Light | ✅ |
| 05 | **3 strategiske prioriteter** | Light | ✅ |
| 06 | **Jeres udfordring → vores håndtag** (mapping) | Light | ✅ |
| 07 | Kapitel-divider: "Dette er Epico" | Dark | — |
| 08 | Epico i tal (stats hero) | Dark | — |
| 09 | DK's IT-marked (facts) | Light | — |
| 10 | Vores DNA (4 tiles) | Light | — |
| 11 | Kapitel-divider: "Det vi leverer" | Red | — |
| 12 | Services: Freelance + NextGen | Light | — |
| 13 | Services: Search + Public | Light | — |
| 14 | Services: Nearshore + Tech + Dynamant + Brancher | Light | — |
| 15 | The Epic Process (7 trin) | Light | — |
| 16 | **Relevant case fra deres branche** | Light | ✅ |
| 17 | **Næste skridt** (3 konkrete) | Light | ✅ |
| 18 | Kontakt — KAM + Resource Manager | Dark | ✅ |

**Klient-specifikke slides** (markeret med ✅) er der hvor jeres senere AI-modul fylder klient-research ind.

---

## Tilpasning til en specifik kunde (manuelt — indtil AI-modulet er bygget)

Søg-erstat i `index.html`:

| Placeholder | Erstat med |
|-------------|------------|
| `[KUNDE]` | Kundens navn |
| `[BRANCHE]` | Kundens branche |
| `[KONTAKTPERSON]` | Mødedeltager hos kunden |
| `[BYNAVN]` | Hvor mødet holdes |
| `[DATO]` | Mødedato |
| `[X mia. DKK]` | Omsætning fra årsrapport |
| `[X.XXX]` | Medarbejdertal |
| `[Prioritet 1 ...]` etc. | Strategi-punkter fra CEO-brev |
| `[Konkret udfordring 1 ...]` etc. | Mapping-cellerne |
| `[Fornavn Efternavn]` | Sælger-navne |

---

## Eksportér til PDF

1. Åbn `index.html` i Chrome / Edge / Safari
2. Tryk `Cmd + P` (Mac) eller `Ctrl + P` (Windows)
3. Vælg:
   - **Layout:** Landscape
   - **Margins:** None
   - **Background graphics:** Slået til (vigtigt — ellers forsvinder dark slides)
   - **Pages per sheet:** 1
4. Gem som PDF

PDF'en bliver 1920×1080 px per side (perfekt 16:9).

---

## Brand-overholdelse

Alt design følger Epico Brand Guide:

- ✅ Skarpe hjørner overalt (kun 2px på badges)
- ✅ Kun de 13 brand-farver (CSS-variabler i top af `styles.css`)
- ✅ Suisse Int'l Bold til overskrifter (DM Sans Bold med `-0.03em` letter-spacing som fallback)
- ✅ DM Sans Regular til brødtekst
- ✅ Mosaic-grid med 2px gap mellem tiles
- ✅ Hero-baggrund: Black Currant `#1B1B50`
- ✅ Primær side-baggrund: Raw Silk `#FFFCF2`
- ✅ Kiwi `#4CE17F` kun som accent / CTA på dark slides
- ✅ Det nye E-bomærke (ikke det gamle fugl-logo)

---

## Filer

```
epico-pitch-deck/
├── index.html         18 slides
├── styles.css         Design tokens + components + slide layouts
├── app.js             Navigation, keyboard, præsentationsmode, print
├── assets/
│   └── e-mark.svg     Standalone E-bomærke til ekstern brug
└── README.md          Denne fil
```

E-bomærket er inline i `index.html` som CSS-bygget div (matcher brand guide nøjagtigt), så det skalerer perfekt uden eksterne assets.

---

## Forberedelse til AI-modulet (sælger-flow)

Når I bygger sælger-modulet senere, skal det:

1. Tage `index.html` som template
2. Tage en kundes navn + årsrapport som input
3. Lade Claude:
   - Læse årsrapporten og uddrage 4 nøgletal → slide 4
   - Identificere 3 strategiske prioriteter fra CEO-brev → slide 5
   - Mappe 4 sandsynlige IT-udfordringer til Epico-services → slide 6
   - Vælge den mest relevante case ud fra branche → slide 16
   - Forslå 3 konkrete næste skridt → slide 17
4. Erstatte placeholders med genereret tekst
5. Spytte en færdig HTML-fil ud (klar til at åbne / eksportere som PDF)

Alle de klient-specifikke felter er bevidst placeret med `[FIRKANTET PARENTES]` så de er nemme at finde og erstatte programmatisk.

---

## Næste skridt for designet

Hvis I vil gå videre:

1. **Tilføj rigtige fotos** — i øjeblikket bruger templaten ingen stock-fotos (mere ærligt og mindre genericisk). I kan tilføje Epico-fotografi til specifikke slides hvis det giver mening.
2. **Klient-logo på cover** — lige nu er det bare "[KUNDE]" i tekst. AI-modulet kan hente logo via Clearbit eller lignende.
3. **Animations** — der er allerede subtle hover-effekter. Kan udvides med slide-transition.
4. **Multi-sprog** — let at tilføje engelsk version ved at duplikere indholdet i `content.js` med dansk/engelsk varianter.

---

Bygget med Claude · Januar 2026
