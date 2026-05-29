# Epico Knowledge Base

Denne mappe indeholder al fakta-viden om Epico som AI'en (Claude) bruger til at generere skræddersyede pitch decks.

**Reglen er enkel: Claude må kun bruge information der findes i denne mappe.** Hvis et faktum ikke står her, må Claude ikke finde på det.

## Struktur

```
knowledge/
├── services/         Detaljerede beskrivelser af hver af de 7 services
├── cases/            Rigtige cases per branche (med kunde-navn hvor offentligt)
├── boundaries.md     Det Epico IKKE leverer (forhindrer hallucinationer)
├── messaging.md      Tone of voice, sprog vi bruger og undgår, CTAs
├── stats.md          Aktuelle nøgletal — KUN disse må citeres
└── README.md         Denne fil
```

## Sådan opdaterer du knowledge base

1. **Åbn den relevante .md-fil** i en teksteditor (VS Code, Cursor, Sublime, etc.)
2. **Rediger teksten** direkte — markdown er bare almindelig tekst
3. **Gem filen**
4. **Genstart backend** (eller restart hot-reload sker automatisk hvis uvicorn kører i `--reload`-mode)
5. Næste pitch-generering bruger den opdaterede viden

## Markører i indholdet

Du vil se nogle markører jeg har lagt ind:

- `[VERIFICÉR]` — Tal eller fakta jeg har gættet på baseret på master ppt. Bør tjekkes og opdateres med rigtige tal.
- `[VERIFICÉR — beskrivelse]` — En specifik ting der mangler bekræftelse.

Søg efter "VERIFICÉR" i mappen og opdater alle stederne.

## Hvad må Claude bruge / ikke bruge

**Claude MÅ:**
- Citere alle tal fra `stats.md`
- Referere til services i `services/`
- Bruge cases fra `cases/` som inspiration til "relevant case"-slide
- Følge tone of voice fra `messaging.md`
- Henvise til boundaries-reglerne i `boundaries.md`

**Claude MÅ IKKE:**
- Lave nye tal op (selv hvis det "lyder rigtigt")
- Finde på kundenavne eller referencer
- Foreslå services der ikke findes (fx "Epico Cloud" eller "Epico AI Strategy")
- Bryde tone of voice (fx bruge "synergi", "best-in-class")
- Foreslå outsourcing til Asien (mod boundaries.md)

## Sådan tilføjer du en ny case

Lav en ny fil i `cases/`, fx `cases/finance.md`. Brug samme struktur som de andre case-filer:

```markdown
# Case: [Branche/Kunde] — [Headline]

## Branche
[Tag — bruges til auto-matching]

## Headline
[1 sætning der opsummerer casen]

## Hvad (situation)
- [Bulletpoints om situationen]

## Hvorfor (driver)
- [Hvad var driveren for kunden]

## Resultat
- [Konkrete tal og leverancer]

## Værdi (for kunden)
- [Hvad fik kunden ud af det]

## Hvilke Epico-services var i spil
- [Service-navne]

## Hvorfor case er relevant
[Når kundens situation matcher ...]
```

## Sådan tilføjer du en ny service

[VERIFICÉR — Hvis Epico lancerer en ny service]

Lav en ny fil i `services/`, brug samme template-struktur som de eksisterende. Husk også at opdatere:
- `backend/claude_client.py` → `EPICO_SERVICES` dict
- `composer/index.html` → tilføj chip i pitch-vinkel sektionen
- `backend/templates/pitch.html.j2` → tilføj slide for den nye service hvis relevant

## Spørgsmål?

Kontakt [VERIFICÉR — den person hos Epico der ejer denne knowledge base].
