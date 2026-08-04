# Slide-bibliotek — sådan redigerer du det

Her ligger **alt statisk Epico-indhold** til pitch decket. Hver `.md`-fil er én slide.

Du behøver ikke kunne kode. Filerne er almindelig tekst og kan redigeres i enhver editor
(VS Code, Cursor, TextEdit, Notepad). Når du har gemt, hentes ændringen næste gang der
laves et pitch.

## Hvad er hvad

```
01-market/        Markedsargumenter — hvorfor fleksibel bemanding, hvad er det rette match
02-intro/         Om Epico — hvem vi er, tal, hvad kunden får
03-services/      De 6 services (Freelance, Projektansættelser, NextGen, Search, Public, Solution)
04-deep-dive/     Solution-specialer (Oracle, Mainframe, App-drift, Dataintegration, Cloud, SAP)
05-competencies/  Kompetenceområder og teknologier
06-process/       Procesbeskrivelser (fx Search' 10-trins forløb)
```

Filer der starter med `_` (som denne) medtages ikke i pitches.

## Filens opbygning

Øverst står en blok mellem `---` — det er slidens **indstillinger**:

```
---
id: freelance                  ← unikt navn (skift ikke uden grund)
title: Freelance               ← vises i slide-oversigten
category: services
length: [short, medium, long]  ← ved hvilke pitch-længder vises sliden?
services: [Epico Freelance]    ← vises kun hvis sælger har valgt denne service
stakeholders: []               ← tom = vises til alle stakeholder-typer
layout: service-detail         ← hvilket design (se listen nedenfor)
order: 32                      ← rækkefølge i decket (lavt tal = tidligere)
variant: light                 ← light | dark | red
section_tag: Freelance         ← teksten i slidens øverste højre hjørne
---
```

Nedenunder står **indholdet**, opdelt i sektioner der starter med `#`:

```
# eyebrow
SERVICE                          ← lille label over overskriften

# heading
Erfarne konsulenter **på 48 timer.**    ← **fed** bliver fremhævet i accentfarve

# subheading
En enkelt uddybende sætning.

# stats
+500 | konsulenter på kontrakt   ← format: VÆRDI | forklaring
+13.000 | CV'er i database

# bullets
Første punkt
Andet punkt

# cards
## Korttitel
Brødtekst til kortet
- punkt i kortet
- endnu et punkt
## Næste kort
Brødtekst

# footnote
Kilde: Årsrapport 2024
```

Brug kun de sektioner layoutet har brug for.

## De vigtigste indstillinger

### `length` — hvornår vises sliden?

| Værdi | Betyder |
|-------|---------|
| `[short, medium, long]` | Altid med |
| `[medium, long]` | Kun ved 30-45 min og 60+ min møder |
| `[long]` | Kun ved dybe 60+ min møder |

Aktuelt giver det: **kort ≈ 12 slides · medium ≈ 19 · lang ≈ 31** (inkl. kunde-slides).

### `services` — bind sliden til en service

- `services: []` → sliden vises altid (uafhængig af hvilke services sælger vælger)
- `services: [Epico Search]` → vises kun når Search er valgt
- `services: [Epico Solution]` → vises kun når Solution er valgt

Vælger sælger **ingen** services, viser systemet automatisk de første 2 (kort),
4 (medium) eller alle (lang).

### `layout` — designet

| Layout | Bruger sektionerne | Godt til |
|--------|--------------------|----------|
| `bullets` | eyebrow, heading, subheading, bullets | Simple punktlister |
| `stats-hero` | stats | 4-5 store tal (brug `variant: dark`) |
| `stats-plus-bullets` | stats + bullets | Tal med uddybende punkter |
| `cards-3` / `cards-4` / `cards-6` | cards | 3, 4 eller 6 kort |
| `service-detail` | stats + 2 cards | Service-slides (kort 1 = "Hvad I får", kort 2 = "Hvornår") |
| `competence-grid` | cards med bullets | Kompetencer med teknologier |
| `two-col` | body + bullets | Tekst til venstre, punkter til højre |
| `text-hero` | body | Ét stort citat eller udsagn |

## Sådan gør du

**Rette en tekst:** Åbn filen, ret teksten, gem. Færdig.

**Tilføje en slide:** Kopiér en eksisterende fil i den rigtige mappe, giv den nyt
`id`, ny `title` og et `order`-tal der placerer den hvor du vil have den.

**Fjerne en slide midlertidigt:** Sæt `length: []` — så vises den aldrig.
Filen bliver liggende så du kan tage den tilbage.

**Flytte en slide:** Ret `order`-tallet. Rækkefølgen i decket følger tallene.

## Efter du har rettet

Ændringen slår igennem ved næste pitch. Kører systemet allerede, kan du tvinge en
genindlæsning ved at kalde `POST /api/reload-knowledge` — eller bare genstarte det.

Både browser-versionen og PowerPoint-eksporten bruger de samme filer, så du
retter kun ét sted.

## Regler for indhold

- **Skriv på dansk.** Direkte og præcis, aktiv form.
- **Tal frem for adjektiver.** "+500 konsulenter" slår "mange konsulenter".
- **Undgå:** synergi, best-in-class, i verdensklasse, rejse, next-gen.
- **Kun tal vi kan stå inde for.** Se `backend/knowledge/stats.md` for de godkendte tal.
