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


def _get_knowledge(stakeholder_key: Optional[str] = None) -> str:
    """Load knowledge base — inkl. stakeholder-profil hvis angivet."""
    # Når en stakeholder er angivet, load fresh (knowledge ændrer sig per pitch)
    if stakeholder_key:
        return load_knowledge(stakeholder_key)
    # Default: cache uden stakeholder
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
    "Epico Freelance": "Hurtig levering af erfarne IT-konsulenter (+10 års erfaring) og hele teams.",
    "Epico NextGen": "IT-talenter med 0-5 års erfaring. Try-before-hire model. +1.500 aktive profiler.",
    "Epico Search": "Headhunting af IT-ledere og specialister til faste stillinger. +3.000 succesfulde rekrutteringer.",
    "Epico Public": "Specialister via SKI 02.06, 02.14, 02.17 til offentlig sektor.",
    "Epico Nearshore": "Dedikerede teams i Warszawa, Polen. Dansk kontrakt og team-leader.",
    "Epico Tech": "Oracle (+20 års erfaring) og Mainframe (+25 års erfaring) specialister. Også AI og AMS.",
    "Epico Solution": "Management services og komplette IT-løsninger med leveranceansvar.",
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
                "description": "1-2 SÆTNINGER (max 200 tegn) der bliver vist på Hvorfor-vi-mødes-konteksten. SKAL afspejle sælgers brief, ikke kun årsrapport. Hvis sælger pitcher MOD en konkurrent → nævn det subtilt (fx 'I bruger i dag Emagine — vi vil gerne vise hvor Epico flytter nålen yderligere'). Hvis stakeholder er Procurement → tonen er forretningsmæssig, ikke teknisk. Ingen bulletliste, kun prosa.",
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
                "description": "Nøjagtigt 3 strategiske prioriteter SOM SÆLGER VIL TALE OM I MØDET. Hvis sælgers brief nævner konkurrent (fx Emagine) eller specifik stakeholder (Procurement) → prioriteterne skal afspejle det. Eksempler: hvis stakeholder er Procurement → prioritet kan være 'Diversificering af leverandørbase' eller 'Reducere TCO på IT-konsulent-spend'. Hvis konkurrent er nævnt → prioritet kan være 'Få bedre service-niveau end nuværende leverandør'. PRIORITETER ER IKKE BARE 'læst fra årsrapport' — de er det sælger vil ARGUMENTERE for under mødet, baseret på brief + research kombineret.",
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
                "description": "Nøjagtigt 4 mappings. HVIS SÆLGER HAR ANGIVET EN KONKURRENT i brief: hver mapping skal differentiere Epico FRA den konkurrent (fx 'Hvor Emagine sender mange CV'er, sender Epico kun forhåndsscreenede der allerede har sagt ja'). HVIS STAKEHOLDER = PROCUREMENT: mappings handler om kontraktvilkår, SLA, fleksibilitet, prismodel. HVIS STAKEHOLDER = IT-LEDELSE: mappings handler om teknisk dybde og leverancetid. Brug sælgers brief som det primære filter — IKKE 'hvad ville være generisk relevant for branchen'.",
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
                "description": "Nøjagtigt 3 konkrete næste skridt. SKAL MATCHE STAKEHOLDER fra brief: Procurement → 'fremsende RFP-svar', 'TCO-analyse', 'pris-benchmark'. IT-ledelse → 'arkitektur-workshop', 'tekniske use cases'. C-suite → 'executive briefing', 'strategic roadmap'. First touch → 'lære hinanden at kende' inden vi taler konkrete leverancer. Hvis konkurrent-situation: minimum ét næste skridt skal være 'parallel-pilot' eller 'sammenligning' så kunden kan teste Epico mod nuværende leverandør uden risiko.",
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
            "service_slides": {
                "type": "array",
                "description": "1 slide per Epico-service som skal vises i pitch'en. HVIS sælger har angivet 'services_to_highlight' → returnér KUN slides for de services. HVIS ingen valgt → returnér alle 7 services (Freelance, NextGen, Search, Public, Nearshore, Tech, Solution). Hvert slide skal være TILPASSET KUNDENS BRANCHE (roller og kunde-referencer matches til kundens domæne).",
                "items": {
                    "type": "object",
                    "properties": {
                        "service_name": {
                            "type": "string",
                            "description": "Eksakt service-navn fra knowledge base. Et af: Epico Freelance, Epico NextGen, Epico Search, Epico Public, Epico Nearshore, Epico Tech, Epico Solution.",
                        },
                        "tagline": {
                            "type": "string",
                            "description": "1 linje value-proposition. Max 90 tegn. Skarp og kunde-værdi-fokuseret, ikke generisk. Fx 'Erfarne IT-konsulenter på 48 timer — uden langtidsbinding'."
                        },
                        "what_we_deliver": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Nøjagtigt 4 bullets der konkret beskriver hvad kunden får. Max 90 tegn per bullet. Tag udgangspunkt i service-filen i knowledge base.",
                            "minItems": 4,
                            "maxItems": 4,
                        },
                        "key_stats": {
                            "type": "array",
                            "description": "Nøjagtigt 3 nøgletal der gør servicen troværdig. Brug KUN tal der står i knowledge base (stats.md eller services/*.md).",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "value": {"type": "string", "description": "Selve tallet, fx '+500' eller '99%' eller '+25 år'"},
                                    "label": {"type": "string", "description": "Kort label, max 60 tegn, fx 'konsulenter på kontrakt' eller 'hit-rate på matching'"},
                                },
                                "required": ["value", "label"],
                            },
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "who_its_for": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Nøjagtigt 3 bullets om hvornår denne service er det rigtige valg. Skriv 'Når I...' eller 'Hvis I...'. Tilpas til kundens situation hvor muligt.",
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "typical_roles": {
                            "type": "string",
                            "description": "Kommasepareret liste af 4-6 KONKRETE roller Epico kan levere via denne service. VÆLG ROLLER DER ER RELEVANTE FOR KUNDENS BRANCHE. Eksempel for finans-kunde i Search: 'CISO · Risk Manager · Senior Java Developer · Quant Developer · IT Security Architect'."
                        },
                        "relevant_partners": {
                            "type": "string",
                            "description": "Kommasepareret liste af 2-4 EPICO-PARTNERE/kunder vi kan nævne. Brug KUN navne fra knowledge base: Arla, Carlsberg, Politi.dk, Ikano Bank, KPMG, Pandora, Siemens, Aller Media. VÆLG DEM DER LIGNER KUNDENS BRANCHE MEST. Hvis ingen passer, skriv generisk fx '+1.500 kunder globalt'."
                        },
                    },
                    "required": ["service_name", "tagline", "what_we_deliver", "key_stats", "who_its_for", "typical_roles", "relevant_partners"],
                },
                "minItems": 1,
                "maxItems": 7,
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
            "service_slides",
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


_MEETING_STAGE_DESCRIPTIONS = {
    "first_touch": "Dette er **første gang** I taler med kunden. Antag intet kendskab. Vær respektfuld for deres tid og hold strukturen tydelig.",
    "re_engage": "I har **mødtes før, men dialogen er gået kold**. Genoplive uden at gentage. Henvis subtilt til hvad I tidligere har talt om hvis relevant.",
    "existing_customer": "Kunden er **allerede en eksisterende kunde**. Pitchen handler om at udvide samarbejdet — ikke at sælge sig ind fra bunden. Spring 'hvem er vi'-passager kort over.",
    "renewal": "Kunden er **eksisterende og samarbejdet skal forlænges eller udvides**. Fokusér på dokumenteret værdi I har leveret + næste fase. Mindre 'sælg', mere 'optimér'.",
}


_TONE_DESCRIPTIONS = {
    "balanced": "Balanceret — direkte og professionel, men menneskelig.",
    "formal": "**Formel og strategisk**. Strammere sprog. Mere fokus på governance, KPI'er, strategi. Mindre 'vi' og mere 'organisationen'.",
    "direct": "**Direkte og operationel**. Korte sætninger. Konkret. Tal-tunge formuleringer. Spring blødheder over.",
    "personal": "**Personlig og konsultativ**. Som en betroet rådgiver. Brug 'I' / 'vi sammen'. Lidt mere uformel uden at miste autoritet.",
}


def _build_system_prompt(
    pitch_focus: Optional[str] = None,
    services_to_highlight: Optional[List[str]] = None,
    emphasis: Optional[str] = None,
    seller_brief: Optional[Dict[str, Optional[str]]] = None,
    slide_dictation: Optional[Dict[str, Optional[str]]] = None,
    stakeholder_key: Optional[str] = None,
) -> str:
    # Sælger-direktiver — disse er styrende
    directives = []

    # Lag 1: Strukturerede sælger-inputs (HØJESTE prioritet)
    if seller_brief:
        brief_parts = []
        stage = seller_brief.get("meeting_stage")
        if stage and stage in _MEETING_STAGE_DESCRIPTIONS:
            brief_parts.append(f"**Mødestadie**: {_MEETING_STAGE_DESCRIPTIONS[stage]}")
        if seller_brief.get("meeting_history"):
            brief_parts.append(f"**Mødehistorik**: {seller_brief['meeting_history']}")
        if seller_brief.get("personal_angle"):
            brief_parts.append(f"**Personlig vinkel om mødedeltageren**: {seller_brief['personal_angle']}")
        if seller_brief.get("insider_insights"):
            brief_parts.append(f"**Insider-insights (ikke offentlige)**: {seller_brief['insider_insights']}")
        if seller_brief.get("exclusions"):
            brief_parts.append(f"**EKSKLUSIONER — må IKKE nævnes**: {seller_brief['exclusions']}")
        tone = seller_brief.get("tone")
        if tone and tone in _TONE_DESCRIPTIONS and tone != "balanced":
            brief_parts.append(f"**Tone**: {_TONE_DESCRIPTIONS[tone]}")

        if brief_parts:
            directives.append(
                "## 🎯 SÆLGERS BRIEF (TRUMFER ALT ANDET)\n\n"
                "Disse oplysninger kommer fra sælgers personlige kendskab til kunden — fra netværk, "
                "tidligere møder, LinkedIn, jobopslag eller interne kilder. **De vægter HØJERE end årsrapporten.**\n\n"
                "Hvis sælgers brief og årsrapport peger forskelligt — vinder sælger. Brug årsrapporten som "
                "*støtte* til sælgers narrativ, ikke som modvægt.\n\n"
                + "\n\n".join(brief_parts)
            )

    # Lag 2: Slide-for-slide dictation
    if slide_dictation:
        dict_parts = []
        if slide_dictation.get("why_meeting"):
            dict_parts.append(f"**Slide 02 (Hvorfor vi mødes)**: Brug DENNE tekst som `client_summary` (polér gerne sprog, men hold indholdet):\n> {slide_dictation['why_meeting']}")
        if slide_dictation.get("research_facts"):
            dict_parts.append(f"**Slide 04 (Research-facts)**: Brug DISSE facts som `research_facts` (parser hver linje). Hvis format er '[Label]: [Værdi] | [Kilde]', så map til key/value/source. Hvis sælger har givet færre end 4 — supplér med årsrapport, men sælgers facts har prioritet:\n```\n{slide_dictation['research_facts']}\n```")
        if slide_dictation.get("priorities"):
            dict_parts.append(f"**Slide 05 (Strategiske prioriteter)**: Brug DISSE som `strategic_priorities` (én linje pr. prioritet, format '[Titel] — [beskrivelse]'):\n```\n{slide_dictation['priorities']}\n```")
        if slide_dictation.get("mappings"):
            dict_parts.append(f"**Slide 06 (Value mappings)**: Brug DISSE som `value_mappings` (én linje pr. mapping, format '[Udfordring] => [Service] : [Løsning]'):\n```\n{slide_dictation['mappings']}\n```")
        if slide_dictation.get("next_steps"):
            dict_parts.append(f"**Slide 17 (Næste skridt)**: Brug DISSE som `next_steps` (én linje pr. skridt, format '[Titel] | [tidsramme] — [beskrivelse]'):\n```\n{slide_dictation['next_steps']}\n```")

        if dict_parts:
            directives.append(
                "## 📝 SÆLGER-STYREDE SLIDES (overskriv AI-output)\n\n"
                "Sælgeren har skrevet **specifikt indhold til bestemte slides**. Du SKAL bruge sælgers tekst som "
                "grundlaget for de pågældende felter — du må kun polere sprog, struktur og formatering. **Du må IKKE "
                "ændre indholdets retning eller pointe.**\n\n"
                "For slides hvor sælger IKKE har givet specifik tekst, bruger du normal analyse-logik.\n\n"
                + "\n\n".join(dict_parts)
            )

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

    # Knowledge base — hele Epico's vidensbase (inkl. stakeholder-profil hvis angivet)
    knowledge = _get_knowledge(stakeholder_key)

    return f"""Du er en strategisk analytiker hos Epico, et af Nordens største IT-konsulenthuse.

Din opgave er at læse research om en potentiel kunde og udarbejde input til et skræddersyet pitch deck.

## 🚨 START-PUNKT — STAKEHOLDER + SÆLGERS BRIEF DEFINERER PITCHEN

**FØR du overhovedet kigger på årsrapport, web search, eller hjemmeside-data — læs stakeholder-profilen ovenfor og sælgers brief grundigt, og besvar disse spørgsmål for dig selv:**

1. **Hvem mødes vi med (stakeholder-type)?** Procurement / IT-leder / HR / CFO / CEO / Tech Lead / Forretningsleder
2. **Hvad bekymrer denne person sig IKKE om?** Disse temaer skal aktivt DROPPES fra pitchen
3. **Hvad er deres aktuelle situation?** (har de allerede en leverandør? skal vi udskifte nogen? skal vi supplere?)
4. **Hvilken konkurrent — hvis nogen — er nævnt i sælgers brief?**
5. **Hvad er sælgers KONKRETE ønske med pitchen?**

**Disse svar er rygraden i hele pitchen.** En Procurement-pitch og en CIO-pitch til samme kunde skal være vidt forskellige.

**Vigtigt om stakeholder-tilpasning:**

Hver stakeholder-profil i vidensbasen lister:
- Hvilke slides der MEDTAGES (omformuleret)
- Hvilke slides der UDELADES (drop dem!)
- Tone der virker
- Nøgletal at fremhæve
- Næste skridt der appellerer

**Du SKAL respektere disse anvisninger.** Hvis profilen siger "Drop research-slide for denne stakeholder" → så gør det. Hvis den siger "Næste skridt skal være RFP-svar, ikke executive workshop" → så gør det.

**Konkurrent-håndtering:**

Hvis sælger har angivet en konkurrent i sit brief (fx "de bruger ProData", "de er på rammeaftale med Tieto"), så skal value_mappings differentiere mod den specifikke konkurrent. Ikke generisk service-mapping.

Hvis ingen konkurrent er nævnt — så er det ikke en konkurrence-pitch. **Nævn ikke konkurrenter på fri hånd.** Drop helt "alternativ-til"-vinklen og fokusér på Epico's egne styrker.

## 🎯 KURATIONS-PRINCIP

Du får MEGET data: årsrapport (60.000+ tegn), hjemmeside-tekst, web-search-resultater, CVR-data, sælgers brief. **Sælger ser KUN det du beslutter at putte i slidesne.**

Din primære opgave er **KURATION, ikke COMPILATION**. Det betyder:

- **Sælgers brief er FILTERET.** Alt fra årsrapport/web search vurderes på "passer det ind i sælgers vinkel?" — hvis ikke: udelad det, selv hvis det er imponerende info
- **Vælg det 1% der betyder noget.** Hvis årsrapporten har 50 fakta, vælg de 4 der støtter sælgers brief
- **Signal > støj.** Brug det der støtter sælgers vinkel, ikke det der er generelt interessant
- **Konkret > abstract.** "Tredoblet IT-team til 1.800 ansatte" slår "Investering i digital transformation" — MEN kun hvis det er relevant for sælgers vinkel

**Kuration-tjek:** Spørg dig selv for hvert fact:
1. Støtter dette sælgers pitch-vinkel + konkurrent-situation + stakeholder?
2. Vil sælgeren nævne dette under mødet?
3. Hvis nej til en af dem → udelad. Hellere mindre og fokuseret end mere og spredt.

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
    website_text: Optional[str] = None,
    web_intelligence: Optional[str] = None,
    seller_brief: Optional[Dict[str, Optional[str]]] = None,
    slide_dictation: Optional[Dict[str, Optional[str]]] = None,
    pitch_focus: Optional[str] = None,
    services_to_highlight: Optional[List[str]] = None,
    emphasis: Optional[str] = None,
    stakeholder_key: Optional[str] = None,
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

    # SÆLGERS BRIEF kommer FØRST (højeste prioritet, før årsrapport)
    if seller_brief and any(seller_brief.values()):
        parts.append("## 🎯 SÆLGERS BRIEF (vægter HØJEST)\n")
        stage = seller_brief.get("meeting_stage")
        if stage:
            parts.append(f"**Mødestadie**: {stage}")
        if seller_brief.get("meeting_history"):
            parts.append(f"**Mødehistorik**: {seller_brief['meeting_history']}")
        if seller_brief.get("personal_angle"):
            parts.append(f"**Personlig vinkel**: {seller_brief['personal_angle']}")
        if seller_brief.get("insider_insights"):
            parts.append(f"**Insider-insights**: {seller_brief['insider_insights']}")
        if seller_brief.get("exclusions"):
            parts.append(f"**⚠️ EKSKLUSIONER (må IKKE nævnes)**: {seller_brief['exclusions']}")
        if seller_brief.get("tone"):
            parts.append(f"**Tone**: {seller_brief['tone']}")
        parts.append("")

    # SLIDE-DICTATION (specifikke felter sælger har styret)
    if slide_dictation and any(slide_dictation.values()):
        parts.append("## 📝 SÆLGER HAR DIKTERET SPECIFIKT INDHOLD TIL DISSE SLIDES\n")
        if slide_dictation.get("why_meeting"):
            parts.append(f"**Slide 02 (client_summary)**:\n> {slide_dictation['why_meeting']}\n")
        if slide_dictation.get("research_facts"):
            parts.append(f"**Slide 04 (research_facts)** — parse hver linje, format '[Label]: [Værdi] | [Kilde]':\n```\n{slide_dictation['research_facts']}\n```\n")
        if slide_dictation.get("priorities"):
            parts.append(f"**Slide 05 (strategic_priorities)** — én linje pr. prioritet, format '[Titel] — [beskrivelse]':\n```\n{slide_dictation['priorities']}\n```\n")
        if slide_dictation.get("mappings"):
            parts.append(f"**Slide 06 (value_mappings)** — én linje pr. mapping, format '[Udfordring] => [Service] : [Løsning]':\n```\n{slide_dictation['mappings']}\n```\n")
        if slide_dictation.get("next_steps"):
            parts.append(f"**Slide 17 (next_steps)** — én linje pr. skridt, format '[Titel] | [tidsramme] — [beskrivelse]':\n```\n{slide_dictation['next_steps']}\n```\n")
        parts.append("")

    if cvr_data:
        parts.append("## CVR-data (offentlig baggrund)\n")
        parts.append(f"- CVR-nummer: {cvr_data.get('cvr', '—')}")
        parts.append(f"- Branche: {cvr_data.get('industry_desc', '—')} (kode {cvr_data.get('industry_code', '—')})")
        parts.append(f"- Antal medarbejdere: {cvr_data.get('employees', '—')}")
        parts.append(f"- Selskabstype: {cvr_data.get('company_type', '—')}")
        parts.append(f"- Adresse: {cvr_data.get('address', '—')}")
        parts.append(f"- Hjemmeside: {cvr_data.get('website', '—')}")
        parts.append(f"- Stiftet: {cvr_data.get('founded', '—')}")
        parts.append("")

    if annual_report_text:
        # Trim hvis det er meget langt
        max_chars = 60000
        report_excerpt = annual_report_text[:max_chars]
        truncated = len(annual_report_text) > max_chars
        parts.append("## Årsrapport (rå tekst — sælgers brief vinder)\n")
        parts.append(report_excerpt)
        if truncated:
            parts.append(f"\n\n[BEMÆRK: Årsrapporten er trunkeret. Original længde: {len(annual_report_text)} tegn.]")
        parts.append("")

    if website_text:
        max_chars = 30000
        website_excerpt = website_text[:max_chars]
        parts.append("## Kundens hjemmeside (kuratrede sider — strategi, om-os, investor)\n")
        parts.append(website_excerpt)
        if len(website_text) > max_chars:
            parts.append(f"\n[Trunkeret. Original: {len(website_text)} tegn.]")
        parts.append("")

    if web_intelligence:
        parts.append("## 🔍 Web search-resultater (aktuelle nyheder & pressemeddelelser)\n")
        parts.append("Disse oplysninger er FRISKE — fra web search lige nu. De har høj prioritet sammen med sælgers brief.")
        parts.append("")
        parts.append(web_intelligence)
        parts.append("")

    # Pitch-vinkel og services-direktiver gentages
    if pitch_focus or services_to_highlight or emphasis:
        parts.append("## ⚠️ Pitch-direktiver (gentaget for tydelighed)\n")
        if pitch_focus:
            parts.append(f"**Pitch-vinkel**: {pitch_focus}")
        if services_to_highlight:
            parts.append(f"**Services at fremhæve**: {', '.join(services_to_highlight)}")
        if emphasis and emphasis in _EMPHASIS_DESCRIPTIONS:
            parts.append(f"**Ekstra vægt på**: {emphasis} — se system-prompt.")
        parts.append("")

    parts.append("---")
    parts.append("Analysér nu kunden og returnér via `deliver_pitch_research`-værktøjet.")
    parts.append("**Husk hierarkiet:** Sælgers brief + slide-dictation > pitch-vinkel + services + emphasis > årsrapport > CVR-data.")

    user_message = "\n".join(parts)

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=_build_system_prompt(
            pitch_focus=pitch_focus,
            services_to_highlight=services_to_highlight,
            emphasis=emphasis,
            seller_brief=seller_brief,
            slide_dictation=slide_dictation,
            stakeholder_key=stakeholder_key,
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
