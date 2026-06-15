"""
Knowledge loader. Indlæser hele knowledge/-mappen som strukturet kontekst til Claude.

Strategien er: alle filer i knowledge/ er den eneste sandhed Claude må bruge om Epico.
"""
from pathlib import Path
from typing import Dict, Optional


KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


def load_stakeholder_profile(stakeholder_key: Optional[str]) -> str:
    """
    Load knowledge om en specifik stakeholder-type.
    stakeholder_key er en af: procurement, it-leader, hr-leader, executive,
    cfo, tech-lead, business-leader, eller None.
    """
    if not stakeholder_key:
        return ""
    safe = stakeholder_key.strip().lower().replace("_", "-")
    f = KNOWLEDGE_DIR / "stakeholders" / f"{safe}.md"
    if not f.exists():
        return ""
    text = f.read_text(encoding="utf-8").strip()
    return (
        f"# 🎯 STAKEHOLDER-PROFIL — DEN PERSON VI MØDES MED\n\n"
        f"Dette afsnit definerer HVEM sælger mødes med. Hele pitchen skal tilpasses denne person.\n"
        f"Slides, tone, formuleringer og næste skridt SKAL respektere stakeholder-profilen herunder.\n\n"
        f"{text}"
    )


def load_knowledge(stakeholder_key: Optional[str] = None) -> str:
    """
    Load alle markdown-filer i knowledge/ og returnér som én samlet streng,
    klar til indsætning i Claude's system prompt.

    Strukturen i output:
    - STAKEHOLDER (kun den valgte type, hvis angivet)
    - SERVICES (alle 7)
    - CASES (alle)
    - BOUNDARIES (det Epico IKKE leverer)
    - MESSAGING (tone of voice)
    - STATS (nøgletal)
    """
    sections = []

    # Stakeholder-profil ØVERST (kritisk — den vægter højest)
    if stakeholder_key:
        profile = load_stakeholder_profile(stakeholder_key)
        if profile:
            sections.append(profile)

    # Services
    services_dir = KNOWLEDGE_DIR / "services"
    if services_dir.exists():
        service_files = sorted(services_dir.glob("*.md"))
        if service_files:
            sections.append("# EPICO SERVICES — DETALJERET BESKRIVELSE\n")
            sections.append("Dette er den FULDE beskrivelse af hver service. Brug KUN disse beskrivelser når du foreslår løsninger.\n")
            for f in service_files:
                sections.append(f"\n---\n\n{f.read_text(encoding='utf-8').strip()}\n")

    # Cases
    cases_dir = KNOWLEDGE_DIR / "cases"
    if cases_dir.exists():
        case_files = sorted(cases_dir.glob("*.md"))
        if case_files:
            sections.append("\n\n# EPICO CASES — RIGTIGE KUNDE-EKSEMPLER\n")
            sections.append("Brug disse cases når du skal foreslå en case der ligner kundens situation. Skriv IKKE nye fiktive cases.\n")
            for f in case_files:
                sections.append(f"\n---\n\n{f.read_text(encoding='utf-8').strip()}\n")

    # Boundaries
    boundaries_file = KNOWLEDGE_DIR / "boundaries.md"
    if boundaries_file.exists():
        sections.append("\n\n# EPICO BOUNDARIES — DET HER LEVERER VI IKKE\n")
        sections.append("Læs dette omhyggeligt. Hvis kunden har et behov der falder uden for, må du ikke foreslå at Epico kan løse det.\n")
        sections.append(f"\n---\n\n{boundaries_file.read_text(encoding='utf-8').strip()}\n")

    # Messaging
    messaging_file = KNOWLEDGE_DIR / "messaging.md"
    if messaging_file.exists():
        sections.append("\n\n# EPICO MESSAGING — TONE OF VOICE\n")
        sections.append(f"\n---\n\n{messaging_file.read_text(encoding='utf-8').strip()}\n")

    # Stats
    stats_file = KNOWLEDGE_DIR / "stats.md"
    if stats_file.exists():
        sections.append("\n\n# EPICO STATS — NØGLETAL\n")
        sections.append("Brug KUN disse tal. Lav ikke nye tal op om Epico.\n")
        sections.append(f"\n---\n\n{stats_file.read_text(encoding='utf-8').strip()}\n")

    return "\n".join(sections)


def load_summary() -> Dict[str, int]:
    """
    Returnér en kort summary af hvad der er loaded (til debug/healthcheck).
    """
    services_dir = KNOWLEDGE_DIR / "services"
    cases_dir = KNOWLEDGE_DIR / "cases"
    return {
        "services_count": len(list(services_dir.glob("*.md"))) if services_dir.exists() else 0,
        "cases_count": len(list(cases_dir.glob("*.md"))) if cases_dir.exists() else 0,
        "has_boundaries": (KNOWLEDGE_DIR / "boundaries.md").exists(),
        "has_messaging": (KNOWLEDGE_DIR / "messaging.md").exists(),
        "has_stats": (KNOWLEDGE_DIR / "stats.md").exists(),
        "total_chars": len(load_knowledge()),
    }


if __name__ == "__main__":
    # Hurtig test
    summary = load_summary()
    print("Knowledge base summary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\n{'=' * 60}")
    print("Første 2000 tegn:")
    print(load_knowledge()[:2000])
