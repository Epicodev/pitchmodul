"""
Claude API client.
Analyserer årsrapport + CVR-data og returnerer struktureret data
til de 5 klient-specifikke slides i pitch decket.
"""
import os
import json
from typing import Optional, Dict, Any, List
from anthropic import Anthropic

from knowledge_loader import load_knowledge


# Bruger den nyeste Sonnet model
MODEL = "claude-sonnet-4-6"


# Cache knowledge base i memory (loades én gang per proces)
_KNOWLEDGE_CACHE: Optional[str] = None


def _get_knowledge() -> str:
    """Load knowledge base lazy + cache i memory."""
    global _KNOWLEDGE_CACHE
    if _KNOWLEDGE_CACHE is None:
        _KNOWLEDGE_CACHE = load_knowledge()
    return _KNOWLEDGE_CACHE


def reload_knowledge() -> int:
    """Force-reload knowledge fra disk. Returnér total chars."""
    global _KNOWLEDGE_CACHE
    _KNOWLEDGE_CACHE = load_knowledge()
    return len(_KNOWLEDGE_CACHE)


# Kort service-oversigt (fallback hvis knowledge-base fejler).
# Detaljerne ligger nu i knowledge/services/*.md
EPICO_SERVICES = {
    "Epico Freelance": "Hurtig levering af erfarne IT-konsulenter (+10 års erfaring).",
    "Epico NextGen": "Nyuddannede IT-talenter (0-2 års erfaring). Try-before-hire model.",
    "Epico Search": "Headhunting af IT-ledere og specialister til faste stillinger.",
    "Epico Public": "Specialister i offentlige rammeaftaler (SKI). Sikkerhedsclearance håndteret.",
    "Epico Nearshore": "Dedikerede teams i Polen, ledet fra Danmark.",
    "Epico Tech": "Oracle, AI, AMS og Managed Technology specialister.",
    "Epico Dynamant": "Mainframe og Cobol specialister.",
}


# Tool schema som Claude skal returnere data i
ANALYSIS_TOOL = {
    "name": "deliver_pitch_research",
    "description": "Returnér struktureret research om kunden, klar til at indsætte i pitch deck.",
    "input_schema": {
        "type": "object",
        "properties": {
            "client_summary": {
                "type": "string",
                "description": "1-2 sætninger der opsummerer hvem kunden er og deres nuværende situation. Brug på cover-slide.",
            },
            "industry_tag": {
                "type": "string",
                "description": "Branchekategori. Vælg én: Medtech, Pharma, Biotech, Finans, Energi, Forsyning, Retail, Public, Industri, Tech, Telco, Transport, Andet.",
            },
            "research_facts": {
                "type": "array",
                "description": "Nøjagtigt 4 fakta om kunden, der demonstrerer at vi har gjort research. Brug konkrete tal fra årsrapport hvor muligt.",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Kort label, fx 'Omsætning seneste regnskabsår' eller 'Strategisk fokus'."
                        },
                        "value": {
                            "type": "string",
                            "description": "Konkret tal eller kort tekst. Fx '24,2 mia. DKK' eller 'Digital transformation + ESG'."
                        },
                        "source": {
                            "type": "string",
                            "description": "Kildehenvisning, fx 'Årsrapport 2024, s. 12' eller 'CEO-brev'."
                        },
                    },
                    "required": ["key", "value", "source"],
                },
                "minItems": 4,
                "maxItems": 4,
            },
            "strategic_priorities": {
                "type": "array",
                "description": "Nøjagtigt 3 strategiske prioriteter som vi læser dem fra årsrapporten/CEO-brev. Vær konkret og kobl til IT/digitalisering hvor muligt.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Kort titel, max 60 tegn. Fx 'Accelerere digital transformation'."
                        },
                        "description": {
                            "type": "string",
                            "description": "1-2 sætninger der uddyber prioriteten med specifik reference til hvad kunden selv har skrevet."
                        },
                    },
                    "required": ["title", "description"],
                },
                "minItems": 3,
                "maxItems": 3,
            },
            "value_mappings": {
                "type": "array",
                "description": "Nøjagtigt 4 mappings mellem konkret kundeudfordring og specifik Epico-service.",
                "items": {
                    "type": "object",
                    "properties": {
                        "challenge": {
                            "type": "string",
                            "description": "Konkret udfordring kunden står med, baseret på research. Vær specifik."
                        },
                        "epico_service": {
                            "type": "string",
                            "description": "Hvilken Epico-service løser dette: Epico Freelance, Epico NextGen, Epico Search, Epico Public, Epico Nearshore, Epico Tech eller Epico Dynamant."
                        },
                        "solution": {
                            "type": "string",
                            "description": "Hvordan løser denne service udfordringen — konkret formulering."
                        },
                    },
                    "required": ["challenge", "epico_service", "solution"],
                },
                "minItems": 4,
                "maxItems": 4,
            },
            "next_steps": {
                "type": "array",
                "description": "Nøjagtigt 3 konkrete næste skridt skræddersyet til kunden.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Kort handlingsorienteret titel."
                        },
                        "description": {
                            "type": "string",
                            "description": "1-2 sætninger der beskriver skridtet konkret."
                        },
                        "when": {
                            "type": "string",
                            "description": "Tidsramme, fx 'Inden for 14 dage'."
                        },
                    },
                    "required": ["title", "description", "when"],
                },
                "minItems": 3,
                "maxItems": 3,
            },
            "case_recommendation": {
                "type": "object",
                "description": "En foreslået case at vise — bygget på relevans til kundens branche.",
                "properties": {
                    "headline": {
                        "type": "string",
                        "description": "Slagkraftig case-overskrift, max 80 tegn."
                    },
                    "intro": {
                        "type": "string",
                        "description": "1-2 sætninger der opsummerer hvorfor denne case er relevant for kunden."
                    },
                    "what": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "3 bullets der beskriver hvad samarbejdet bestod af.",
                    },
                    "why": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "3 bullets der beskriver hvorfor kunden havde brug for hjælp.",
                    },
                    "result": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "3 bullets der beskriver konkrete resultater.",
                    },
                    "value": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "3 bullets der beskriver værdien for kunden.",
                    },
                },
                "required": ["headline", "intro", "what", "why", "result", "value"],
            },
        },
        "required": [
            "client_summary",
            "industry_tag",
            "research_facts",
            "strategic_priorities",
            "value_mappings",
            "next_steps",
            "case_recommendation",
        ],
    },
}


_EMPHASIS_DESCRIPTIONS = {
    "speed": "Sælger vil have pitchen til at lægge ekstra vægt på **hastighed og leveringskraft**. Fremhæv Epico's 48t-responstid, hurtige onboarding, og evne til at skalere op på få dage.",
    "expertise": "Sælger vil have pitchen til at lægge ekstra vægt på **specialisterfaring**. Fremhæv +20 års gennemsnitserfaring, nicheskompetencer, og dybde frem for bredde.",
    "cost": "Sælger vil have pitchen til at lægge ekstra vægt på **skalering uden vækst i fast lønsum**. Fremhæv konsulent-modellen, fleksibilitet, og Nearshore som omkostningsoptimering.",
    "local": "Sælger vil have pitchen til at lægge ekstra vægt på **lokal/dansk kontekst**. Fremhæv at Epico er dansk, kender det danske arbejdsmarked, har dansk juridisk setup, og forstår SKI-aftaler.",
    "culture": "Sælger vil have pitchen til at lægge ekstra vægt på **kultur- og team-fit**. Fremhæv at Epico matcher på personlighed og kommunikation, ikke kun CV. Personlig KAM-relation, ingen ticket-systemer.",
}


def _build_system_prompt(
    pitch_focus: Optional[str] = None,
    services_to_highlight: Optional[List[str]] = None,
    emphasis: Optional[str] = None,
) -> str:
    # Sælger-direktiver — disse er styrende
    directives = []

    if pitch_focus:
        directives.append(f"""## ⚠️ SÆLGERS PITCH-VINKEL (styrende)

Sælgeren har angivet følgende fokus for denne pitch:

> {pitch_focus}

**Dette overstyrer alt andet.** Alle dine valg — research-facts, strategiske prioriteter, value-mappings, case-anbefaling og næste skridt — SKAL understøtte denne vinkel.

Du må gerne **nedprioritere temaer fra årsrapporten**, selvom de er interessante, hvis de ikke understøtter sælgers fokus. Hellere skarpere end mere komplet. Hellere fire fakta der peger samme vej end fire fakta der spreder sig.""")

    if services_to_highlight:
        services_str = ", ".join(services_to_highlight)
        directives.append(f"""## ⚠️ SERVICES AT FREMHÆVE (styrende)

Sælgeren har valgt at fremhæve følgende services i pitch'en:

> {services_str}

Dine `value_mappings` skal **primært** mappe kundens udfordringer til DISSE services. Hvis sælgeren har valgt færre end 4 services, må du gerne bruge samme service flere gange (forskellige aspekter af det). Inkludér IKKE services sælgeren ikke har valgt, medmindre det er strengt nødvendigt for at undgå kunstig tvang.""")

    if emphasis and emphasis in _EMPHASIS_DESCRIPTIONS:
        directives.append(f"""## ⚠️ EKSTRA VÆGT (styrende)

{_EMPHASIS_DESCRIPTIONS[emphasis]}

Lad dette farve dine formuleringer og prioritering — særligt i `value_mappings.solution` og `next_steps`.""")

    directive_block = "\n\n".join(directives) if directives else "## Frihed til at vælge\n\nSælgeren har ikke angivet specifik retning. Brug din bedste dømmekraft baseret på årsrapport og CVR-data."

    # Knowledge base — hele Epico's vidensbase
    knowledge = _get_knowledge()

    return f"""Du er en strategisk analytiker hos Epico, et af Nordens største IT-konsulenthuse.

Din opgave er at læse research om en potentiel kunde og udarbejde input til et skræddersyet pitch deck.

## 🛑 KRITISK REGEL — FAKTA OM EPICO

Alt du siger om **Epico** — services, processer, tal, cases, leveringsmodeller — SKAL stamme direkte fra "EPICO VIDENSBASE" sektionen nedenfor. **Du må IKKE finde på:**

- Tal eller statistikker om Epico (brug kun dem der står i `stats.md`)
- Kundenavne eller cases (brug kun dem i `cases/`)
- Services eller pakke-løsninger der ikke findes (se `boundaries.md`)
- Leveringsmodeller eller priser der ikke er beskrevet
- Sprog eller buzzwords i strid med `messaging.md`

Hvis et faktum om Epico ikke står i vidensbasen → **udelad det**. Hellere mindre konkret end forkert.

**Modsætning**: Når du beskriver KUNDEN (deres situation, deres udfordringer, deres branche), må du gerne syntetisere fra kundens årsrapport, CVR-data og sælgers noter. Dér er kreativ syntese ønsket.

{directive_block}

---

# EPICO VIDENSBASE

Dette er den ENESTE sandhed du må bruge om Epico. Hold dig til det.

{knowledge}

---

## Outputregler

- **Skriv på dansk** — selvom kilderne er på engelsk.
- **Tone**: Følg `messaging.md` strikt. Ingen "synergi", "best-in-class", "next-gen" (medmindre det er Epico NextGen-servicen).
- **Konkret > generisk**: Hellere "Manglende Oracle-DBA til ERP-migration" end "Behov for IT-konsulenter".
- **Kildehenvis kundefakta**: Hver `research_facts.source` skal pege på årsrapport-side eller anden konkret kilde. Hvis du ikke har en konkret kilde, brug "(branche-estimat)".
- **Match case fra `cases/`**: Når du foreslår en case (`case_recommendation`), brug en RIGTIG case fra `cases/`-mappen. Find den der ligner kundens branche mest. Skriv IKKE en helt ny fiktiv case.
- **Services-fokus**: I `value_mappings.epico_service`, brug nøjagtige service-navne ("Epico Freelance", "Epico Search", osv.) — ikke afledte navne.

Returnér ALTID via `deliver_pitch_research`-værktøjet — aldrig prosa-svar."""


def analyze_client(
    client_name: str,
    cvr_data: Optional[Dict[str, Any]] = None,
    annual_report_text: Optional[str] = None,
    sales_notes: Optional[str] = None,
    pitch_focus: Optional[str] = None,
    services_to_highlight: Optional[List[str]] = None,
    emphasis: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Kør Claude-analyse på alt input. Returnér struktureret JSON klar til template-injection.

    Args:
        client_name: Kundens navn
        cvr_data: Resultat fra cvr.lookup_by_name/by_cvr (eller None)
        annual_report_text: Tekst-indhold fra årsrapport-PDF (eller None)
        sales_notes: Sælgers baggrundsviden om kunden (eller None)
        pitch_focus: Sælgers eksplicitte direktiv om hvad pitchen skal handle om
        services_to_highlight: Liste af Epico-services som sælger vil fremhæve
        emphasis: En af 'speed', 'expertise', 'cost', 'local', 'culture' eller None
    """
    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    # Byg user message med al kontekst
    parts = [f"# Kunde: {client_name}\n"]

    if cvr_data:
        parts.append("## CVR-data\n")
        parts.append(f"- CVR-nummer: {cvr_data.get('cvr', '—')}")
        parts.append(f"- Branche: {cvr_data.get('industry_desc', '—')} (kode {cvr_data.get('industry_code', '—')})")
        parts.append(f"- Antal medarbejdere: {cvr_data.get('employees', '—')}")
        parts.append(f"- Selskabstype: {cvr_data.get('company_type', '—')}")
        parts.append(f"- Adresse: {cvr_data.get('address', '—')}")
        parts.append(f"- Hjemmeside: {cvr_data.get('website', '—')}")
        parts.append(f"- Stiftet: {cvr_data.get('founded', '—')}")
        parts.append("")

    if annual_report_text:
        # Trim hvis det er meget langt — Claude kan håndtere 200K tokens men vi vil holde det rimeligt
        max_chars = 80000
        report_excerpt = annual_report_text[:max_chars]
        truncated = len(annual_report_text) > max_chars
        parts.append("## Årsrapport (uddrag)\n")
        parts.append(report_excerpt)
        if truncated:
            parts.append(f"\n\n[BEMÆRK: Årsrapporten er blevet trunkeret. Original længde: {len(annual_report_text)} tegn.]")
        parts.append("")

    if sales_notes:
        parts.append("## Sælgerens noter / kontekst\n")
        parts.append(sales_notes)
        parts.append("")

    # Gentag fokus i user-message for ekstra vægt (system + user = strongest signal)
    if pitch_focus or services_to_highlight or emphasis:
        parts.append("## ⚠️ Husk sælgers direktiver (gentaget for tydelighed)\n")
        if pitch_focus:
            parts.append(f"**Pitch-vinkel**: {pitch_focus}")
        if services_to_highlight:
            parts.append(f"**Services at fremhæve**: {', '.join(services_to_highlight)}")
        if emphasis and emphasis in _EMPHASIS_DESCRIPTIONS:
            parts.append(f"**Ekstra vægt på**: {emphasis} — se system-prompt.")
        parts.append("")

    parts.append("---")
    parts.append("Analysér nu kunden og returnér via `deliver_pitch_research`-værktøjet. Husk: sælgers direktiver er styrende.")

    user_message = "\n".join(parts)

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=_build_system_prompt(
            pitch_focus=pitch_focus,
            services_to_highlight=services_to_highlight,
            emphasis=emphasis,
        ),
        tools=[ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "deliver_pitch_research"},
        messages=[{"role": "user", "content": user_message}],
    )

    # Uddrag tool_use blokken
    for block in response.content:
        if block.type == "tool_use" and block.name == "deliver_pitch_research":
            return block.input

    raise RuntimeError("Claude returnerede ikke struktureret data via tool-use.")
