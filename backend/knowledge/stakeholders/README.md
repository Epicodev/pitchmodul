# Stakeholder Knowledge

Disse filer fortæller Claude hvordan en pitch skal tilpasses afhængigt af **hvem sælgeren mødes med**. Hver fil beskriver:

- **Hvem stakeholderen er** (typiske titler)
- **Hvad de bekymrer sig om**
- **Hvad de IKKE bekymrer sig om** (kritisk — Claude må DROPPE indhold)
- **Hvilke slides der virker** (medtages / udelades)
- **Tone** der passer
- **Nøgletal** at fremhæve
- **Næste skridt** der appellerer
- **Eksempler på formuleringer** der virker

## Tilgængelige stakeholder-typer

| Key | Stakeholder | Når man bruger det |
|-----|-------------|---------------------|
| `procurement` | Procurement / Indkøb | RFP-svar, rammeaftaler, TCO-fokus |
| `it-leader` | CIO / IT-direktør | Teknisk dybde, stack-match |
| `hr-leader` | CHRO / HR-direktør | Talent-pipeline, kandidat-experience |
| `executive` | CEO / Board | Strategi, ROI, partnerskab |
| `cfo` | CFO / Økonomi | TCO, budgetforudsigelighed |
| `tech-lead` | Tech Lead / Engineering Manager | Hands-on teknisk credibility |
| `business-leader` | Forretningsleder / Department Head | Forretnings-outcome, branche-fit |

## Sådan opdaterer du

Hver `.md` er almindelig markdown. Rediger direkte i editor.

Vigtigst at holde opdateret:
- "Hvad de IKKE bekymrer sig om" → forhindrer Claude i at proppe pitchen
- "Næste skridt der appellerer" → påvirker slide 17 (Næste skridt)
- "Eksempler på formuleringer" → Claude bruger disse som inspiration til tone

## Tilføj en ny stakeholder

1. Lav ny `.md`-fil i denne mappe
2. Følg samme struktur som de eksisterende
3. Tilføj nøgle i `composer/index.html` (`<select>` med stakeholder-options)
4. Tilføj genkendelse i `backend/claude_client.py` (mapping fra key til filnavn)
