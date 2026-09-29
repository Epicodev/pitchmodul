# Pitch Composer i Microsoft Copilot — opsætningsguide

Denne guide sætter Pitch Composer op som agent i Microsoft Copilot Studio, så sælgere kan skrive fx *"Lav et pitch deck til Brøndby IF på engelsk med freelance og search"* direkte i Teams og få et link til det færdige deck.

Guiden har to dele: **Del 1** gør Benjamin (5 minutter), **Del 2** gør jeres Microsoft 365-admin i Copilot Studio (ca. 30 minutter).

---

## Del 1: Aktivér agent-API'et (Benjamin)

Agent-API'et er slået fra indtil der er sat en API-nøgle på serveren.

1. Lav en nøgle. Kør denne kommando i Terminal og kopiér resultatet:

```bash
openssl rand -hex 24
```

2. Gå til [Railway](https://railway.app) → projektet **pacific-essence** → servicen **web** → fanen **Variables**.
3. Tilføj en ny variabel:
   - Navn: `PITCH_AGENT_API_KEY`
   - Værdi: nøglen fra trin 1
4. Railway genstarter selv servicen. Tjek at det virker:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://web-production-cb233.up.railway.app/agent/catalogue
```

Svarer den `401` er alt som det skal være (nøglen kræves nu). Svarer den `503` mangler variablen stadig.

5. Send nøglen og denne guide til jeres M365-admin — **gerne via en sikker kanal**, ikke almindelig mail.

---

## Del 2: Opsæt agenten i Copilot Studio (M365-admin)

### Forudsætninger
- Adgang til [Copilot Studio](https://copilotstudio.microsoft.com) med licens til at oprette agenter
- API-nøglen fra Del 1

### Trin 1: Opret agenten

1. Copilot Studio → **Create** → **New agent** (spring "Describe"-flowet over, vælg **Configure**).
2. Navn: `Epico Pitch Composer`
3. Beskrivelse: `Genererer Epico pitch decks til kundemøder ud fra kundenavn, sprog og sælgers brief.`
4. Indsæt følgende under **Instructions**:

```
Du hjælper Epicos sælgere med at generere pitch decks. Du taler dansk.

SÅDAN ARBEJDER DU:
1. Kald altid /catalogue først, så du kender gyldige sprog, services, stakeholdere og slides.
2. Spørg sælgeren om det du mangler: kundenavn, sprog (dansk/engelsk), services og gerne et kort brief om mødet (hvem mødes de med, hvad ved de, hvad vil de opnå).
3. HURTIGT DECK (intet brief / travlt): kald /master-deck. Svar med linket med det samme.
4. SKRÆDDERSYET DECK (sælger har et brief): kald /research med sælgers brief i 'brief'-feltet. Sig at researchen tager 4-5 minutter, og at de kan spørge "er den færdig?" undervejs.
5. Når sælgeren spørger til status: kald /research/{job_id}. Ved status 'done': kald /deck-from-research og svar med linket.
6. Svar ALTID med deck-linket som et klikbart link, og nævn at decket åbner i browseren og kan præsenteres direkte derfra.

REGLER:
- Brug service-navnene ordret fra /catalogue (fx "Epico Freelance", "Epico Search").
- Skriv aldrig lange tankestreger (— eller –) i dine svar.
- Finder du på fejl eller får fejlsvar fra API'et, så vis fejlbeskeden ærligt til sælgeren.
```

### Trin 2: Tilføj API'et som værktøj

1. I agenten: **Tools** (eller **Actions**) → **Add a tool** → **New tool** → **REST API**.
2. Import: angiv URL'en til OpenAPI-beskrivelsen:
   `https://web-production-cb233.up.railway.app/agent/openapi.json`
3. Authentication: vælg **API key**
   - Placering: **Header**
   - Header-navn: `X-Api-Key`
   - Værdi: API-nøglen fra Del 1
4. Vælg alle fem operationer (catalogue, master-deck, research, research-status, deck-from-research) og gennemfør guiden.

### Trin 3: Test

I test-panelet i Copilot Studio, prøv:

> Lav et pitch deck til Brøndby IF på engelsk med freelance og search

Agenten skal svare med et link til et deck på `web-production-cb233.up.railway.app/generated/...`. Åbn linket og tjek at decket viser kundens navn på forsiden.

Prøv derefter den skræddersyede vej:

> Lav et skræddersyet pitch til Brøndby IF. Jeg skal møde IT-chefen, de bygger ny fanplatform og mangler tekniske specialister.

Agenten starter research og beder dig vente. Spørg "er den færdig?" efter 5 minutter — så leverer den linket.

### Trin 4: Udgiv til Teams

1. **Channels** → **Microsoft Teams** → aktivér.
2. **Publish**.
3. Del agenten med salgsteamet (eller hele organisationen) via **Availability options**.

---

## Teknisk reference

| Endpoint | Metode | Formål |
|---|---|---|
| `/agent/catalogue` | GET | Gyldige sprog, services, stakeholdere og slides |
| `/agent/plan` | GET | Slide-plan (forvalg, kapitler) for `pitch_length` og `services` |
| `/agent/slides/{id}/thumbnail` | GET | Miniature af en masterslide, JPEG 640x360 |
| `/agent/slides/{id}/preview` | GET | Én masterslide som selvstændig HTML-side |
| `/agent/deck/pdf` | POST | Masterdeck som PDF, én side per slide (kræver Chromium) |
| `/agent/master-deck` | POST | Hurtigt masterdeck med kundens navn (klar med det samme) |
| `/agent/research` | POST | Start AI-research (4-5 min, svarer med job_id) |
| `/agent/research/{job_id}` | GET | Status på research |
| `/agent/deck-from-research` | POST | Generér skræddersyet deck fra færdig research |

- Alle kald kræver headeren `X-Api-Key`.
- OpenAPI-beskrivelsen på `/agent/openapi.json` er åben (den indeholder ingen hemmeligheder) så den kan importeres direkte.
- Mistes nøglen eller skal den skiftes: opdatér `PITCH_AGENT_API_KEY` i Railway og i Copilot Studio-værktøjets authentication. Gamle nøgler virker ikke efter skiftet.
- Research-jobs lever i serverens hukommelse: genstarter Railway midt i en kørsel, skal researchen startes forfra. Det er et kendt vilkår, ikke en fejl.
