"""
Claude API client.
Analyserer årsrapport + CVR-data og returnerer struktureret data
til de 5 klient-specifikke slides i pitch decket.
"""
import os
import json
import copy
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


_SLIDE_REFINE_SYSTEM_PROMPT = """Du er Epico's pitch-redaktør. Sælger har bedt dig om at SKÆRPE et specifikt slide-indhold med en bestemt direktive.

Modtag:
- Slide-type (research_facts / strategic_priorities / value_mappings / next_steps / case_recommendation)
- Nuværende indhold (JSON)
- Sælgers direktive (fritekst, fx "mere konkret", "mere kommerciel tone", "fokus på cybersecurity")

Returnér en FORBEDRET version af samme slide i samme JSON-struktur via `refine_slide`-værktøjet.

**Vigtige regler:**
- Behold STRUKTUREN (samme antal facts/items, samme felter)
- Tilpas TONE og INDHOLD efter direktivet
- Hvis direktivet er "mere konkret": erstat generiske bullets med specifikke tal og navne
- Hvis "mere kommerciel": tilpas tonen til TCO/SLA/ROI-sprog
- Hvis "mere strategisk": løft niveauet til forretningsoutcome
- Hvis "mindre sælgende": fjern blødt corporate-snak
- Hold dig til knowledge base — find IKKE på nye fakta om Epico
- Hvis indholdet allerede er godt: lav små, præcise justeringer

Returnér ALTID via `refine_slide`-værktøjet."""


_REFINE_TOOL = {
    "name": "refine_slide",
    "description": "Returnér det forbedrede slide-indhold i samme struktur som input.",
    "input_schema": {
        "type": "object",
        "properties": {
            "refined_content": {
                "description": "Det forbedrede indhold. Strukturen SKAL matche input (samme nøgler, samme antal items).",
            },
        },
        "required": ["refined_content"],
    },
}


def refine_slide(
    slide_type: str,
    current_content: Any,
    directive: str,
    client_name: Optional[str] = None,
    stakeholder_key: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Any:
    """
    Skærp et specifikt slide-indhold baseret på sælgers direktive.

    Args:
        slide_type: 'research_facts' | 'strategic_priorities' | 'value_mappings' |
                    'next_steps' | 'case_recommendation'
        current_content: Nuværende JSON-indhold for sliden
        directive: Sælgers ønske ("mere konkret", "mere kommerciel", "fokus på security", osv.)
        client_name: For kontekst
        stakeholder_key: For tone-tilpasning

    Returns:
        Forbedret indhold i samme struktur
    """
    import json
    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    knowledge = _get_knowledge(stakeholder_key)

    parts = [
        f"## Kunde: {client_name or 'kunden'}\n",
        f"## Slide-type: {slide_type}\n",
        f"## Sælgers direktive:\n{directive}\n",
        "## Nuværende indhold:\n```json",
        json.dumps(current_content, indent=2, ensure_ascii=False),
        "```\n",
        "\n## EPICO VIDENSBASE (kun fakta fra denne må bruges om Epico):\n",
        knowledge,
        "\n\n---\nSkærp ovenstående slide-indhold efter direktivet. Returnér samme struktur via `refine_slide`-værktøjet.",
    ]
    user_message = "\n".join(parts)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=_SLIDE_REFINE_SYSTEM_PROMPT,
        tools=[_REFINE_TOOL],
        tool_choice={"type": "tool", "name": "refine_slide"},
        messages=[{"role": "user", "content": user_message}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "refine_slide":
            return block.input.get("refined_content")

    return current_content  # Fallback


_BRIEF_CONTRACT_TOOL = {
    "name": "deliver_pitch_contract",
    "description": "Returnér den eksplicitte pitch-kontrakt der binder Claude til sælgers intent.",
    "input_schema": {
        "type": "object",
        "properties": {
            "core_intent": {
                "type": "string",
                "description": "Én sætning (max 200 tegn): Hvad ER denne pitch egentlig om? Skriv det som om du forklarer pitchen til en kollega.",
            },
            "tone_directive": {
                "type": "string",
                "description": "Kort beskrivelse af tonen baseret på stakeholder + længde. Max 150 tegn. Eksempel: 'Procurement-tone: TCO, SLA, kontraktvilkår — drop strategisk/visionært sprog.'",
            },
            "must_include": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3-5 punkter pitchen SKAL inkludere. Tag fra sælgers brief + de mest relevante datapunkter fra research.",
                "minItems": 3,
                "maxItems": 5,
            },
            "must_exclude": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3-5 temaer pitchen SKAL undgå. Tag fra sælgers eksklusioner + temaer der ikke matcher stakeholder/længde/fokus (selv hvis interessante).",
                "minItems": 3,
                "maxItems": 5,
            },
            "research_priorities": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "3-5 ting pitchen har brug for at vide om kunden for at holde vand. "
                    "Formulér dem som det du LEDER EFTER — ikke som noget du allerede har fundet. "
                    "Fx 'Om de har annonceret et ERP-skifte inden for 18 måneder', ikke 'De skifter ERP'. "
                    "Har du allerede belæg i materialet, så skriv det du fandt. "
                    "Disse styrer både hvad der bliver søgt efter, og hvad der senere må trækkes ud af materialet."
                ),
                "minItems": 3,
                "maxItems": 5,
            },
            "research_queries": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "3-4 konkrete web-søgninger der kan afklare research-prioriteterne ovenfor. "
                    "Skriv dem som en researcher ville taste dem — med firmanavn, konkrete termer og "
                    "gerne årstal. Ikke som spørgsmål til en chatbot.\n\n"
                    "God: 'Novo Nordisk SAP S/4HANA migration 2025 leverandør'\n"
                    "Dårlig: 'Hvad laver Novo Nordisk inden for IT?'\n\n"
                    "Rammer sælgers brief en konkurrent, en bestemt afdeling eller en konkret smerte — "
                    "så skal mindst én søgning gå direkte efter dét. Søgninger på generisk firmabaggrund "
                    "er spildt: dem har vi CVR og årsrapport til."
                ),
                "minItems": 3,
                "maxItems": 4,
            },
            "next_steps_style": {
                "type": "string",
                "description": "1 sætning: Hvad slags næste skridt skal Claude foreslå? (RFP-svar, executive workshop, teknisk pilot, parallel-test, osv.) — baseret på stakeholder.",
            },
            "expected_slide_count": {
                "type": "string",
                "description": "Fx '8-10 slides' (kort), '13-15 slides' (medium), '20+ slides' (lang).",
            },
        },
        "required": ["core_intent", "tone_directive", "must_include", "must_exclude", "research_priorities", "research_queries", "next_steps_style", "expected_slide_count"],
    },
}


_BRIEF_CONTRACT_SYSTEM = """Du er Epico's pitch-strateg. En sælger skal til møde hos en kunde, og du skal beslutte HVAD den pitch handler om — før nogen begynder at samle materiale.

Det er vigtigt at forstå rækkefølgen: du arbejder **før** researchen er lavet. Du får sælgers brief, CVR-data og eventuelt en årsrapport. Du får ikke web-søgninger endnu — for det er DIG der bestemmer hvad der skal søges efter.

Din opgave er en kontrakt på ~300 ord: hvad pitchen handler om, hvad den skal indeholde, hvad den ikke må indeholde, og hvad vi mangler at vide.

Tænk som en redaktør der briefer en journalist inden researchen: "Her er historien. Gå ud og find belæg for den — og kom tilbage hvis den ikke holder."

## Sådan læser du sælgers input

Sælgers input er ikke én klump. Fem typer, hver med sin egen vægt:

- **Begrænsninger** (hvad der ikke må nævnes) er absolutte. De ryger direkte i `must_exclude` og kan ikke afvejes.
- **Evidens** (insider-viden, mødehistorik, hvad sælger ved om personen) er faktuelle oplysninger. De vinder over årsrapport og CVR ved konflikt — et regnskab er op til 14 måneder gammelt, sælger talte måske med dem i sidste uge.
- **Ramme** (mødestadie, pitch-vinkel) afgør hvad der er relevant. Den tilføjer ikke fakta, men den bestemmer hvad du leder efter.
- **Diktat** (tekst sælger selv har skrevet til bestemte slides) er endeligt indhold. Kontrakten skal beskytte det, ikke overskrive det.
- **Struktur** (længde, services, stakeholder) styrer form og omfang — ikke hvad der er sandt.

## Principper

- Stakeholder-typen styrer tone og næste skridt. En Procurement-chef og en CIO får ikke samme pitch.
- Pitch-længden styrer hvor mange detaljer der er plads til. Kort betyder skarpere, ikke bare kortere.
- Er der nævnt en konkurrent: pitchen handler om differentiering, ikke om generisk salg.
- Er briefen tynd, så sig det ærligt i `core_intent` fremfor at digte en historie. Dine `research_queries` bliver så det der skal redde pitchen.

Returnér via `deliver_pitch_contract`-værktøjet."""


def _build_pitch_contract(
    client_name: str,
    cvr_data: Optional[Dict[str, Any]] = None,
    annual_report_text: Optional[str] = None,
    website_text: Optional[str] = None,
    web_intelligence: Optional[str] = None,
    seller_brief: Optional[Dict[str, Optional[str]]] = None,
    slide_dictation: Optional[Dict[str, Optional[str]]] = None,
    pitch_focus: Optional[str] = None,
    services_to_highlight: Optional[List[str]] = None,
    stakeholder_key: Optional[str] = None,
    pitch_length: Optional[str] = "medium",
    api_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Stage 0: Generer eksplicit pitch-kontrakt FØR slides-generering.
    Claude bindes til denne kontrakt i Stage 1 + Stage 2.
    """
    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    parts = [f"# Kunde: {client_name}\n"]

    # Sælgers brief (vigtigst)
    if seller_brief and any(seller_brief.values()):
        parts.append("## 🎯 SÆLGERS BRIEF (vigtigste input)\n")
        if seller_brief.get("meeting_stakeholder"):
            parts.append(f"**Stakeholder-type**: {seller_brief['meeting_stakeholder']}")
        if seller_brief.get("meeting_stage"):
            parts.append(f"**Mødestadie**: {seller_brief['meeting_stage']}")
        for key, label in [
            ("meeting_history", "Mødehistorik"),
            ("personal_angle", "Personlig vinkel/stakeholder"),
            ("insider_insights", "Insider-insights/konkurrent-situation"),
            ("exclusions", "⚠️ EKSKLUSIONER (må IKKE nævnes)"),
        ]:
            if seller_brief.get(key):
                parts.append(f"**{label}**: {seller_brief[key]}")
        parts.append("")

    # Pitch-vinkel + længde
    parts.append("## Pitch-direktiver\n")
    parts.append(f"**Pitch-længde**: {pitch_length} ({_short_length_label(pitch_length)})")
    if pitch_focus:
        parts.append(f"**Pitch-fokus**: {pitch_focus}")
    if services_to_highlight:
        parts.append(f"**Services at fremhæve**: {', '.join(services_to_highlight)}")
    parts.append("")

    # Slide-dictation (tvinger specifikt indhold)
    if slide_dictation and any(slide_dictation.values()):
        parts.append("## Slide-dictation (specifikt indhold sælger har skrevet)\n")
        for k, v in slide_dictation.items():
            if v:
                parts.append(f"- {k}: {v[:200]}")
        parts.append("")

    # CVR
    if cvr_data:
        parts.append("## CVR-data (offentlig baggrund)\n")
        parts.append(f"- Branche: {cvr_data.get('industry_desc', '—')}")
        parts.append(f"- Ansatte: {cvr_data.get('employees', '—')}")
        parts.append(f"- Hjemmeside: {cvr_data.get('website', '—')}")
        parts.append("")

    # Research-materiale. Kontrakten bygges normalt FØR web-search, så det meste
    # af dette er tomt — det er meningen. Kontrakten bestemmer hvad der skal søges.
    if annual_report_text:
        # Kun et uddrag: kontrakten skal være hurtig, og Stage 1 får hele rapporten.
        parts.append("## Årsrapport (uddrag)\n")
        parts.append(annual_report_text[:30000])
        parts.append("")

    if web_intelligence:
        parts.append("## Web search-resultater\n")
        parts.append(web_intelligence[:8000])
        parts.append("")

    if website_text:
        parts.append("## Hjemmeside (kuratede sider)\n")
        parts.append(website_text[:8000])
        parts.append("")

    if not any([annual_report_text, web_intelligence, website_text]):
        parts.append("## Research-materiale\n")
        parts.append(
            "Der er endnu ikke indsamlet research — det sker EFTER denne kontrakt, "
            "styret af dine `research_queries`. Byg kontrakten på sælgers brief og CVR-data alene, "
            "og lad `research_queries` være det du har brug for at få afklaret."
        )
        parts.append("")

    parts.append("---")
    parts.append("Producer pitch-kontrakten via `deliver_pitch_contract`-værktøjet. Vær KONKRET og SPECIFIK — ingen vage formuleringer.")

    user_message = "\n".join(parts)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=_BRIEF_CONTRACT_SYSTEM,
            tools=[_BRIEF_CONTRACT_TOOL],
            tool_choice={"type": "tool", "name": "deliver_pitch_contract"},
            messages=[{"role": "user", "content": user_message}],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "deliver_pitch_contract":
                return block.input
    except Exception:
        return None

    return None


# ═══════════════════════════════════════════════════════════════════════════
# OMVENDT BRIEF — AI spørger, i stedet for at sælger udfylder blanke felter
# ═══════════════════════════════════════════════════════════════════════════

_BRIEF_QUESTIONS_TOOL = {
    "name": "deliver_brief_questions",
    "description": "Returnér de spørgsmål der vil løfte pitchen mest.",
    "input_schema": {
        "type": "object",
        "properties": {
            "assessment": {
                "type": "string",
                "description": (
                    "Én sætning, max 160 tegn, til sælgeren: hvad kan du allerede lave en god pitch på, "
                    "og hvad er det svage punkt? Skriv direkte og uden smiger. "
                    "Fx 'Du har stakeholder og konkurrent på plads — men intet om hvad der gør DEM utilfredse.'"
                ),
            },
            "questions": {
                "type": "array",
                "description": (
                    "2-3 spørgsmål. Ikke flere. Hvert spørgsmål skal kunne ændre pitchen konkret — "
                    "kan du ikke pege på hvilket slide svaret ville flytte, så stil det ikke."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": (
                                "Spørgsmålet, som en kollega ville stille det. Max 120 tegn. "
                                "Konkret og besvarligt på 20 sekunder. "
                                "God: 'Hvad var den udløsende årsag til at de tog mødet?' "
                                "Dårlig: 'Kan du fortælle mere om kunden?'"
                            ),
                        },
                        "why": {
                            "type": "string",
                            "description": "Max 90 tegn: hvad svaret ændrer i pitchen. Fx 'Bestemmer om vi åbner på pris eller på kapacitet.'",
                        },
                        "field": {
                            "type": "string",
                            "enum": ["insider_insights", "personal_angle", "meeting_history", "pitch_focus", "exclusions"],
                            "description": "Hvilket brief-felt svaret hører hjemme i.",
                        },
                        "example_answer": {
                            "type": "string",
                            "description": "Max 90 tegn. Et realistisk eksempelsvar der viser detaljeniveauet. Vises som placeholder.",
                        },
                    },
                    "required": ["question", "why", "field", "example_answer"],
                },
                "minItems": 2,
                "maxItems": 3,
            },
        },
        "required": ["assessment", "questions"],
    },
}


_BRIEF_QUESTIONS_SYSTEM = """Du er en erfaren Epico-sælger der kigger en kollegas mødeforberedelse igennem, kort før de skal afsted.

Kollegaen har skrevet noget om kunden og mødet — måske meget, måske næsten intet. Din opgave er at stille de **2-3 spørgsmål der vil løfte pitchen mest**. Ikke en tjekliste. Ikke alt hvad man kunne spørge om. De to-tre der faktisk rykker.

## Sådan vælger du

Et godt spørgsmål opfylder alle fire:

1. **Svaret ændrer pitchen.** Kan du ikke sige hvilket slide der bliver anderledes, så drop det.
2. **Sælgeren kan svare på 20 sekunder.** Vi spørger om hvad de ved, ikke om hvad de skal undersøge.
3. **Du kan ikke selv finde svaret.** Omsætning, branche, antal ansatte — det slår vi selv op. Spørg om det der kun findes i sælgerens hoved.
4. **Det er ikke allerede besvaret.** Læs briefen ordentligt igennem først.

## Hvad der typisk er værd at spørge om

- **Den udløsende årsag.** Hvorfor tog de mødet lige nu? Det afgør hvad hele pitchen skal handle om.
- **Smerten hos den nuværende leverandør.** Er der en konkurrent inde, er "hvad irriterer dem" mere værd end alt andet.
- **Hvem der reelt beslutter.** Ofte ikke personen i mødet.
- **Hvad der er gået galt før.** Både med os og med andre.
- **Hvad der IKKE må nævnes.** Sælgere glemmer ofte at skrive det, men det redder møder.

## Hvad du ikke skal spørge om

- Ting der står i CVR eller årsrapporten
- Brede spørgsmål ("fortæl mere om kunden")
- Ting sælger næppe ved ("hvad er deres IT-budget for 2027?")
- Mere end tre spørgsmål — så bliver det et skema, og skemaer bliver ikke udfyldt

Er briefen allerede stærk, så sig det i `assessment` og stil de to spørgsmål der ville gøre den skarpere endnu. Der er altid noget.

Returnér via `deliver_brief_questions`-værktøjet."""


def suggest_brief_questions(
    client_name: str,
    cvr_data: Optional[Dict[str, Any]] = None,
    seller_brief: Optional[Dict[str, Optional[str]]] = None,
    pitch_focus: Optional[str] = None,
    stakeholder_key: Optional[str] = None,
    pitch_length: Optional[str] = "medium",
    services_to_highlight: Optional[List[str]] = None,
    api_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Læs sælgers (måske tomme) brief og returnér 2-3 spørgsmål der vil løfte pitchen mest.

    Vender formularen om: i stedet for tolv blanke felter sælgeren skal gætte
    relevansen af, spørger vi om det der faktisk mangler.
    """
    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    brief = seller_brief or {}
    parts = [f"# Kunde: {client_name}\n"]

    if cvr_data:
        parts.append("## Hvad vi allerede kan slå op (spørg IKKE om dette)\n")
        for label, key in [("Branche", "industry_desc"), ("Ansatte", "employees"), ("Hjemmeside", "website")]:
            if cvr_data.get(key):
                parts.append(f"- {label}: {cvr_data[key]}")
        parts.append("")

    parts.append("## Mødeopsætning\n")
    parts.append(f"- Stakeholder: {stakeholder_key or 'ikke angivet'}")
    parts.append(f"- Mødestadie: {brief.get('meeting_stage') or 'ikke angivet'}")
    parts.append(f"- Pitch-længde: {pitch_length}")
    if services_to_highlight:
        parts.append(f"- Services i spil: {', '.join(services_to_highlight)}")
    parts.append("")

    parts.append("## Hvad sælgeren har skrevet indtil nu\n")
    written = [
        (label, brief.get(key) or (pitch_focus if key == "pitch_focus" else None))
        for key, label in [
            ("pitch_focus", "Pitch-vinkel"),
            ("meeting_history", "Mødehistorik"),
            ("personal_angle", "Om mødedeltageren"),
            ("insider_insights", "Insider-viden"),
            ("exclusions", "Må ikke nævnes"),
        ]
    ]
    filled = [(l, v) for l, v in written if v]
    if filled:
        for label, value in filled:
            parts.append(f"**{label}**: {value}")
    else:
        parts.append("*Intet udfyldt endnu — sælgeren er lige begyndt.*")
    parts.append("")

    tomme = [l for l, v in written if not v]
    if tomme:
        parts.append(f"*Endnu tomme felter: {', '.join(tomme)}*\n")

    parts.append("---")
    parts.append("Stil de 2-3 spørgsmål der vil løfte denne pitch mest. Returnér via `deliver_brief_questions`.")

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=_BRIEF_QUESTIONS_SYSTEM,
            tools=[_BRIEF_QUESTIONS_TOOL],
            tool_choice={"type": "tool", "name": "deliver_brief_questions"},
            messages=[{"role": "user", "content": "\n".join(parts)}],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "deliver_brief_questions":
                return block.input
    except Exception as e:
        # Kaster videre — kalderen skal kunne vise sælgeren HVORFOR det fejlede.
        # "Prøv igen" hjælper ikke hvis problemet er en tom API-konto.
        raise RuntimeError(str(e)) from e

    return None


def build_pitch_contract(**kwargs) -> Optional[Dict[str, Any]]:
    """Offentligt indgangspunkt til Stage 0. Kaldes af /api/research FØR web-search,
    så kontraktens `research_queries` kan styre hvad der bliver søgt efter."""
    return _build_pitch_contract(**kwargs)


def _short_length_label(pitch_length: Optional[str]) -> str:
    return {
        "short": "8-10 slides, max 80 tegn pr bullet",
        "medium": "13-15 slides, normal dybde",
        "long": "20+ slides, maks dybde",
    }.get(pitch_length or "medium", "13-15 slides")


def _format_contract_for_prompt(contract: Dict[str, Any]) -> str:
    """Format pitch-kontrakten som en kompakt prompt-blok."""
    if not contract:
        return ""
    parts = [
        "## 🔒 AUTORITATIV PITCH-KONTRAKT (denne trumfer alt andet)",
        "",
        f"**Kerne-intent**: {contract.get('core_intent', '')}",
        f"**Tone**: {contract.get('tone_directive', '')}",
        f"**Slide-antal**: {contract.get('expected_slide_count', '')}",
        f"**Næste skridt-stil**: {contract.get('next_steps_style', '')}",
        "",
        "**SKAL inkluderes:**",
    ]
    for item in contract.get("must_include", []):
        parts.append(f"- {item}")
    parts.append("\n**SKAL UNDGÅS:**")
    for item in contract.get("must_exclude", []):
        parts.append(f"- {item}")
    parts.append(
        "\n**Research-prioriteter** — det pitchen har brug for at vide. De blev formuleret "
        "FØR researchen blev indsamlet, så de er spørgsmål, ikke svar:"
    )
    for item in contract.get("research_priorities", []):
        parts.append(f"- {item}")

    queries = contract.get("research_queries") or []
    if queries:
        parts.append("\nDer blev søgt målrettet efter: " + " · ".join(f"«{q}»" for q in queries))

    parts.append(
        "\n**Sådan bruger du dem:** Materialet nedenfor er indsamlet for at besvare netop disse "
        "spørgsmål. Træk det ud der besvarer dem. Fandt søgningen ikke svar på et af dem — så påstå "
        "det ikke alligevel; lad prioriteten falde og nævn hullet i `coverage_report.missing_input`.\n"
        "\nDu SKAL respektere kontrakten i alt output."
    )
    return "\n".join(parts)


def _critique_and_refine(
    initial_analysis: Dict[str, Any],
    original_brief_text: str,
    stakeholder_key: Optional[str] = None,
    pitch_contract: Optional[Dict[str, Any]] = None,
    pitch_length: Optional[str] = "medium",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Stage 2: Claude læser sit eget udkast med kritisk blik MOD pitch-kontrakten
    og leverer en forbedret version. Kontrakten trumfer Claude's egne præferencer.

    Args:
        initial_analysis: Output fra første Claude-kald
        original_brief_text: Den oprindelige brief sælger gav
        stakeholder_key: For tone-tilpasning
        pitch_contract: Stage 0-kontrakt — autoritativ
        pitch_length: For dynamisk schema

    Returns:
        Forbedret JSON i samme struktur som input
    """
    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    contract_block = _format_contract_for_prompt(pitch_contract) if pitch_contract else ""

    # Bygger user-message: kontrakt + udkast
    parts = []
    if contract_block:
        parts.append(contract_block)
        parts.append("\n---\n")

    parts.append("## UDKAST DER SKAL TJEKKES MOD KONTRAKTEN OG FORBEDRES\n")
    parts.append("```json")
    parts.append(json.dumps(initial_analysis, indent=2, ensure_ascii=False))
    parts.append("```")

    parts.append("""
## DIN OPGAVE

Læs udkastet IGENNEM mod kontrakten. Tjek SPECIFIKT:

1. **Omfang**: Matcher antal facts/prioriteter/mappings kontraktens 'expected_slide_count'?
2. **Tone**: Er hver bullet i den tone kontrakten beskriver?
3. **MUST_INCLUDE**: Er hver punkt fra kontrakten dækket et sted i pitchen?
4. **MUST_EXCLUDE**: Er nogen af de forbudte temaer sneget med ind?
5. **Research-prioriteter**: Bruger pitchen KUN de research-prioriteter kontrakten godkendte?
6. **Næste skridt**: Matcher de kontraktens 'next_steps_style'?

7. **Slide-overskrifter**: Taler `slide_headlines` til DENNE stakeholder, eller kunne de sidde på en hvilken som helst pitch?
8. **Relevans-test på facts**: Består hver fact begge dele — ikke-indlysende for kunden OG handlingsbar for os? Er `why_it_matters` en reel indsigt eller en omskrivning af faktaet?

Hvis du finder problemer — TILBAGE-RUL. Kontraktens vilje trumfer dine egne præferencer for hvad der er pitch-mæssigt 'pænt'.

## Dækningsrapporten skal skrives HELT FORFRA

`coverage_report` i udkastet beskriver udkastet — ikke din rettede version. Skriv den om fra bunden,
så den beskriver dét du returnerer nu.

Vær ærlig i den. Rapporten læses af sælgeren for at finde ud af hvor de skal gribe ind, og en rapport
der siger at alt lykkedes er værdiløs. Har du udeladt noget fra briefen — skriv det i `dropped` med
den rigtige grund. Er der et svagt slide — og det er der altid — så peg på det i `weakest_slide`
og fortæl hvad sælgeren konkret kan tilføje.

Returnér forbedret JSON via `deliver_pitch_research`.""")

    user_message = "\n".join(parts)

    # Brug samme dynamiske schema som Stage 1 — pitch_length skal respekteres
    analysis_tool = _build_analysis_tool(pitch_length or "medium")

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=_CRITIQUE_SYSTEM_PROMPT,
        tools=[analysis_tool],
        tool_choice={"type": "tool", "name": "deliver_pitch_research"},
        messages=[{"role": "user", "content": user_message}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "deliver_pitch_research":
            return block.input

    # Fallback hvis critique fejler — returnér original
    return initial_analysis


# Kort service-oversigt (fallback hvis knowledge-base fejler).
# Detaljerne ligger nu i knowledge/services/*.md
EPICO_SERVICES = {
    "Epico Freelance": "Hurtig levering af erfarne IT-konsulenter (+10 års erfaring).",
    "Epico Projektansættelser": "Try-before-hire — 6 måneders prøveperiode med mulighed for permanent ansættelse uden rekrutteringsfee.",
    "Epico NextGen": "IT-talenter med 0-5 års erfaring. Try-before-hire model. +1.500 aktive profiler.",
    "Epico Search": "Headhunting af IT-ledere og specialister til faste stillinger. +3.100 succesfulde rekrutteringer. 6 mdr garanti.",
    "Epico Public": "Specialister via SKI 02.06, 02.14, 02.17 til offentlig sektor.",
    "Epico Solution": "CoE-baseret leveringsmodel — RUN & BUILD. Komplette IT-løsninger med kunde-ejet arkitektur.",
}


# Schema-størrelser pr pitch-længde
# Kort = færre items, lang = flere — Claude tvinges fysisk til at respektere længden
_SCHEMA_SIZES = {
    "short": {
        "facts": (2, 3), "priorities": (2, 3), "mappings": (2, 3),
        "case_bullets": (2, 3), "next_steps": (2, 3),
    },
    "medium": {
        "facts": (4, 4), "priorities": (3, 3), "mappings": (4, 4),
        "case_bullets": (3, 3), "next_steps": (3, 3),
    },
    "long": {
        "facts": (4, 5), "priorities": (3, 4), "mappings": (4, 5),
        "case_bullets": (3, 4), "next_steps": (3, 4),
    },
}


def _build_analysis_tool(pitch_length: str = "medium") -> Dict[str, Any]:
    """Generer schema dynamisk baseret på pitch_length så Claude TVINGES til
    at respektere antal items (kort = færre, lang = flere)."""
    sizes = _SCHEMA_SIZES.get(pitch_length, _SCHEMA_SIZES["medium"])
    fmin, fmax = sizes["facts"]
    pmin, pmax = sizes["priorities"]
    mmin, mmax = sizes["mappings"]
    cbmin, cbmax = sizes["case_bullets"]
    nsmin, nsmax = sizes["next_steps"]

    tool = json.loads(json.dumps(ANALYSIS_TOOL))  # deep copy
    props = tool["input_schema"]["properties"]

    props["research_facts"]["minItems"] = fmin
    props["research_facts"]["maxItems"] = fmax
    props["strategic_priorities"]["minItems"] = pmin
    props["strategic_priorities"]["maxItems"] = pmax
    props["value_mappings"]["minItems"] = mmin
    props["value_mappings"]["maxItems"] = mmax
    props["next_steps"]["minItems"] = nsmin
    props["next_steps"]["maxItems"] = nsmax

    # Case-bullets
    cprops = props["case_recommendation"]["properties"]
    for key in ("what", "why", "result", "value"):
        if key in cprops:
            cprops[key]["minItems"] = cbmin
            cprops[key]["maxItems"] = cbmax

    return tool


# Tool schema som Claude skal returnere data i
ANALYSIS_TOOL = {
    "name": "deliver_pitch_research",
    "description": "Returnér struktureret research om kunden, klar til at indsætte i pitch deck.",
    "input_schema": {
        "type": "object",
        "properties": {
            "industry_tag": {
                "type": "string",
                "description": "Branchekategori. Vælg én: Medtech, Pharma, Biotech, Finans, Energi, Forsyning, Retail, Public, Industri, Tech, Telco, Transport, Andet.",
            },
            "research_facts": {
                "type": "array",
                "description": (
                    "Fakta om kunden der beviser at vi har gjort hjemmearbejdet. "
                    "**RELEVANS-TESTEN — hver fact skal bestå BEGGE dele:**\n"
                    "1) **Ikke-indlysende for modtageren.** Kunden kender sin egen omsætning. "
                    "Et tal de selv har skrevet i deres årsrapport er kun interessant hvis du kobler det til noget de IKKE selv har sagt "
                    "(en konsekvens, en sammenligning, et mønster over tid).\n"
                    "2) **Handlingsbar for os.** Fakta skal kunne bruges som afsæt for noget Epico kan tilbyde. "
                    "Hvis du ikke kan svare på 'og derfor kan vi...' — så er den ikke relevant, uanset hvor imponerende den lyder.\n\n"
                    "En fact der kun består test 1 er trivia. En der kun består test 2 er et gæt. Begge, eller drop den."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Kort label, fx 'Vækst i medarbejderstab' eller 'Teknologi-skifte i gang'."
                        },
                        "value": {
                            "type": "string",
                            "description": "Konkret tal eller kort tekst. Fx '+340 ansatte på 2 år' eller 'SAP S/4HANA-migration annonceret Q1 2026'."
                        },
                        "source": {
                            "type": "string",
                            "description": "Kildehenvisning, fx 'Årsrapport 2024, s. 12', 'Pressemeddelelse 3. feb 2026' eller 'Epico-netværk' (når sælger har oplyst den)."
                        },
                        "why_it_matters": {
                            "type": "string",
                            "description": (
                                "INTERN note (vises ikke på sliden — kun til sælger i review). Max 140 tegn. "
                                "Skal besvare: hvad er det ikke-indlysende her, OG hvad kan vi konkret gøre ved det? "
                                "Format: '[indsigt] → [vores åbning]'. "
                                "Eksempel: 'Vækst uden tilsvarende IT-rekruttering → de mangler kapacitet, ikke strategi.' "
                                "Kan du ikke skrive en troværdig sådan — så er faktaet ikke relevant nok. Vælg et andet."
                            )
                        },
                    },
                    "required": ["key", "value", "source", "why_it_matters"],
                },
                "minItems": 4,
                "maxItems": 4,
            },
            "research_facts_alternates": {
                "type": "array",
                "description": (
                    "3 EKSTRA fakta som sælger kan bytte ind i stedet for dem ovenfor. "
                    "Disse skal bestå samme relevans-test, men vælge en ANDEN vinkel end de valgte — "
                    "fx en anden kilde, et andet forretningsområde, en anden tidshorisont. "
                    "Sælgeren kender kunden bedre end du gør; giv reelle alternativer, ikke andenrangs-rester."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                        "source": {"type": "string"},
                        "why_it_matters": {
                            "type": "string",
                            "description": "Samme format som ovenfor: '[indsigt] → [vores åbning]'. Max 140 tegn."
                        },
                    },
                    "required": ["key", "value", "source", "why_it_matters"],
                },
                "minItems": 3,
                "maxItems": 3,
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
                            "description": "Hvilken Epico-service løser dette: Epico Freelance, Epico Projektansættelser, Epico NextGen, Epico Search, Epico Public eller Epico Solution."
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
            "slide_headlines": {
                "type": "object",
                "description": (
                    "Overskrifterne til de fire kundespecifikke slides. De fire slides stiller ALTID de samme fire spørgsmål "
                    "(hvad ved vi · hvor skal I hen · hvor kan vi hjælpe · hvad gør vi nu) — men RAMMEN skal matche "
                    "hvem der sidder i lokalet, hvad mødet handler om, og hvad sælger har skrevet i sin brief.\n\n"
                    "Skriv IKKE generiske overskrifter. En Procurement-chef og en CIO skal ikke se den samme sætning:\n"
                    "· CIO → 'Dette ved vi om jeres IT-landskab'\n"
                    "· Procurement → 'Sådan ser jeres leverandørbillede ud'\n"
                    "· CFO → 'Hvor jeres IT-omkostninger ligger i dag'\n"
                    "· HR → 'Hvad jeres rekrutteringstal fortæller'\n\n"
                    "Markér 1-3 ord med **stjerner** — de bliver farvet som accent. Præcis ét accent-udtryk pr. overskrift."
                ),
                "properties": {
                    "research": {
                        "type": "object",
                        "properties": {
                            "eyebrow": {"type": "string", "description": "Max 40 tegn. Rammesætter hvorfor vi viser dette. Fx 'Vi har gjort hjemmearbejdet' eller 'Jeres leverandørsituation'."},
                            "heading": {"type": "string", "description": "Max 70 tegn. Hovedoverskrift for research-sliden, i stakeholderens sprog. Brug **stjerner** om accent-ordene."},
                        },
                        "required": ["eyebrow", "heading"],
                    },
                    "priorities": {
                        "type": "object",
                        "properties": {
                            "eyebrow": {"type": "string", "description": "Max 40 tegn."},
                            "heading": {"type": "string", "description": "Max 70 tegn. Overskrift for de strategiske prioriteter. Brug **stjerner**."},
                        },
                        "required": ["eyebrow", "heading"],
                    },
                    "mapping": {
                        "type": "object",
                        "properties": {
                            "eyebrow": {"type": "string", "description": "Max 40 tegn."},
                            "heading": {"type": "string", "description": "Max 70 tegn. Overskrift for udfordring→løsning-koblingen. Brug **stjerner**."},
                        },
                        "required": ["eyebrow", "heading"],
                    },
                    "next_steps": {
                        "type": "object",
                        "properties": {
                            "eyebrow": {"type": "string", "description": "Max 40 tegn."},
                            "heading": {"type": "string", "description": "Max 70 tegn. Overskrift for næste skridt. Brug **stjerner**."},
                        },
                        "required": ["eyebrow", "heading"],
                    },
                },
                "required": ["research", "priorities", "mapping", "next_steps"],
            },
            "coverage_report": {
                "type": "object",
                "description": (
                    "En ÆRLIG selvrapport til sælgeren om hvordan deres input blev brugt. Dette vises kun i review-fanen, "
                    "aldrig i pitchen. Vær kritisk over for dit eget arbejde — en rapport der siger 'alt gik perfekt' "
                    "er ubrugelig. Sælgeren skal kunne se hvor de skal gribe ind."
                ),
                "properties": {
                    "brief_usage": {
                        "type": "array",
                        "description": "Ét punkt pr. konkret ting sælger skrev i sin brief, som faktisk landede i pitchen.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "input": {"type": "string", "description": "Hvad sælger skrev — citér kort, max 80 tegn."},
                                "landed_in": {"type": "string", "description": "Hvor det endte. Fx 'Research-slide, fact 2' eller 'Næste skridt 1 + tone gennem hele pitchen'."},
                                "how": {"type": "string", "description": "Hvordan det blev brugt — max 120 tegn. Konkret, ikke 'blev taget i betragtning'."},
                            },
                            "required": ["input", "landed_in", "how"],
                        },
                        "minItems": 1,
                        "maxItems": 8,
                    },
                    "dropped": {
                        "type": "array",
                        "description": (
                            "Ting fra sælgers brief du IKKE brugte — og hvorfor. Vær ærlig. Typiske grunde: "
                            "pitch-længden gav ikke plads, det stred mod en eksklusion, det passede ikke til stakeholderen, "
                            "eller du kunne ikke finde noget i research der bakkede det op. Tom liste er kun troværdig "
                            "hvis briefen var meget kort."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "input": {"type": "string", "description": "Hvad sælger skrev — max 80 tegn."},
                                "why": {"type": "string", "description": "Hvorfor det ikke kom med — max 120 tegn. Konkret grund."},
                            },
                            "required": ["input", "why"],
                        },
                        "maxItems": 6,
                    },
                    "weakest_slide": {
                        "type": "object",
                        "description": "Det svageste slide i pitchen. Der ER altid ét. Peg på det.",
                        "properties": {
                            "slide": {"type": "string", "description": "Hvilket slide, fx 'Value mappings' eller 'Case'."},
                            "why": {"type": "string", "description": "Hvad er svagt ved det — max 140 tegn. Fx 'Bygger på branchegæt, ikke på noget kunden selv har sagt.'"},
                            "what_would_fix_it": {"type": "string", "description": "Hvad sælger konkret kan tilføje for at løfte det — max 140 tegn. Formulér som noget sælgeren kan skrive i briefen."},
                        },
                        "required": ["slide", "why", "what_would_fix_it"],
                    },
                    "missing_input": {
                        "type": "array",
                        "description": "1-3 ting du ville have haft gavn af at vide, som sælger ikke oplyste. Formulér som direkte spørgsmål.",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 3,
                    },
                },
                "required": ["brief_usage", "dropped", "weakest_slide", "missing_input"],
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
            "industry_tag",
            "slide_headlines",
            "research_facts",
            "research_facts_alternates",
            "strategic_priorities",
            "value_mappings",
            "next_steps",
            "case_recommendation",
            "coverage_report",
        ],
    },
}


_CRITIQUE_SYSTEM_PROMPT = """Du er en KRITISK pitch-anmelder hos Epico — som en erfaren Procurement-direktør eller CIO der har set tusindvis af konsulenthus-pitches.

Du modtager:
1. En **AUTORITATIV PITCH-KONTRAKT** der definerer hvad pitchen SKAL og IKKE må indeholde
2. Et udkast til pitch-research (JSON med facts, priorities, mappings, service-slides, case, next steps)

Din opgave: Tjek udkastet MOD kontrakten og lever en forbedret version der respekterer kontrakten 100%.

**KONTRAKTEN TRUMFER ALT.** Hvis du synes pitchen kunne være "pænere" på en måde der bryder kontrakten — så lad være. Sælgers intent vinder over din egen smag.

## Kritiske checkpunkter

For hver del af udkastet, spørg:

**Research-facts (slide 4):**
- Er hver fact konkret og verificerbar, eller generisk? ('Stor digital transformation' → blød. '$1.4B digital investering frem mod 2025' → konkret.)
- Citerer vi kilden specifikt nok? ('Årsrapport' → blød. 'Årsrapport 2024, s. 12' → konkret.)
- Bringer hver fact NYHEDSVÆRDI for kunden, eller er det noget de selv ved?

**Strategic priorities (slide 5):**
- Er hver prioritet specifik for DENNE stakeholder, eller kunne den genbruges på enhver kunde?
- Læser den som noget kunden selv ville sige, eller som corporate-snak?
- Kobler den til konkrete observationer fra årsrapport/web/brief?

**Value mappings (slide 6):**
- Er udfordringen formuleret konkret nok? (Ikke 'behov for IT-konsulenter', men 'akut behov for Oracle-DBA til S/4HANA-migration i Q3')
- Differentierer løsningen Epico, eller kunne en anden leverandør sige det samme?
- Hvis sælger har angivet konkurrent: skubber mapping mod hvorfor VI er bedre end DEM?

**Case (slide 16):**
- Er headline slagkraftig?
- Er resultaterne kvantitative (tal, %, antal)?
- Er case-branchen sammenlignelig med kundens?

**Next steps (slide 17):**
- Er hvert næste skridt EKSEKVERBART (konkret action, ikke 'tag en dialog')?
- Matcher det stakeholder-typen? (Procurement → RFP. IT-leder → workshop.)
- Er der en logisk progression (lille commitment → større)?

## Generelle regler for forbedring

- **Tal trumfer ord.** Hvis du kan udskifte et adjektiv med et tal, gør det.
- **Specifik > generisk.** "Java-udvikler med Spring Boot 3.2 + Kubernetes" slår "senior backend-udvikler".
- **Konsekvent tone.** Hvis stakeholder er Procurement, må ingen bullet falde tilbage til strategisk-CEO-tone.
- **Drop fyld.** Hver bullet skal kunne forsvares som "dette ville sælgeren faktisk sige højt".
- **Tjek eksklusioner.** Hvis sælger har skrevet 'undgå Nordea-reference' og du nævner Nordea — fjern det.

Returnér en KOMPLET forbedret version i samme JSON-struktur som input. Behold det der var godt; forbedre kun det der ikke holder vand.

Returnér ALTID via `deliver_pitch_research`-værktøjet."""




_MEETING_STAGE_DESCRIPTIONS = {
    "first_touch": "Dette er **første gang** I taler med kunden. Antag intet kendskab. Vær respektfuld for deres tid og hold strukturen tydelig.",
    "re_engage": "I har **mødtes før, men dialogen er gået kold**. Genoplive uden at gentage. Henvis subtilt til hvad I tidligere har talt om hvis relevant.",
    "existing_customer": "Kunden er **allerede en eksisterende kunde**. Pitchen handler om at udvide samarbejdet — ikke at sælge sig ind fra bunden. Spring 'hvem er vi'-passager kort over.",
    "renewal": "Kunden er **eksisterende og samarbejdet skal forlænges eller udvides**. Fokusér på dokumenteret værdi I har leveret + næste fase. Mindre 'sælg', mere 'optimér'.",
}


_PITCH_LENGTH_DESCRIPTIONS = {
    "short": """**Pitch-længde: KORT** (15-20 min møde, 8-10 slides total).

- Hold ALLE bullets UNDER 80 tegn. Tagline-style.
- Drop adjektiver. Hver sætning skal kunne læses på 3 sekunder.
- Strategic priorities: titel max 50 tegn, description max 120 tegn.
- Value mappings: challenge max 80 tegn, solution max 100 tegn.
- Case-intro: 1 sætning.
- Næste skridt: 1 sætning per description.
- Vær nådesløs med at skære: kun det der DIREKTE understøtter pitch-vinklen.""",

    "medium": """**Pitch-længde: MEDIUM** (30-45 min møde, 13-15 slides total). Default.

- Normal dybde. 80-100 tegn per bullet.
- Balancér mellem konkrete detaljer og læsbarhed.""",

    "long": """**Pitch-længde: LANG** (60+ min deep-dive, 20+ slides).

- Maks dybde. 100-130 tegn per bullet.
- Strategic priorities: brug op til 200 tegn per description til at uddybe.
- Value mappings: solution kan være op til 180 tegn med konkret reasoning.""",
}




def _build_system_prompt(
    pitch_focus: Optional[str] = None,
    services_to_highlight: Optional[List[str]] = None,
    seller_brief: Optional[Dict[str, Optional[str]]] = None,
    slide_dictation: Optional[Dict[str, Optional[str]]] = None,
    stakeholder_key: Optional[str] = None,
    pitch_length: Optional[str] = "medium",
) -> str:
    # Sælger-direktiver — disse er styrende
    directives = []

    # Pitch-længde (styrer dybde og antal bullets)
    if pitch_length and pitch_length in _PITCH_LENGTH_DESCRIPTIONS:
        directives.append(
            "## 📏 PITCH-LÆNGDE (styrer dybde)\n\n"
            + _PITCH_LENGTH_DESCRIPTIONS[pitch_length]
        )

    # ── DE FEM AUTORITETSTYPER ────────────────────────────────────────────
    # Sælgers input er IKKE én udifferentieret klump. Hver type har sin egen
    # regel for hvordan den vinder over — eller samarbejder med — research.

    brief = seller_brief or {}
    dictation = slide_dictation or {}

    # TYPE 1 — BEGRÆNSNING. Absolut. Ingen afvejning.
    if brief.get("exclusions"):
        directives.append(
            "## ⛔ BEGRÆNSNINGER — ABSOLUTTE\n\n"
            "Sælgeren har angivet hvad der IKKE må optræde i pitchen. Dette er ikke en præference "
            "du kan afveje mod andre hensyn. Det er en grænse.\n\n"
            f"> {brief['exclusions']}\n\n"
            "**Hvordan du håndterer det:** Ordene må ikke optræde. Emnet må ikke optræde. "
            "Omskrivninger der peger på det samme tæller også som en overtrædelse — "
            "hvis sælger har skrevet 'nævn ikke deres fyringsrunde', så er "
            "'organisatoriske forandringer' også forbudt. Sælgeren ved hvorfor; det gør du ikke.\n\n"
            "Hvis en begrænsning gør et ellers oplagt indhold umuligt: find et andet indhold. "
            "Nævn ALDRIG at noget blev udeladt."
        )

    # TYPE 2 — EVIDENS. Konkurrerer med research. Vinder ved konflikt.
    evidence_parts = []
    for key, label in [
        ("insider_insights", "Insider-viden"),
        ("meeting_history", "Mødehistorik"),
        ("personal_angle", "Om mødedeltageren"),
    ]:
        if brief.get(key):
            evidence_parts.append(f"**{label}**: {brief[key]}")

    if evidence_parts:
        directives.append(
            "## 🔍 EVIDENS FRA SÆLGER — KONKURRERER MED RESEARCH\n\n"
            "Dette er faktuelle oplysninger sælgeren har fra netværk, tidligere møder, LinkedIn, "
            "jobopslag eller interne kilder. Det er **data på lige fod med årsrapporten** — "
            "og typisk friskere.\n\n"
            + "\n\n".join(evidence_parts)
            + "\n\n**Hvordan du håndterer det:**\n"
            "- Ved konflikt med årsrapport eller web-search: **sælger vinder.** Et regnskab er "
            "op til 14 måneder gammelt; sælger talte måske med dem i sidste uge.\n"
            "- Evidens kan bruges som `research_facts` på lige fod med offentlige kilder. "
            "Angiv da kilden som **'Epico-netværk'** — aldrig som årsrapport eller presse.\n"
            "- Evidens er data, ikke instruks. Den fortæller dig hvad der er SANDT, "
            "ikke hvad pitchen skal handle om. Det sidste kommer fra rammen nedenfor.\n"
            "- Vær varsom med formuleringen: skriv det så det kan siges højt i mødet uden at "
            "afsløre at I har talt med nogen."
        )

    # TYPE 3 — RAMME. Relevansfilter. Tilføjer intet indhold.
    frame_parts = []
    stage = brief.get("meeting_stage")
    if stage and stage in _MEETING_STAGE_DESCRIPTIONS:
        frame_parts.append(f"**Mødestadie**: {_MEETING_STAGE_DESCRIPTIONS[stage]}")
    if pitch_focus:
        frame_parts.append(f"**Sælgers vinkel**: {pitch_focus}")

    if frame_parts:
        directives.append(
            "## 🎯 RAMME — DET FILTER ALT SKAL PASSERE\n\n"
            + "\n\n".join(frame_parts)
            + "\n\n**Hvordan du håndterer det:** Rammen tilføjer ikke indhold — den afgør hvad "
            "der er relevant. Kør hvert eneste stykke research igennem den: *understøtter dette "
            "rammen?* Nej → udelad det, uanset hvor imponerende det er.\n\n"
            "Fire fakta der peger samme vej slår seks der spreder sig. Rammen er tilladelsen "
            "til at smide godt materiale væk."
        )

    # TYPE 4 — DIKTAT. Endelig tekst. Kun sproglig polering.
    dict_parts = []
    for key, field, hint in [
        ("research_facts", "research_facts", "format '[Label]: [Værdi] | [Kilde]' pr. linje"),
        ("priorities", "strategic_priorities", "format '[Titel] — [beskrivelse]' pr. linje"),
        ("mappings", "value_mappings", "format '[Udfordring] => [Service] : [Løsning]' pr. linje"),
        ("next_steps", "next_steps", "format '[Titel] | [tidsramme] — [beskrivelse]' pr. linje"),
    ]:
        if dictation.get(key):
            dict_parts.append(
                f"**→ `{field}`** ({hint}):\n```\n{dictation[key]}\n```"
            )

    if dict_parts:
        directives.append(
            "## ✍️ DIKTERET INDHOLD — ENDELIGT\n\n"
            "Sælgeren har skrevet indholdet til bestemte felter selv. Det er ikke et forslag "
            "du skal forbedre — det er beslutningen.\n\n"
            + "\n\n".join(dict_parts)
            + "\n\n**Hvordan du håndterer det:** Du må rette stavefejl, ensrette tegnsætning og "
            "tilpasse længden til pitch-formatet. Du må **ikke** ændre pointen, tilføje forbehold, "
            "gøre sproget mere sælgende, eller bytte sælgers ord ud med dine egne fordi de lyder bedre.\n\n"
            "Har sælger givet færre punkter end feltet kræver: supplér med dine egne, "
            "men placér altid sælgers først.\n\n"
            "Felter der ikke er nævnt her genererer du helt normalt."
        )

    # TYPE 5 — STRUKTUR. Form, ikke indhold.
    structure_parts = []
    if services_to_highlight:
        structure_parts.append(
            f"**Services i spil**: {', '.join(services_to_highlight)} — "
            "dine `value_mappings` skal mappe til DISSE. Samme service må gerne gå igen "
            "(forskellige aspekter). Inddrag ikke fravalgte services."
        )
    if stakeholder_key:
        structure_parts.append(
            f"**Stakeholder**: `{stakeholder_key}` — profilen står i vidensbasen nedenfor. "
            "Den styrer tone, hvilke slides der giver mening, og hvilke næste skridt der lander."
        )

    if structure_parts:
        directives.append(
            "## ⚙️ STRUKTUR — FORM, IKKE INDHOLD\n\n"
            + "\n\n".join(structure_parts)
            + "\n\n**Hvordan du håndterer det:** Dette bestemmer pitchens *form* — "
            "hvor mange slides, hvilke services, hvilken tone. Det bestemmer ikke hvad der er "
            "sandt om kunden. Lad ikke strukturvalg presse dig til at påstå noget research "
            "ikke bakker op."
        )

    # Hierarkiet — eksplicit, så modellen ikke selv skal gætte
    if directives:
        directives.append(
            "## ⚖️ NÅR TO INPUT PEGER FORSKELLIGT\n\n"
            "1. **Begrænsning** slår alt. Ingen undtagelser.\n"
            "2. **Diktat** slår dine egne formuleringer for de felter det dækker.\n"
            "3. **Evidens** slår årsrapport, web-search og CVR ved faktuel konflikt.\n"
            "4. **Ramme** afgør hvad der overhovedet kommer i betragtning.\n"
            "5. **Struktur** afgør hvor meget der er plads til.\n\n"
            "Bemærk at de ikke er rangeret efter vigtighed, men efter *hvad de gør*. "
            "En begrænsning og en ramme kan ikke være uenige — de arbejder på hvert sit niveau."
        )

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
    stakeholder_key: Optional[str] = None,
    pitch_length: Optional[str] = "medium",
    pitch_contract: Optional[Dict[str, Any]] = None,
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
    """
    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    # ===== STAGE 0: Pitch-kontrakt =====
    # Normalt bygget af kalderen FØR web-search, så kontrakten kan styre hvad der
    # søges efter. Bygges her kun hvis kalderen ikke har gjort det.
    if pitch_contract is None:
        pitch_contract = _build_pitch_contract(
            client_name=client_name,
            cvr_data=cvr_data,
            annual_report_text=annual_report_text,
            website_text=website_text,
            web_intelligence=web_intelligence,
            seller_brief=seller_brief,
            slide_dictation=slide_dictation,
            pitch_focus=pitch_focus,
            services_to_highlight=services_to_highlight,
            stakeholder_key=stakeholder_key,
            pitch_length=pitch_length,
            api_key=api_key,
        )
    contract_block = _format_contract_for_prompt(pitch_contract) if pitch_contract else ""

    # ===== STAGE 1: Initial draft =====
    # Byg user message med al kontekst
    parts = [f"# Kunde: {client_name}\n"]

    # Pitch-kontrakt ØVERST i Stage 1
    if contract_block:
        parts.append(contract_block)
        parts.append("\n---\n")

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
        parts.append("")

    # SLIDE-DICTATION (specifikke felter sælger har styret)
    if slide_dictation and any(slide_dictation.values()):
        parts.append("## 📝 SÆLGER HAR DIKTERET SPECIFIKT INDHOLD TIL DISSE SLIDES\n")
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
    if pitch_focus or services_to_highlight:
        parts.append("## ⚠️ Pitch-direktiver (gentaget for tydelighed)\n")
        if pitch_focus:
            parts.append(f"**Pitch-vinkel**: {pitch_focus}")
        if services_to_highlight:
            parts.append(f"**Services at fremhæve**: {', '.join(services_to_highlight)}")
        parts.append("")

    parts.append("---")
    parts.append("Analysér nu kunden og returnér via `deliver_pitch_research`-værktøjet.")
    parts.append("**Husk autoritetstyperne:** Begrænsning > Diktat > Evidens > Ramme > Struktur. Se system-prompten.")

    user_message = "\n".join(parts)

    analysis_tool = _build_analysis_tool(pitch_length or "medium")
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=_build_system_prompt(
            pitch_focus=pitch_focus,
            services_to_highlight=services_to_highlight,
            seller_brief=seller_brief,
            slide_dictation=slide_dictation,
            stakeholder_key=stakeholder_key,
            pitch_length=pitch_length,
        ),
        tools=[analysis_tool],
        tool_choice={"type": "tool", "name": "deliver_pitch_research"},
        messages=[{"role": "user", "content": user_message}],
    )

    # Uddrag tool_use blokken (Stage 1 — initial draft)
    initial_analysis = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "deliver_pitch_research":
            initial_analysis = block.input
            break

    if initial_analysis is None:
        raise RuntimeError("Claude returnerede ikke struktureret data via tool-use.")

    # Stage 2 — Self-critique og refinement
    # Send pitch-kontrakten med så critique kan tjekke om Stage 1 respekterede den
    try:
        refined = _critique_and_refine(
            initial_analysis=initial_analysis,
            original_brief_text=user_message,
            stakeholder_key=stakeholder_key,
            pitch_contract=pitch_contract,
            pitch_length=pitch_length,
            api_key=api_key,
        )
        return refined
    except Exception:
        # Hvis critique fejler, fald tilbage til initial analyse
        return initial_analysis
