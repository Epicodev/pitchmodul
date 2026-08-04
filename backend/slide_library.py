"""
Slide-bibliotek — statisk Epico-indhold som markdown-filer.

Arkitektur:
  DEL 1 (dette modul): Statiske Epico-slides i slide_library/*.md
                       Filtreres på pitch_length + services + stakeholder
  DEL 2 (claude_client): AI-genererede kunde-slides

Marketing kan redigere .md-filerne direkte uden at røre kode.

FORMAT — hver .md-fil:

    ---
    id: freelance-detail
    title: Freelance
    category: services
    length: [medium, long]         # hvilke pitch-længder inkluderer denne
    services: [Epico Freelance]    # kun med hvis servicen er valgt (tom = altid)
    stakeholders: []               # kun for disse stakeholders (tom = alle)
    layout: service-detail
    order: 30
    variant: light                 # light | dark | red
    ---

    # eyebrow
    DET FÅR I

    # heading
    Erfarne IT-konsulenter **på 48 timer.**

    # subheading
    Valgfri underoverskrift.

    # stats
    +500 | konsulenter på kontrakt
    +13.000 | CV'er i database

    # bullets
    Første bullet
    Anden bullet

    # cards
    ## Korttitel
    Kortets brødtekst
    ## Andet kort
    Anden brødtekst

    # footnote
    Kilde: et-eller-andet
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

LIBRARY_DIR = Path(__file__).parent / "slide_library"

# Pitch-længder i stigende orden — bruges til fallback-logik
LENGTH_ORDER = ["short", "medium", "long"]


@dataclass
class Card:
    """Et kort i et cards-layout: titel + brødtekst + valgfri bullets."""
    title: str = ""
    body: str = ""
    bullets: List[str] = field(default_factory=list)


@dataclass
class Stat:
    """Et nøgletal: værdi + label."""
    value: str = ""
    label: str = ""


@dataclass
class LibrarySlide:
    """En statisk Epico-slide fra biblioteket."""
    id: str
    title: str
    category: str
    layout: str
    order: int
    variant: str = "light"
    length: List[str] = field(default_factory=list)
    services: List[str] = field(default_factory=list)
    stakeholders: List[str] = field(default_factory=list)
    section_tag: str = ""

    eyebrow: str = ""
    heading: str = ""
    subheading: str = ""
    body: str = ""
    footnote: str = ""
    stats: List[Stat] = field(default_factory=list)
    bullets: List[str] = field(default_factory=list)
    cards: List[Card] = field(default_factory=list)

    source_file: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Til Jinja-template og PPTX-renderer."""
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "layout": self.layout,
            "order": self.order,
            "variant": self.variant,
            "section_tag": self.section_tag or self.title,
            "eyebrow": self.eyebrow,
            "heading": self.heading,
            "heading_html": _bold_to_accent(self.heading),
            "subheading": self.subheading,
            "body": self.body,
            "footnote": self.footnote,
            "stats": [{"value": s.value, "label": s.label} for s in self.stats],
            "bullets": self.bullets,
            "cards": [
                {"title": c.title, "body": c.body, "bullets": c.bullets}
                for c in self.cards
            ],
        }


def bold_to_accent(text: str) -> str:
    """Offentligt alias — bruges også af deck_gen til AI-genererede overskrifter."""
    return _bold_to_accent(text)


def _bold_to_accent(text: str) -> str:
    """Konvertér **fed** til <span class="accent"> så overskrifter kan fremhæve ord."""
    if not text:
        return ""
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return re.sub(r"\*\*(.+?)\*\*", r'<span class="accent">\1</span>', escaped)


def _parse_frontmatter(raw: str) -> tuple[Dict[str, Any], str]:
    """Split YAML-agtig frontmatter fra body. Understøtter kun de typer vi bruger."""
    if not raw.startswith("---"):
        return {}, raw

    end = raw.find("\n---", 3)
    if end == -1:
        return {}, raw

    fm_text = raw[3:end].strip()
    body = raw[end + 4 :].lstrip("\n")

    meta: Dict[str, Any] = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            items = [v.strip().strip("'\"") for v in inner.split(",")] if inner else []
            meta[key] = [i for i in items if i]
        elif value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
            meta[key] = int(value)
        else:
            meta[key] = value.strip("'\"")

    return meta, body


def _parse_body(body: str) -> Dict[str, Any]:
    """
    Parse sektions-baseret body. Sektioner startes med '# sektionsnavn'.
    Cards bruger '## Korttitel' inden i '# cards'.
    """
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            current = stripped[2:].strip().lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line.rstrip())

    def text_of(name: str) -> str:
        lines = [ln.strip() for ln in sections.get(name, [])]
        return "\n".join(ln for ln in lines if ln).strip()

    def list_of(name: str) -> List[str]:
        return [ln.strip() for ln in sections.get(name, []) if ln.strip()]

    stats: List[Stat] = []
    for line in list_of("stats"):
        value, _, label = line.partition("|")
        stats.append(Stat(value=value.strip(), label=label.strip()))

    cards: List[Card] = []
    current_card: Optional[Card] = None
    for line in sections.get("cards", []):
        stripped = line.strip()
        if stripped.startswith("## "):
            if current_card:
                cards.append(current_card)
            current_card = Card(title=stripped[3:].strip())
        elif current_card is not None and stripped:
            if stripped.startswith("- "):
                current_card.bullets.append(stripped[2:].strip())
            else:
                current_card.body = (
                    f"{current_card.body} {stripped}".strip()
                    if current_card.body
                    else stripped
                )
    if current_card:
        cards.append(current_card)

    return {
        "eyebrow": text_of("eyebrow"),
        "heading": text_of("heading"),
        "subheading": text_of("subheading"),
        "body": text_of("body"),
        "footnote": text_of("footnote"),
        "stats": stats,
        "bullets": list_of("bullets"),
        "cards": cards,
    }


def _parse_file(path: Path) -> Optional[LibrarySlide]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    meta, body = _parse_frontmatter(raw)
    if not meta.get("id"):
        return None

    parsed = _parse_body(body)

    return LibrarySlide(
        id=str(meta["id"]),
        title=str(meta.get("title", meta["id"])),
        category=str(meta.get("category", "misc")),
        layout=str(meta.get("layout", "bullets")),
        order=int(meta.get("order", 999)),
        variant=str(meta.get("variant", "light")),
        length=meta.get("length") or list(LENGTH_ORDER),
        services=meta.get("services") or [],
        stakeholders=meta.get("stakeholders") or [],
        section_tag=str(meta.get("section_tag", "")),
        source_file=str(path.relative_to(LIBRARY_DIR)) if path.is_relative_to(LIBRARY_DIR) else str(path),
        **parsed,
    )


_CACHE: Optional[List[LibrarySlide]] = None


def load_library(force: bool = False) -> List[LibrarySlide]:
    """Load alle slides fra biblioteket. Cachet i memory."""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE

    slides: List[LibrarySlide] = []
    if LIBRARY_DIR.exists():
        for path in sorted(LIBRARY_DIR.rglob("*.md")):
            if path.name.startswith("_"):
                continue
            slide = _parse_file(path)
            if slide:
                slides.append(slide)

    slides.sort(key=lambda s: (s.order, s.id))
    _CACHE = slides
    return slides


def reload_library() -> int:
    """Force-reload fra disk. Returnér antal slides."""
    return len(load_library(force=True))


# Max antal service-bundne slides når sælger IKKE har valgt specifikke services.
# Har sælger valgt services, vises alle de valgte uanset cap.
_SERVICE_SLIDE_CAP = {"short": 2, "medium": 4, "long": 99}


def select_slides(
    pitch_length: str = "medium",
    services: Optional[List[str]] = None,
    stakeholder: Optional[str] = None,
    excluded_ids: Optional[List[str]] = None,
) -> List[LibrarySlide]:
    """
    Filtrér biblioteket ned til de slides der hører til denne pitch.

    Regler:
      - length: sliden skal liste den valgte pitch-længde
      - services: hvis sliden er bundet til services, skal mindst én være valgt.
                  Har sælger ikke valgt nogen, medtages service-slides op til
                  _SERVICE_SLIDE_CAP for den valgte længde.
      - stakeholders: hvis sliden er bundet til stakeholders, skal den valgte matche
      - excluded_ids: slides sælger aktivt har fravalgt
    """
    services = services or []
    excluded = set(excluded_ids or [])
    cap = _SERVICE_SLIDE_CAP.get(pitch_length, 99)

    selected: List[LibrarySlide] = []
    service_slides_used = 0

    for slide in load_library():
        if slide.id in excluded:
            continue
        if pitch_length not in slide.length:
            continue
        if slide.stakeholders and stakeholder and stakeholder not in slide.stakeholders:
            continue

        if slide.services:
            if services:
                # Sælger har valgt services — vis kun dem, men alle af dem
                if not any(s in services for s in slide.services):
                    continue
            else:
                # Ingen valgt — vis de vigtigste op til cap
                if service_slides_used >= cap:
                    continue
                service_slides_used += 1

        selected.append(slide)

    return selected


def library_summary() -> Dict[str, Any]:
    """Til /api/health — hvad indeholder biblioteket?"""
    slides = load_library()
    by_category: Dict[str, int] = {}
    for s in slides:
        by_category[s.category] = by_category.get(s.category, 0) + 1
    return {
        "total": len(slides),
        "by_category": by_category,
        "counts_by_length": {
            length: len([s for s in slides if length in s.length])
            for length in LENGTH_ORDER
        },
    }


if __name__ == "__main__":
    lib = load_library()
    print(f"Slides i bibliotek: {len(lib)}\n")
    for s in lib:
        svc = f" · services={','.join(s.services)}" if s.services else ""
        stk = f" · stakeholders={','.join(s.stakeholders)}" if s.stakeholders else ""
        print(f"  [{s.order:3d}] {s.id:28s} {s.layout:20s} {s.length}{svc}{stk}")

    print("\nUdvalg pr. pitch-længde (alle services):")
    for length in LENGTH_ORDER:
        chosen = select_slides(pitch_length=length)
        print(f"  {length:7s}: {len(chosen)} slides")
