"""Master-decket: Benjamins salgspræsentation som slide-kilde.

Slides ligger urørt i master_deck/slides/ (importeret med import_master.py).
Dette modul ved, hvad hvert slide handler om — kapitel, services og ved
hvilke pitch-længder det er med som standard — og kan udvælge, samle og
gøre et deck selvbærende (assets som data-URI'er).

Sælgeren kan altid slå det enkelte slide til/fra i composeren; MANIFEST
styrer kun forvalget.
"""
from __future__ import annotations

import base64
from html import escape as html_escape
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DECK_DIR = Path(__file__).parent / "master_deck"

# ─── Manifest ─────────────────────────────────────────────────────────
# id = filens nummer-præfiks. lengths = pitch-længder hvor slidet er
# forvalgt. services = kun forvalgt hvis mindst én af disse services er
# valgt (tom = altid relevant). reserved = bruges af skabelonen selv
# (cover/næste skridt/afslutning) og vises ikke i vælgeren.

SHORT, MEDIUM, LONG = "short", "medium", "long"
ALL = [SHORT, MEDIUM, LONG]

FREELANCE = "Epico Freelance"
PROJEKT = "Epico Projektansættelser"
NEXTGEN = "Epico NextGen"
SEARCH = "Epico Search"
PUBLIC = "Epico Public"
SOLUTION = "Epico Solution"


@dataclass
class MasterSlide:
    num: int
    label: str
    chapter: str
    lengths: List[str] = field(default_factory=lambda: list(ALL))
    services: List[str] = field(default_factory=list)
    reserved: bool = False

    @property
    def id(self) -> str:
        return f"m{self.num:02d}"

    def to_plan_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.label,
            "category": self.chapter,
            "services": self.services,
        }


MANIFEST: List[MasterSlide] = [
    MasterSlide(1, "Titel", "reserved", reserved=True),
    # ── Historien om Epico ──
    MasterSlide(2, "Udfordringen", "story"),
    MasterSlide(3, "Fleksibel bemanding", "story", [MEDIUM, LONG]),
    MasterSlide(4, "Det rette match", "story"),
    MasterSlide(5, "Processen", "story", [MEDIUM, LONG]),
    MasterSlide(6, "Hvem er vi", "story", [MEDIUM, LONG]),
    MasterSlide(7, "Epico i tal", "story"),
    MasterSlide(8, "Citat", "story", [LONG]),
    MasterSlide(9, "Hvad vi gør", "story"),
    # ── Freelance ──
    MasterSlide(10, "Services forside", "freelance", [MEDIUM, LONG], [FREELANCE, PROJEKT]),
    MasterSlide(11, "Freelance", "freelance", ALL, [FREELANCE, PROJEKT]),
    MasterSlide(12, "Epic Process", "freelance", [MEDIUM, LONG], [FREELANCE, PROJEKT]),
    # ── Kompetencer (generelle) ──
    MasterSlide(13, "Kompetencer", "kompetencer", [MEDIUM, LONG]),
    MasterSlide(14, "Fagområder", "kompetencer", [LONG]),
    # ── Headhunting & rekruttering ──
    MasterSlide(15, "Headhunting forside", "search", [MEDIUM, LONG], [SEARCH]),
    MasterSlide(16, "Headhunting", "search", ALL, [SEARCH]),
    MasterSlide(17, "Rekrutteringsprocessen", "search", [MEDIUM, LONG], [SEARCH]),
    MasterSlide(18, "Fra A til Z", "search", [LONG], [SEARCH]),
    # ── NextGen ──
    MasterSlide(19, "NextGen forside", "nextgen", [MEDIUM, LONG], [NEXTGEN]),
    MasterSlide(20, "NextGen", "nextgen", ALL, [NEXTGEN]),
    MasterSlide(21, "NextGen proces", "nextgen", [MEDIUM, LONG], [NEXTGEN]),
    # ── Solution ──
    MasterSlide(22, "Solution forside", "solution", [MEDIUM, LONG], [SOLUTION]),
    MasterSlide(23, "Epico Solution", "solution", ALL, [SOLUTION]),
    MasterSlide(24, "App as a Service", "solution", [LONG], [SOLUTION]),
    MasterSlide(25, "Dataintegration", "solution", [LONG], [SOLUTION]),
    MasterSlide(26, "Cloud", "solution", [LONG], [SOLUTION]),
    MasterSlide(27, "SAP Basis", "solution", [LONG], [SOLUTION]),
    # ── Oracle / Mainframe (Solution-specialer) ──
    MasterSlide(28, "Oracle forside", "oracle", [MEDIUM, LONG], [SOLUTION]),
    MasterSlide(29, "Oracle", "oracle", ALL, [SOLUTION]),
    MasterSlide(30, "Mainframe forside", "mainframe", [MEDIUM, LONG], [SOLUTION]),
    MasterSlide(31, "Mainframe", "mainframe", ALL, [SOLUTION]),
    # ── Offentlig sektor ──
    MasterSlide(32, "Offentlig sektor forside", "public", [MEDIUM, LONG], [PUBLIC]),
    MasterSlide(33, "Offentlig sektor", "public", ALL, [PUBLIC]),
    # ── Afrunding ──
    MasterSlide(34, "Seks kriterier", "closing", [MEDIUM, LONG]),
    MasterSlide(35, "Partnerskab", "closing"),
    MasterSlide(36, "Næste skridt", "reserved", reserved=True),
    MasterSlide(37, "Afslutning", "reserved", reserved=True),
]

CHAPTER_LABELS = {
    "story": "Historien om Epico",
    "freelance": "Freelance & projektansættelser",
    "kompetencer": "Kompetencer",
    "search": "Headhunting & rekruttering",
    "nextgen": "NextGen",
    "solution": "Solution",
    "oracle": "Oracle",
    "mainframe": "Mainframe",
    "public": "Offentlig sektor",
    "closing": "Afrunding",
}

_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}

# ─── Indlæsning (caches ved første kald) ─────────────────────────────
_slide_html: Dict[int, str] = {}
_assets_b64: Dict[str, str] = {}
_head_css: Optional[str] = None
_runtime_js: Optional[str] = None


def _load() -> None:
    global _head_css, _runtime_js
    if _slide_html:
        return
    for f in sorted((DECK_DIR / "slides").glob("*.html")):
        num = int(f.name.split("-", 1)[0])
        _slide_html[num] = f.read_text(encoding="utf-8")
    for f in (DECK_DIR / "assets").iterdir():
        mime = _MIME.get(f.suffix)
        if mime:
            b64 = base64.b64encode(f.read_bytes()).decode()
            _assets_b64[f.stem] = f"data:{mime};base64,{b64}"
    _head_css = (DECK_DIR / "head.css").read_text(encoding="utf-8")
    _runtime_js = (DECK_DIR / "runtime.js").read_text(encoding="utf-8")


def deck_available() -> bool:
    return (DECK_DIR / "slides").is_dir() and any((DECK_DIR / "slides").glob("*.html"))


def head_css() -> str:
    _load()
    return _head_css or ""


def runtime_js() -> str:
    _load()
    return _runtime_js or ""


def slide_html(num: int) -> str:
    _load()
    return _slide_html[num]


def get_slide(num: int) -> MasterSlide:
    return next(s for s in MANIFEST if s.num == num)


def inline_assets(html: str) -> str:
    """Erstat uuid-referencer med data-URI'er så decket er én fil.

    Viewer-scriptet inlines som data-URI i stedet for et <script>-body,
    fordi det indeholder en literal '</script>' i sin dokumentation.
    """
    _load()
    for uuid, data_uri in _assets_b64.items():
        html = html.replace(uuid, data_uri)
    runtime_b64 = base64.b64encode((_runtime_js or "").encode()).decode()
    html = html.replace(
        "__DECK_RUNTIME__", f"data:text/javascript;base64,{runtime_b64}"
    )
    return html


# ─── Udvælgelse ──────────────────────────────────────────────────────


def thumbnails_html() -> str:
    """En selvstændig side med alle valgbare master-slides som miniaturer.

    Sælgeren skal kunne se hvad han slår til og fra. En titel som "Fra A til Z"
    eller "Seks kriterier" siger intet uden sliden ved siden af, og så bliver
    valget gætteri — eller han springer det over og tager standarddecket.

    Siden lever i en iframe, så masterens skrifter og fx-animationer ikke
    kolliderer med composerens egen stil. Billederne hentes fra /master-assets
    i stedet for at blive inlinet, så browseren kan cache dem på tværs af de
    34 miniaturer.
    """
    _load()

    cards = []
    for s in MANIFEST:
        if s.reserved:
            continue
        # data-deck-active får fx-animationerne til at vise deres slut-tilstand
        # i stedet for at stå usynlige og vente på at sliden bliver fremvist.
        cards.append(
            f'<button class="t" data-id="{s.id}" type="button" '
            f'title="{html_escape(s.label)}">'
            f'<div class="frame"><div class="stage" data-deck-active>{slide_html(s.num)}</div></div>'
            f'<span class="cap">{html_escape(s.label)}</span>'
            f'<span class="mark" aria-hidden="true"></span>'
            f'</button>'
        )

    return f"""<!DOCTYPE html>
<html lang="da"><head><meta charset="utf-8">
<style>
{_head_css or ""}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: transparent; font-family: 'DM Sans', sans-serif; }}
#grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }}
.t {{
  position: relative; display: block; width: 100%; padding: 0;
  border: 2px solid transparent; background: none; cursor: pointer;
  text-align: left; font: inherit;
}}
.frame {{
  position: relative; width: 100%; aspect-ratio: 16 / 9;
  overflow: hidden; background: #FFFCF2; border: 1px solid #d8d3c4;
}}
.stage {{
  position: absolute; top: 0; left: 0; width: 1920px; height: 1080px;
  transform-origin: top left; pointer-events: none;
}}
.stage > section {{ position: absolute; inset: 0; width: 1920px; height: 1080px; }}
.cap {{
  display: block; padding: 6px 2px 0; font-size: 12px; font-weight: 600;
  color: #1B1B50; line-height: 1.3;
}}
.mark {{
  position: absolute; top: 8px; right: 8px; width: 22px; height: 22px;
  background: #4CE17F; color: #1B1B50; font-size: 15px; font-weight: 700;
  display: none; align-items: center; justify-content: center;
}}
.mark::before {{ content: "✓"; }}
.t[data-on="1"] .mark {{ display: flex; }}
.t[data-on="0"] .frame {{ opacity: .38; filter: grayscale(.55); }}
.t[data-on="0"] .cap {{ color: #8a8578; }}
.t[data-on="0"]:hover .frame {{ opacity: .72; filter: none; }}
.t:hover {{ border-color: #E01E37; }}
.t:focus-visible {{ outline: 2px solid #E01E37; outline-offset: 2px; }}
</style></head>
<body><div id="grid">{''.join(cards)}</div>
<script>
// Miniaturerne skaleres til den bredde de får — så virker det uanset
// hvor bredt composeren giver os lov til at være.
function fit() {{
  document.querySelectorAll('.frame').forEach(f => {{
    const st = f.querySelector('.stage');
    if (st) st.style.transform = 'scale(' + (f.clientWidth / 1920) + ')';
  }});
}}
addEventListener('resize', fit);
fit();

// Klik melder tilbage til composeren, som ejer state. Vi tegner ikke selv
// ændringen — vi venter på at få den valgte liste tilbage, så de to aldrig
// kan komme ud af trit.
document.getElementById('grid').addEventListener('click', e => {{
  const t = e.target.closest('.t');
  if (t) parent.postMessage({{ type: 'slide-toggle', id: t.dataset.id }}, '*');
}});

addEventListener('message', e => {{
  const d = e.data || {{}};
  if (d.type !== 'slide-selection') return;
  const on = new Set(d.ids || []);
  document.querySelectorAll('.t').forEach(t => {{
    t.dataset.on = on.has(t.dataset.id) ? '1' : '0';
  }});
  parent.postMessage({{ type: 'slide-preview-height', height: document.body.scrollHeight }}, '*');
}});

// Fortæl composeren hvor høj siden er, så iframen kan følge indholdet
new ResizeObserver(() => parent.postMessage(
  {{ type: 'slide-preview-height', height: document.body.scrollHeight }}, '*'
)).observe(document.body);
</script></body></html>"""



def slides_following(ids: Optional[List[str]]) -> List[Dict[str, str]]:
    """Hvilke master-slides kommer efter kundeslidesne — til AI-prompten.

    AI'en skriver kundeslidesne uden at kunne se resten af decket. Uden den her
    liste genforklarer den services som masteren allerede forklarer bedre og
    pænere tre slides senere.
    """
    if not ids:
        return []
    chosen = set(ids)
    out = []
    for s in MANIFEST:
        if s.reserved or s.id not in chosen:
            continue
        out.append({
            "label": s.label,
            "chapter": CHAPTER_LABELS.get(s.chapter, s.chapter),
            "services": ", ".join(s.services) if s.services else "",
        })
    return out


def default_slide_ids(
    pitch_length: str = "medium",
    services: Optional[List[str]] = None,
) -> List[str]:
    """Hvilke slides er forvalgt ved denne længde + service-kombination."""
    chosen = set(services or [])
    out = []
    for s in MANIFEST:
        if s.reserved:
            continue
        if pitch_length not in s.lengths:
            continue
        if s.services and not (chosen & set(s.services)):
            continue
        out.append(s.id)
    return out


def plan(
    pitch_length: str = "medium",
    services: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Alle valgbare slides + hvilke der er forvalgt — til composerens vælger.

    Hvert fravalgt slide får en grund med. Uden den kan vælgeren ikke skelne
    mellem "passer ikke i et kort møde" og "hører til en service du ikke
    pitcher" — to helt forskellige beskeder til sælgeren, som ellers ville
    se ens ud.
    """
    defaults = set(default_slide_ids(pitch_length, services))
    chosen = set(services or [])
    out = []
    for s in MANIFEST:
        if s.reserved:
            continue
        d = s.to_plan_dict()
        d["default_on"] = s.id in defaults

        if d["default_on"]:
            d["off_reason"] = None
        elif s.services and not (chosen & set(s.services)):
            # Sælgeren kan låse den op ved at vælge en af disse services
            d["off_reason"] = "service"
            d["unlock_services"] = list(s.services)
        else:
            d["off_reason"] = "length"
        out.append(d)
    return out


def select_slides(
    pitch_length: str = "medium",
    services: Optional[List[str]] = None,
    excluded_slide_ids: Optional[List[str]] = None,
    selected_slide_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Endelig slide-liste til rendering, i masterens rækkefølge.

    selected_slide_ids er sælgerens fulde valg fra vælgeren og vinder
    over forvalget; ellers bruges forvalget (længde+services) minus
    eksplicitte fravalg.
    """
    if selected_slide_ids is not None:
        chosen = set(selected_slide_ids)
    else:
        chosen = set(default_slide_ids(pitch_length, services))
        chosen -= set(excluded_slide_ids or [])
    _load()
    out = []
    for s in MANIFEST:
        if s.reserved or s.id not in chosen:
            continue
        out.append({"id": s.id, "title": s.label, "html": _slide_html[s.num]})
    return out
