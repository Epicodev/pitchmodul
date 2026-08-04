"""
Deck-generator.

Bygger det færdige pitch deck af to dele:
  DEL 1: Kunde-slides (AI-genereret via claude_client)
  DEL 2: Epico-slides (statisk bibliotek i slide_library/, filtreret på
         pitch-længde + valgte services)
"""
from pathlib import Path
from typing import Dict, Any, List, Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape

from slide_library import select_slides

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
)

# Agenda-tider pr. pitch-længde (5 punkter)
_AGENDA_TIMINGS = {
    "short": ["3 min", "4 min", "4 min", "5 min", "4 min"],
    "medium": ["8 min", "10 min", "10 min", "10 min", "7 min"],
    "long": ["10 min", "15 min", "15 min", "15 min", "10 min"],
}


def _default_team_member(member: Optional[Dict[str, str]], fallback_title: str) -> Dict[str, Optional[str]]:
    member = member or {}
    return {
        "name": member.get("name") or "[Fornavn Efternavn]",
        "title": member.get("title") or fallback_title,
        "phone": member.get("phone") or "+45 00 00 00 00",
        "email": member.get("email") or "[navn]@epico.dk",
        "linkedin": member.get("linkedin"),
    }


def render_deck(
    client_name: str,
    analysis: Dict[str, Any],
    meeting: Optional[Dict[str, str]] = None,
    team: Optional[Dict[str, Dict[str, str]]] = None,
    pitch_length: str = "medium",
    services: Optional[List[str]] = None,
    stakeholder: Optional[str] = None,
    excluded_slide_ids: Optional[List[str]] = None,
    asset_base: str = "..",
) -> str:
    """
    Render det færdige pitch deck som HTML.

    Args:
        client_name: Kundens navn
        analysis: Output fra claude_client.analyze_client() — kunde-slides
        meeting: {"date", "city", "contact_person"}
        team: {"kam": {...}, "rm": {...}}
        pitch_length: 'short' | 'medium' | 'long' — styrer hvilke bibliotek-slides der vælges
        services: Valgte Epico-services — styrer hvilke service-slides der vises
        stakeholder: Stakeholder-key til filtrering
        excluded_slide_ids: Bibliotek-slides sælger har fravalgt
        asset_base: Sti til styles.css / app.js
    """
    meeting = meeting or {}
    team = team or {}

    # DEL 2 — hent Epico-slides fra biblioteket
    library = select_slides(
        pitch_length=pitch_length,
        services=services,
        stakeholder=stakeholder,
        excluded_ids=excluded_slide_ids,
    )

    context = {
        "client": {"name": client_name},
        "meeting": {
            "date": meeting.get("date") or "[DATO]",
            "city": meeting.get("city") or "[BYNAVN]",
            "contact_person": meeting.get("contact_person") or "[KONTAKTPERSON]",
        },
        "team": {
            "kam": _default_team_member(team.get("kam"), "Senior Key Account Manager"),
            "rm": _default_team_member(team.get("rm"), "Resource Manager"),
        },
        # Kunde-slides fra AI
        "research_facts": analysis.get("research_facts", []),
        "strategic_priorities": analysis.get("strategic_priorities", []),
        "value_mappings": analysis.get("value_mappings", []),
        "next_steps": analysis.get("next_steps", []),
        "case": analysis.get("case_recommendation", {}),
        "industry_tag": analysis.get("industry_tag", "branchen"),
        # Epico-slides fra bibliotek
        "library_slides": [s.to_dict() for s in library],
        # Meta
        "agenda_timings": _AGENDA_TIMINGS.get(pitch_length, _AGENDA_TIMINGS["medium"]),
        "pitch_length": pitch_length,
        "asset_base": asset_base,
    }

    return _env.get_template("pitch.html.j2").render(**context)


def preview_slide_plan(
    pitch_length: str = "medium",
    services: Optional[List[str]] = None,
    stakeholder: Optional[str] = None,
    excluded_slide_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Returnér hvilke slides der VILLE komme med — uden at generere noget.
    Bruges af Composer til at vise sælger et live-overblik.
    """
    library = select_slides(
        pitch_length=pitch_length,
        services=services,
        stakeholder=stakeholder,
        excluded_ids=excluded_slide_ids,
    )

    # Kunde-slides er altid med
    client_slides = [
        {"id": "cover", "title": "Cover", "category": "kunde"},
        {"id": "agenda", "title": "Agenda", "category": "kunde"},
        {"id": "research", "title": "Research om kunden", "category": "kunde"},
        {"id": "priorities", "title": "Strategiske prioriteter", "category": "kunde"},
        {"id": "mapping", "title": "Udfordring → løsning", "category": "kunde"},
    ]
    closing_slides = [
        {"id": "case", "title": "Relevant case", "category": "kunde"},
        {"id": "next-steps", "title": "Næste skridt", "category": "kunde"},
        {"id": "contact", "title": "Kontakt", "category": "kunde"},
    ]

    library_entries = [
        {
            "id": s.id,
            "title": s.title,
            "category": s.category,
            "layout": s.layout,
            "services": s.services,
        }
        for s in library
    ]

    chapter = (
        [{"id": "chapter-epico", "title": "Kapitel: Dette er Epico", "category": "kunde"}]
        if library_entries and pitch_length != "short"
        else []
    )

    return {
        "total": len(client_slides) + len(chapter) + len(library_entries) + len(closing_slides),
        "client_slides": client_slides,
        "library_slides": library_entries,
        "closing_slides": closing_slides,
        "pitch_length": pitch_length,
    }
