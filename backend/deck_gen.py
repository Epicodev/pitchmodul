"""
Deck-generator. Tager struktureret data fra Claude og renderer Jinja2-template.
"""
from pathlib import Path
from typing import Dict, Any, Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
)


def render_deck(
    client_name: str,
    analysis: Dict[str, Any],
    meeting: Optional[Dict[str, str]] = None,
    team: Optional[Dict[str, Dict[str, str]]] = None,
    asset_base: str = "..",
) -> str:
    """
    Render det færdige pitch deck.

    Args:
        client_name: Kundens navn (bruges på cover og som [KUNDE] overalt)
        analysis: Output fra claude_client.analyze_client() — indeholder
                  research_facts, strategic_priorities, value_mappings,
                  next_steps, case_recommendation, industry_tag, client_summary
        meeting: {"date": "...", "city": "...", "contact_person": "..."}
        team: {"kam": {...}, "rm": {...}}
        asset_base: Stien til styles.css og app.js relativt til output

    Returns:
        Færdig HTML-streng
    """
    meeting = meeting or {}
    team = team or {}

    context = {
        "client": {
            "name": client_name,
            "summary": analysis.get("client_summary", f"Vi mødes fordi {client_name} står midt i en transformation, hvor IT-kompetencer er afgørende — og vi mener, vi har et bud på, hvordan det kan løses uden at I skal kompromittere på kvalitet, kultur eller hastighed."),
        },
        "meeting": {
            "date": meeting.get("date", "[DATO]"),
            "city": meeting.get("city", "[BYNAVN]"),
            "contact_person": meeting.get("contact_person", "[KONTAKTPERSON]"),
        },
        "team": {
            "kam": {
                "name": team.get("kam", {}).get("name", "[Fornavn Efternavn]"),
                "title": team.get("kam", {}).get("title", "Senior Key Account Manager"),
                "phone": team.get("kam", {}).get("phone", "+45 00 00 00 00"),
                "email": team.get("kam", {}).get("email", "[navn]@epico.dk"),
                "linkedin": team.get("kam", {}).get("linkedin"),
            },
            "rm": {
                "name": team.get("rm", {}).get("name", "[Fornavn Efternavn]"),
                "title": team.get("rm", {}).get("title", "Resource Manager"),
                "phone": team.get("rm", {}).get("phone", "+45 00 00 00 00"),
                "email": team.get("rm", {}).get("email", "[navn]@epico.dk"),
                "linkedin": team.get("rm", {}).get("linkedin"),
            },
        },
        "research_facts": analysis.get("research_facts", []),
        "strategic_priorities": analysis.get("strategic_priorities", []),
        "value_mappings": analysis.get("value_mappings", []),
        "service_slides": analysis.get("service_slides", []),
        "next_steps": analysis.get("next_steps", []),
        "case": analysis.get("case_recommendation", {}),
        "industry_tag": analysis.get("industry_tag", "branchen"),
        "asset_base": asset_base,
    }

    template = _env.get_template("pitch.html.j2")
    return template.render(**context)
