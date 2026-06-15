"""
PowerPoint (.pptx) renderer.
Bygger samme pitch deck som HTML, men som editerbar .pptx-fil.

Bruger:
- 16:9 slide-størrelse (1920x1080 px → 13.333" x 7.5")
- Epico brand-farver direkte
- DM Sans som primær font (fallback til Arial hvis ikke installeret)
- Tekst er editerbar i PowerPoint
"""
from io import BytesIO
from typing import Dict, Any, List, Optional
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from lxml import etree


# ---------- Brand-farver (matcher styles.css) ----------
RED = RGBColor(0x69, 0x0F, 0x23)
RASPBERRY = RGBColor(0xE0, 0x1E, 0x37)
BLACK_CURRANT = RGBColor(0x1B, 0x1B, 0x50)
KIWI = RGBColor(0x4C, 0xE1, 0x7F)
BLUEBERRY = RGBColor(0x4B, 0x64, 0xEA)
GREY = RGBColor(0x24, 0x21, 0x26)
LIGHT_GREY = RGBColor(0x91, 0x91, 0x99)
BEIGE = RGBColor(0xE4, 0xE1, 0xDC)
ALU_GREY = RGBColor(0xE5, 0xE5, 0xE5)
RAW_SILK = RGBColor(0xFF, 0xFC, 0xF2)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

# ---------- Layout-konstanter ----------
SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
MARGIN = Inches(0.6)

FONT_DISPLAY = "DM Sans"  # Fallback til Arial Bold når ikke installeret
FONT_BODY = "DM Sans"


# ============================================================
# HELPERS
# ============================================================

def _set_slide_bg(slide, color: RGBColor) -> None:
    """Sæt baggrundsfarve på en slide."""
    bg = slide.background.fill
    bg.solid()
    bg.fore_color.rgb = color


def _add_rect(slide, x, y, w, h, fill: RGBColor, line: Optional[RGBColor] = None):
    """Tilføj et rektangel med fyldfarve."""
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()  # Ingen border
    else:
        shape.line.color.rgb = line
    return shape


def _add_text(
    slide,
    x, y, w, h,
    text: str,
    font_size: int = 18,
    bold: bool = False,
    color: RGBColor = GREY,
    font_name: str = FONT_BODY,
    align: int = PP_ALIGN.LEFT,
    anchor: int = MSO_ANCHOR.TOP,
    letter_spacing: Optional[float] = None,
):
    """Tilføj et tekstboks."""
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = Emu(0)
    tf.margin_right = Emu(0)
    tf.margin_top = Emu(0)
    tf.margin_bottom = Emu(0)

    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text or ""
    run.font.name = font_name
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.color.rgb = color

    if letter_spacing is not None:
        rPr = run._r.get_or_add_rPr()
        rPr.set("spc", str(int(letter_spacing * 100)))  # Letter-spacing i 1/100 pt

    return tb


def _add_e_mark(slide, x, y, size: int = Inches(0.5), bg: RGBColor = RED, fg: RGBColor = WHITE):
    """Tilføj Epico E-bomærket som en gruppe af rektangler."""
    # Baggrunds-firkant
    bg_shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, size, size)
    bg_shape.fill.solid()
    bg_shape.fill.fore_color.rgb = bg
    bg_shape.line.fill.background()

    # 3 horisontale streger der danner E
    bar_height = size // 7
    side_padding = size // 6
    bar_width_full = size - (side_padding * 2)
    bar_width_mid = int(bar_width_full * 0.65)
    bar_x = x + side_padding

    # Top bar
    top = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, bar_x, y + side_padding, bar_width_full, bar_height)
    top.fill.solid(); top.fill.fore_color.rgb = fg; top.line.fill.background()

    # Mid bar (kortere)
    mid_y = y + (size // 2) - (bar_height // 2)
    mid = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, bar_x, mid_y, bar_width_mid, bar_height)
    mid.fill.solid(); mid.fill.fore_color.rgb = fg; mid.line.fill.background()

    # Bottom bar
    bot_y = y + size - side_padding - bar_height
    bot = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, bar_x, bot_y, bar_width_full, bar_height)
    bot.fill.solid(); bot.fill.fore_color.rgb = fg; bot.line.fill.background()


def _add_slide_header(slide, section_tag: str, dark: bool = False):
    """Tilføj brand-header i top-right (E-mærke + 'Epico' + section-tag)."""
    text_color = WHITE if dark else BLACK_CURRANT
    label_color = RGBColor(0xFF, 0xFF, 0xFF) if dark else LIGHT_GREY
    e_size = Inches(0.4)

    # E-mærke
    e_x = SLIDE_W - Inches(3.5)
    e_y = Inches(0.35)
    _add_e_mark(slide, e_x, e_y, e_size)

    # "Epico" wordmark
    _add_text(
        slide,
        e_x + e_size + Inches(0.15), e_y - Inches(0.02),
        Inches(0.8), e_size + Inches(0.1),
        "Epico",
        font_size=14, bold=True, color=text_color, anchor=MSO_ANCHOR.MIDDLE,
        font_name=FONT_DISPLAY,
    )

    # Section-tag
    _add_text(
        slide,
        e_x + e_size + Inches(1.0), e_y,
        Inches(2.0), e_size,
        section_tag.upper(),
        font_size=9, bold=True, color=label_color, anchor=MSO_ANCHOR.MIDDLE,
        font_name=FONT_BODY,
    )


def _add_footer(slide, text: str, dark: bool = False):
    """Tilføj slide-footer i bottom-left."""
    color = RGBColor(0xFF, 0xFF, 0xFF) if dark else LIGHT_GREY
    _add_text(
        slide,
        MARGIN, SLIDE_H - Inches(0.5),
        Inches(6), Inches(0.3),
        text.upper(),
        font_size=9, bold=True, color=color,
        font_name=FONT_BODY,
    )


# ============================================================
# SLIDE BUILDERS
# ============================================================

def _slide_cover(prs, ctx):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _set_slide_bg(slide, BLACK_CURRANT)

    # E-mærke + wordmark i top-left
    _add_e_mark(slide, MARGIN, Inches(0.6), Inches(0.55))
    _add_text(slide, MARGIN + Inches(0.7), Inches(0.6),
              Inches(2), Inches(0.55), "Epico",
              font_size=22, bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE,
              font_name=FONT_DISPLAY)

    # Meta top-right
    _add_text(slide, SLIDE_W - Inches(4.5), Inches(0.65),
              Inches(4), Inches(0.4),
              f"SKRÆDDERSYET PITCH · {ctx['meeting']['date'].upper()}",
              font_size=9, bold=True,
              color=RGBColor(0x99, 0x99, 0xAA), align=PP_ALIGN.RIGHT,
              font_name=FONT_BODY)

    # Eyebrow
    _add_text(slide, MARGIN, Inches(2.8),
              Inches(6), Inches(0.4),
              "STRATEGISK SAMARBEJDSOPLÆG",
              font_size=11, bold=True, color=KIWI,
              font_name=FONT_BODY)

    # Stort title — kunde-navn
    _add_text(slide, MARGIN, Inches(3.3),
              SLIDE_W - (MARGIN * 2), Inches(1.0),
              ctx["client"]["name"],
              font_size=72, bold=True, color=WHITE,
              font_name=FONT_DISPLAY)

    # X-mark
    _add_text(slide, MARGIN, Inches(4.4),
              Inches(2), Inches(0.6),
              "×",
              font_size=44, bold=True, color=KIWI,
              font_name=FONT_DISPLAY)

    # Epico
    _add_text(slide, MARGIN, Inches(5.0),
              SLIDE_W - (MARGIN * 2), Inches(1.0),
              "Epico",
              font_size=72, bold=True, color=KIWI,
              font_name=FONT_DISPLAY)

    # Footer
    _add_text(slide, MARGIN, SLIDE_H - Inches(0.7),
              Inches(6), Inches(0.3),
              f"UDARBEJDET TIL {ctx['meeting']['contact_person'].upper()}",
              font_size=9, bold=True,
              color=RGBColor(0xAA, 0xAA, 0xBB),
              font_name=FONT_BODY)
    _add_text(slide, SLIDE_W - Inches(6.5), SLIDE_H - Inches(0.7),
              Inches(6), Inches(0.3),
              f"{ctx['meeting']['city'].upper()} · {ctx['meeting']['date'].upper()}",
              font_size=9, bold=True,
              color=RGBColor(0xAA, 0xAA, 0xBB), align=PP_ALIGN.RIGHT,
              font_name=FONT_BODY)


def _slide_agenda(prs, ctx):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, RAW_SILK)
    _add_slide_header(slide, "Agenda")

    _add_text(slide, MARGIN, Inches(1.4), Inches(6), Inches(0.4),
              "SÅDAN BRUGER VI DE NÆSTE 45 MINUTTER",
              font_size=11, bold=True, color=RASPBERRY,
              font_name=FONT_BODY)

    _add_text(slide, MARGIN, Inches(1.85), Inches(8), Inches(1.0),
              "Agenda",
              font_size=60, bold=True, color=BLACK_CURRANT,
              font_name=FONT_DISPLAY)

    items = [
        ("01", f"Vores research om {ctx['client']['name']}", "8 min"),
        ("02", "Jeres strategiske prioriteter — sådan som vi læser dem", "10 min"),
        ("03", "Hvor Epico kan flytte nålen for jer", "10 min"),
        ("04", "Hvem vi er, og hvad vi leverer", "10 min"),
        ("05", "Næste skridt — hvis vi er enige", "7 min"),
    ]
    y = Inches(3.2)
    for num, label, dur in items:
        _add_text(slide, MARGIN, y, Inches(0.7), Inches(0.5),
                  num, font_size=22, bold=True, color=RASPBERRY,
                  font_name=FONT_DISPLAY)
        _add_text(slide, MARGIN + Inches(0.9), y, Inches(8.5), Inches(0.5),
                  label, font_size=22, color=BLACK_CURRANT,
                  font_name=FONT_DISPLAY)
        _add_text(slide, SLIDE_W - Inches(1.5), y, Inches(1.0), Inches(0.5),
                  dur.upper(), font_size=10, bold=True, color=LIGHT_GREY,
                  align=PP_ALIGN.RIGHT, font_name=FONT_BODY)
        # Divider line
        _add_rect(slide, MARGIN, y + Inches(0.65), SLIDE_W - (MARGIN * 2), Emu(8000), ALU_GREY)
        y += Inches(0.78)


def _slide_research(prs, ctx):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, RAW_SILK)
    _add_slide_header(slide, "Research")

    _add_text(slide, MARGIN, Inches(1.4), Inches(6), Inches(0.4),
              "VI HAR GJORT HJEMMEARBEJDET",
              font_size=11, bold=True, color=RASPBERRY, font_name=FONT_BODY)
    _add_text(slide, MARGIN, Inches(1.85), Inches(11), Inches(1.0),
              f"Dette ved vi om {ctx['client']['name']}",
              font_size=56, bold=True, color=BLACK_CURRANT, font_name=FONT_DISPLAY)

    # 2x2 grid med facts
    facts = ctx.get("research_facts", [])[:4]
    cell_w = (SLIDE_W - (MARGIN * 2) - Inches(0.05)) / 2
    cell_h = Inches(1.6)
    start_y = Inches(3.4)
    for i, fact in enumerate(facts):
        col = i % 2
        row = i // 2
        x = MARGIN + col * (cell_w + Inches(0.05))
        y = start_y + row * (cell_h + Inches(0.05))
        _add_rect(slide, x, y, cell_w, cell_h, WHITE)
        # Venstre rød border
        _add_rect(slide, x, y, Inches(0.05), cell_h, RED)
        # Key
        _add_text(slide, x + Inches(0.4), y + Inches(0.25),
                  cell_w - Inches(0.8), Inches(0.3),
                  fact.get("key", "").upper(),
                  font_size=10, bold=True, color=LIGHT_GREY,
                  font_name=FONT_BODY)
        # Value
        value_text = fact.get("value", "")
        value_size = 28 if len(value_text) <= 18 else 18
        _add_text(slide, x + Inches(0.4), y + Inches(0.6),
                  cell_w - Inches(0.8), Inches(0.55),
                  value_text,
                  font_size=value_size, bold=True, color=BLACK_CURRANT,
                  font_name=FONT_DISPLAY)
        # Source
        _add_text(slide, x + Inches(0.4), y + cell_h - Inches(0.4),
                  cell_w - Inches(0.8), Inches(0.3),
                  f"Kilde: {fact.get('source', '')}",
                  font_size=10, color=LIGHT_GREY, font_name=FONT_BODY)


def _slide_priorities(prs, ctx):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, RAW_SILK)
    _add_slide_header(slide, "Jeres prioriteter")

    _add_text(slide, MARGIN, Inches(1.4), Inches(6), Inches(0.4),
              "SÅDAN LÆSER VI JERES RETNING",
              font_size=11, bold=True, color=RASPBERRY, font_name=FONT_BODY)
    _add_text(slide, MARGIN, Inches(1.85), Inches(11), Inches(1.0),
              "3 strategiske prioriteter vi vil tale ind i.",
              font_size=44, bold=True, color=BLACK_CURRANT, font_name=FONT_DISPLAY)

    priorities = ctx.get("strategic_priorities", [])[:3]
    y = Inches(3.4)
    for i, p in enumerate(priorities, start=1):
        _add_rect(slide, MARGIN, y, SLIDE_W - (MARGIN * 2), Inches(1.1), WHITE)
        # Num
        _add_text(slide, MARGIN + Inches(0.3), y + Inches(0.15),
                  Inches(0.8), Inches(0.7),
                  f"{i:02d}",
                  font_size=42, bold=True, color=RASPBERRY,
                  font_name=FONT_DISPLAY)
        # Title
        _add_text(slide, MARGIN + Inches(1.2), y + Inches(0.15),
                  SLIDE_W - MARGIN - Inches(1.5), Inches(0.4),
                  p.get("title", ""),
                  font_size=18, bold=True, color=BLACK_CURRANT,
                  font_name=FONT_BODY)
        # Description
        _add_text(slide, MARGIN + Inches(1.2), y + Inches(0.55),
                  SLIDE_W - MARGIN - Inches(1.5), Inches(0.5),
                  p.get("description", "")[:280],
                  font_size=12, color=GREY, font_name=FONT_BODY)
        y += Inches(1.18)


def _slide_mapping(prs, ctx):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, RAW_SILK)
    _add_slide_header(slide, "Hvor vi flytter nålen")

    _add_text(slide, MARGIN, Inches(1.4), Inches(6), Inches(0.4),
              "KONKRET KOBLING",
              font_size=11, bold=True, color=RASPBERRY, font_name=FONT_BODY)
    _add_text(slide, MARGIN, Inches(1.85), Inches(12), Inches(1.0),
              "Jeres udfordring. Vores håndtag.",
              font_size=44, bold=True, color=BLACK_CURRANT, font_name=FONT_DISPLAY)

    mappings = ctx.get("value_mappings", [])[:4]
    col1_w = Inches(5.5)
    arrow_w = Inches(0.6)
    col2_w = SLIDE_W - (MARGIN * 2) - col1_w - arrow_w

    # Header row
    header_y = Inches(3.3)
    _add_rect(slide, MARGIN, header_y, col1_w, Inches(0.45), BEIGE)
    _add_text(slide, MARGIN + Inches(0.2), header_y + Inches(0.1),
              col1_w - Inches(0.3), Inches(0.3),
              "JERES UDFORDRING",
              font_size=10, bold=True, color=GREY, font_name=FONT_BODY)
    _add_rect(slide, MARGIN + col1_w + arrow_w, header_y, col2_w, Inches(0.45), BLACK_CURRANT)
    _add_text(slide, MARGIN + col1_w + arrow_w + Inches(0.2), header_y + Inches(0.1),
              col2_w - Inches(0.3), Inches(0.3),
              "DET EPICO KAN LØSE",
              font_size=10, bold=True, color=WHITE, font_name=FONT_BODY)

    y = header_y + Inches(0.5)
    row_h = Inches(0.75)
    for m in mappings:
        _add_rect(slide, MARGIN, y, col1_w, row_h, WHITE, line=ALU_GREY)
        _add_text(slide, MARGIN + Inches(0.2), y + Inches(0.1),
                  col1_w - Inches(0.4), row_h - Inches(0.2),
                  m.get("challenge", "")[:200],
                  font_size=11, color=GREY, font_name=FONT_BODY,
                  anchor=MSO_ANCHOR.MIDDLE)
        # Arrow
        _add_text(slide, MARGIN + col1_w, y,
                  arrow_w, row_h,
                  "→", font_size=20, bold=True, color=RASPBERRY,
                  align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE,
                  font_name=FONT_DISPLAY)
        _add_rect(slide, MARGIN + col1_w + arrow_w, y, col2_w, row_h,
                  RGBColor(0xFA, 0xF9, 0xF5), line=ALU_GREY)
        sol_text = f"{m.get('epico_service', '')}: {m.get('solution', '')[:180]}"
        _add_text(slide, MARGIN + col1_w + arrow_w + Inches(0.2),
                  y + Inches(0.1),
                  col2_w - Inches(0.4), row_h - Inches(0.2),
                  sol_text,
                  font_size=11, color=BLACK_CURRANT, font_name=FONT_BODY,
                  anchor=MSO_ANCHOR.MIDDLE)
        y += row_h + Emu(20000)


def _slide_divider(prs, chapter_num: str, title: str, accent_word: str = "", red: bool = False):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, RED if red else BLACK_CURRANT)
    _add_slide_header(slide, f"Kapitel {chapter_num}", dark=True)

    # Stort baggrunds-nummer
    _add_text(slide, MARGIN, Inches(1.0), Inches(6), Inches(4.5),
              chapter_num,
              font_size=240, bold=True,
              color=RGBColor(0x33, 0x33, 0x77) if not red else RGBColor(0x80, 0x20, 0x35),
              font_name=FONT_DISPLAY)

    _add_text(slide, MARGIN, Inches(5.8), Inches(6), Inches(0.4),
              f"KAPITEL {chapter_num}".upper(),
              font_size=11, bold=True, color=KIWI, font_name=FONT_BODY)

    _add_text(slide, MARGIN, Inches(6.2), SLIDE_W - (MARGIN * 2), Inches(1.0),
              title,
              font_size=80, bold=True, color=WHITE, font_name=FONT_DISPLAY)


def _slide_epico_stats(prs, ctx):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, BLACK_CURRANT)
    _add_slide_header(slide, "Epico i tal", dark=True)

    _add_text(slide, MARGIN, Inches(1.4), Inches(6), Inches(0.4),
              "2026",
              font_size=11, bold=True, color=KIWI, font_name=FONT_BODY)
    _add_text(slide, MARGIN, Inches(1.85), Inches(12), Inches(1.0),
              "Et af Nordens største IT-konsulenthuse.",
              font_size=44, bold=True, color=WHITE, font_name=FONT_DISPLAY)

    stats = [
        ("+700 mio.", "DKK i omsætning · 2024"),
        ("+500", "Konsulenter på kontrakt"),
        ("+13.000", "CV'er i database"),
        ("+1.500", "Kunder globalt"),
        ("12", "Lande med konsulenter"),
    ]
    col_w = (SLIDE_W - (MARGIN * 2) - Emu(100000)) / 5
    y = Inches(3.5)
    accents = [KIWI, RASPBERRY, BLUEBERRY, KIWI, RASPBERRY]
    for i, (value, label) in enumerate(stats):
        x = MARGIN + i * (col_w + Emu(20000))
        # Border-left
        _add_rect(slide, x, y, Emu(20000), Inches(2.5), accents[i])
        _add_text(slide, x + Inches(0.2), y + Inches(0.3),
                  col_w - Inches(0.3), Inches(0.8),
                  value, font_size=40, bold=True, color=WHITE,
                  font_name=FONT_DISPLAY)
        _add_text(slide, x + Inches(0.2), y + Inches(1.4),
                  col_w - Inches(0.3), Inches(1.0),
                  label,
                  font_size=10, color=RGBColor(0xAA, 0xAA, 0xBB),
                  font_name=FONT_BODY)


def _slide_market(prs, ctx):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, RAW_SILK)
    _add_slide_header(slide, "Markedet")

    _add_text(slide, MARGIN, Inches(1.4), Inches(6), Inches(0.4),
              "HVORFOR I IKKE STÅR ALENE MED PROBLEMET",
              font_size=11, bold=True, color=RASPBERRY, font_name=FONT_BODY)
    _add_text(slide, MARGIN, Inches(1.85), Inches(11), Inches(1.0),
              "DK's IT-marked i tal.",
              font_size=44, bold=True, color=BLACK_CURRANT, font_name=FONT_DISPLAY)

    facts = [
        ("200.000", "IT-specialister vil DK mangle i 2030."),
        ("4 af 5", "virksomheder har problemer med at rekruttere IT-specialister."),
        ("92%", "af virksomhederne mangler kvalificerede ansøgere."),
        ("71,4%", "af danske IT-leverandører ser kompetencemangel som den største vækstbarriere."),
    ]
    y = Inches(3.4)
    for figure, text in facts:
        _add_text(slide, MARGIN, y, Inches(3), Inches(0.7),
                  figure, font_size=42, bold=True, color=RASPBERRY,
                  font_name=FONT_DISPLAY)
        _add_text(slide, MARGIN + Inches(3.2), y + Inches(0.15),
                  Inches(9), Inches(0.5),
                  text, font_size=16, color=GREY, font_name=FONT_BODY)
        _add_rect(slide, MARGIN, y + Inches(0.8),
                  SLIDE_W - (MARGIN * 2), Emu(8000), ALU_GREY)
        y += Inches(0.92)


def _slide_dna(prs, ctx):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, RAW_SILK)
    _add_slide_header(slide, "Vores DNA")

    _add_text(slide, MARGIN, Inches(1.4), Inches(6), Inches(0.4),
              "DET VI MÅLES PÅ — HVER DAG",
              font_size=11, bold=True, color=RASPBERRY, font_name=FONT_BODY)
    _add_text(slide, MARGIN, Inches(1.85), Inches(11), Inches(1.0),
              "Fire ting, vi ikke går på kompromis med.",
              font_size=40, bold=True, color=BLACK_CURRANT, font_name=FONT_DISPLAY)

    dna = [
        ("01", "Hastighed", "Vi leverer typisk relevante CV'er inden for 48 timer.", WHITE, RASPBERRY, GREY),
        ("02", "Det rette match", "Vi matcher også på kultur, kommunikation og tempo.", BLACK_CURRANT, KIWI, WHITE),
        ("03", "Personlig relation", "I får én dedikeret Key Account Manager.", RAW_SILK, RASPBERRY, GREY),
        ("04", "Ekspertise", "+15 års dyb branche-erfaring inden for IT-konsulenthus.", RED, KIWI, WHITE),
    ]
    col_w = (SLIDE_W - (MARGIN * 2) - Inches(0.15)) / 4
    cell_h = Inches(3.3)
    y = Inches(3.4)
    for i, (num, title, body, bg, num_color, text_color) in enumerate(dna):
        x = MARGIN + i * (col_w + Inches(0.05))
        _add_rect(slide, x, y, col_w, cell_h, bg)
        _add_text(slide, x + Inches(0.3), y + Inches(0.3),
                  col_w - Inches(0.5), Inches(1.0),
                  num, font_size=42, bold=True, color=num_color,
                  font_name=FONT_DISPLAY)
        _add_text(slide, x + Inches(0.3), y + cell_h - Inches(1.5),
                  col_w - Inches(0.5), Inches(0.5),
                  title, font_size=18, bold=True, color=text_color,
                  font_name=FONT_BODY)
        _add_text(slide, x + Inches(0.3), y + cell_h - Inches(0.95),
                  col_w - Inches(0.5), Inches(0.85),
                  body, font_size=11,
                  color=RGBColor(0xAA, 0xAA, 0xBB) if bg in (BLACK_CURRANT, RED) else LIGHT_GREY,
                  font_name=FONT_BODY)


def _slide_service(prs, service: dict, idx: int, total: int):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, RAW_SILK)
    section_name = service.get("service_name", "Service").replace("Epico ", "")
    _add_slide_header(slide, section_name)

    _add_text(slide, MARGIN, Inches(1.0), Inches(6), Inches(0.4),
              f"SERVICE {idx:02d} / {total:02d}",
              font_size=11, bold=True, color=RASPBERRY, font_name=FONT_BODY)
    _add_text(slide, MARGIN, Inches(1.45), Inches(12), Inches(1.0),
              service.get("service_name", ""),
              font_size=64, bold=True, color=BLACK_CURRANT, font_name=FONT_DISPLAY)
    _add_text(slide, MARGIN, Inches(2.55), Inches(12), Inches(0.6),
              service.get("tagline", ""),
              font_size=20, bold=True, color=RASPBERRY, font_name=FONT_DISPLAY)

    # 3 kolonner
    col_w = (SLIDE_W - (MARGIN * 2) - Inches(0.1)) / 3
    body_y = Inches(3.5)
    body_h = Inches(3.0)

    # Col 1: Hvad I får
    _add_rect(slide, MARGIN, body_y, col_w, body_h, WHITE)
    _add_text(slide, MARGIN + Inches(0.3), body_y + Inches(0.25),
              col_w - Inches(0.5), Inches(0.3),
              "HVAD I FÅR", font_size=10, bold=True, color=RASPBERRY,
              font_name=FONT_BODY)
    bullet_y = body_y + Inches(0.7)
    for b in service.get("what_we_deliver", [])[:4]:
        _add_text(slide, MARGIN + Inches(0.3), bullet_y,
                  col_w - Inches(0.5), Inches(0.5),
                  f"• {b[:110]}", font_size=10, color=GREY,
                  font_name=FONT_BODY)
        bullet_y += Inches(0.55)

    # Col 2: Stats (dark)
    col2_x = MARGIN + col_w + Inches(0.05)
    _add_rect(slide, col2_x, body_y, col_w, body_h, BLACK_CURRANT)
    _add_text(slide, col2_x + Inches(0.3), body_y + Inches(0.25),
              col_w - Inches(0.5), Inches(0.3),
              "NØGLETAL", font_size=10, bold=True, color=KIWI,
              font_name=FONT_BODY)
    stat_y = body_y + Inches(0.8)
    for s in service.get("key_stats", [])[:3]:
        _add_text(slide, col2_x + Inches(0.3), stat_y,
                  col_w - Inches(0.5), Inches(0.5),
                  s.get("value", ""), font_size=28, bold=True, color=KIWI,
                  font_name=FONT_DISPLAY)
        _add_text(slide, col2_x + Inches(0.3), stat_y + Inches(0.45),
                  col_w - Inches(0.5), Inches(0.3),
                  s.get("label", ""), font_size=9,
                  color=RGBColor(0xAA, 0xAA, 0xBB),
                  font_name=FONT_BODY)
        stat_y += Inches(0.85)

    # Col 3: Hvornår
    col3_x = MARGIN + (col_w * 2) + Inches(0.1)
    _add_rect(slide, col3_x, body_y, col_w, body_h, WHITE)
    _add_text(slide, col3_x + Inches(0.3), body_y + Inches(0.25),
              col_w - Inches(0.5), Inches(0.3),
              "HVORNÅR DET ER DET RIGTIGE VALG",
              font_size=10, bold=True, color=RASPBERRY,
              font_name=FONT_BODY)
    who_y = body_y + Inches(0.7)
    for w in service.get("who_its_for", [])[:3]:
        _add_text(slide, col3_x + Inches(0.3), who_y,
                  col_w - Inches(0.5), Inches(0.7),
                  f"• {w[:130]}", font_size=10, color=GREY,
                  font_name=FONT_BODY)
        who_y += Inches(0.75)

    # Footer metadata
    foot_y = body_y + body_h + Inches(0.15)
    _add_rect(slide, MARGIN, foot_y, SLIDE_W - (MARGIN * 2), Inches(0.7),
              RAW_SILK)
    _add_rect(slide, MARGIN, foot_y, Emu(30000), Inches(0.7), RED)
    _add_text(slide, MARGIN + Inches(0.3), foot_y + Inches(0.1),
              Inches(2), Inches(0.25),
              "TYPISKE ROLLER", font_size=9, bold=True, color=RASPBERRY,
              font_name=FONT_BODY)
    _add_text(slide, MARGIN + Inches(0.3), foot_y + Inches(0.38),
              SLIDE_W - (MARGIN * 2) - Inches(0.5), Inches(0.3),
              service.get("typical_roles", "")[:200],
              font_size=10, color=BLACK_CURRANT,
              font_name=FONT_BODY)


def _slide_case(prs, ctx):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, RAW_SILK)
    _add_slide_header(slide, "Relevant case")

    case = ctx.get("case", {})
    _add_text(slide, MARGIN, Inches(1.0), Inches(8), Inches(0.4),
              f"CASE FRA {ctx.get('industry_tag', 'BRANCHEN').upper()}",
              font_size=11, bold=True, color=RASPBERRY,
              font_name=FONT_BODY)
    _add_text(slide, MARGIN, Inches(1.45), Inches(12), Inches(1.2),
              case.get("headline", "")[:180],
              font_size=36, bold=True, color=BLACK_CURRANT,
              font_name=FONT_DISPLAY)
    _add_text(slide, MARGIN, Inches(2.7), Inches(12), Inches(0.8),
              case.get("intro", "")[:300],
              font_size=14, color=GREY, font_name=FONT_BODY)

    # 4 kolonner
    cols = [
        ("HVAD", case.get("what", []), WHITE, GREY, RASPBERRY),
        ("HVORFOR", case.get("why", []), WHITE, GREY, RASPBERRY),
        ("RESULTAT", case.get("result", []), RED, WHITE, KIWI),
        ("VÆRDI", case.get("value", []), WHITE, GREY, RASPBERRY),
    ]
    col_w = (SLIDE_W - (MARGIN * 2) - Inches(0.15)) / 4
    cell_h = Inches(2.7)
    y = Inches(3.8)
    for i, (label, bullets, bg, txt, accent) in enumerate(cols):
        x = MARGIN + i * (col_w + Inches(0.05))
        _add_rect(slide, x, y, col_w, cell_h, bg)
        _add_text(slide, x + Inches(0.25), y + Inches(0.2),
                  col_w - Inches(0.5), Inches(0.3),
                  label, font_size=10, bold=True, color=accent,
                  font_name=FONT_BODY)
        bl_y = y + Inches(0.65)
        for b in bullets[:3]:
            _add_text(slide, x + Inches(0.25), bl_y,
                      col_w - Inches(0.5), Inches(0.55),
                      f"• {str(b)[:110]}", font_size=10, color=txt,
                      font_name=FONT_BODY)
            bl_y += Inches(0.6)


def _slide_next_steps(prs, ctx):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, RAW_SILK)
    _add_slide_header(slide, "Næste skridt")

    _add_text(slide, MARGIN, Inches(1.4), Inches(8), Inches(0.4),
              "HVIS VI ER ENIGE OM RETNINGEN",
              font_size=11, bold=True, color=RASPBERRY,
              font_name=FONT_BODY)
    _add_text(slide, MARGIN, Inches(1.85), Inches(11), Inches(1.0),
              "Tre konkrete næste skridt.",
              font_size=44, bold=True, color=BLACK_CURRANT,
              font_name=FONT_DISPLAY)

    steps = ctx.get("next_steps", [])[:3]
    col_w = (SLIDE_W - (MARGIN * 2) - Inches(0.1)) / 3
    cell_h = Inches(3.0)
    y = Inches(3.4)
    for i, step in enumerate(steps, start=1):
        x = MARGIN + (i - 1) * (col_w + Inches(0.05))
        _add_rect(slide, x, y, col_w, cell_h, WHITE)
        _add_text(slide, x + Inches(0.3), y + Inches(0.3),
                  col_w - Inches(0.5), Inches(0.3),
                  f"SKRIDT {i:02d}", font_size=10, bold=True, color=RASPBERRY,
                  font_name=FONT_BODY)
        _add_text(slide, x + Inches(0.3), y + Inches(0.75),
                  col_w - Inches(0.5), Inches(0.8),
                  step.get("title", ""), font_size=20, bold=True,
                  color=BLACK_CURRANT, font_name=FONT_DISPLAY)
        _add_text(slide, x + Inches(0.3), y + Inches(1.65),
                  col_w - Inches(0.5), Inches(0.9),
                  step.get("description", "")[:200],
                  font_size=11, color=GREY, font_name=FONT_BODY)
        # When-badge
        _add_rect(slide, x + Inches(0.3), y + cell_h - Inches(0.55),
                  col_w - Inches(0.6), Emu(15000), ALU_GREY)
        _add_text(slide, x + Inches(0.3), y + cell_h - Inches(0.45),
                  col_w - Inches(0.6), Inches(0.3),
                  step.get("when", "").upper(), font_size=10, bold=True,
                  color=BLACK_CURRANT, font_name=FONT_BODY)


def _slide_contact(prs, ctx):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, BLACK_CURRANT)
    _add_slide_header(slide, "Kontakt", dark=True)

    _add_text(slide, MARGIN, Inches(1.5), Inches(8), Inches(0.4),
              "LAD OS TAGE NÆSTE SKRIDT",
              font_size=11, bold=True, color=KIWI, font_name=FONT_BODY)
    _add_text(slide, MARGIN, Inches(1.95), Inches(7), Inches(1.6),
              "Vi glæder os til at høre fra jer.",
              font_size=44, bold=True, color=WHITE, font_name=FONT_DISPLAY)

    # 2 kontakt-kort
    kam = ctx["team"]["kam"]
    rm = ctx["team"]["rm"]
    contacts = [
        ("DIN KEY ACCOUNT MANAGER", kam, KIWI),
        ("DIN RESOURCE MANAGER", rm, RASPBERRY),
    ]
    card_w = Inches(5.5)
    card_x = SLIDE_W - card_w - MARGIN
    card_y = Inches(2.0)
    card_h = Inches(2.3)
    for i, (role_label, person, accent) in enumerate(contacts):
        y = card_y + i * (card_h + Inches(0.1))
        _add_rect(slide, card_x, y, Emu(40000), card_h, accent)
        _add_rect(slide, card_x + Emu(40000), y,
                  card_w - Emu(40000), card_h,
                  RGBColor(0x25, 0x25, 0x70))
        _add_text(slide, card_x + Inches(0.3), y + Inches(0.25),
                  card_w - Inches(0.5), Inches(0.3),
                  role_label, font_size=10, bold=True, color=accent,
                  font_name=FONT_BODY)
        _add_text(slide, card_x + Inches(0.3), y + Inches(0.6),
                  card_w - Inches(0.5), Inches(0.5),
                  person.get("name", "[Navn]"), font_size=22, bold=True,
                  color=WHITE, font_name=FONT_DISPLAY)
        _add_text(slide, card_x + Inches(0.3), y + Inches(1.1),
                  card_w - Inches(0.5), Inches(0.3),
                  f"{person.get('title', '')} · Epico DK",
                  font_size=11,
                  color=RGBColor(0xAA, 0xAA, 0xBB),
                  font_name=FONT_BODY)
        _add_text(slide, card_x + Inches(0.3), y + Inches(1.5),
                  card_w - Inches(0.5), Inches(0.7),
                  f"T: {person.get('phone', '')}\nM: {person.get('email', '')}",
                  font_size=11, color=WHITE, font_name=FONT_BODY)


# ============================================================
# MAIN RENDERER
# ============================================================

def render_pptx(
    client_name: str,
    analysis: Dict[str, Any],
    meeting: Optional[Dict[str, str]] = None,
    team: Optional[Dict[str, Dict[str, str]]] = None,
    included_slides: Optional[List[str]] = None,
) -> bytes:
    """
    Generér et komplet pitch deck som .pptx fil.
    Returnerer bytes klar til at gemme / serve via HTTP.
    """
    meeting = meeting or {}
    team = team or {}
    if included_slides is None:
        included_slides = [
            "epico_intro_chapter", "epico_stats", "it_market", "epico_dna",
            "services_chapter", "epic_process", "case_study",
        ]

    ctx = {
        "client": {"name": client_name},
        "meeting": {
            "date": meeting.get("date") or "—",
            "city": meeting.get("city") or "—",
            "contact_person": meeting.get("contact_person") or "—",
        },
        "team": {
            "kam": {
                "name": (team.get("kam") or {}).get("name") or "[Navn]",
                "title": (team.get("kam") or {}).get("title") or "Senior Key Account Manager",
                "phone": (team.get("kam") or {}).get("phone") or "+45 00 00 00 00",
                "email": (team.get("kam") or {}).get("email") or "[navn]@epico.dk",
            },
            "rm": {
                "name": (team.get("rm") or {}).get("name") or "[Navn]",
                "title": (team.get("rm") or {}).get("title") or "Resource Manager",
                "phone": (team.get("rm") or {}).get("phone") or "+45 00 00 00 00",
                "email": (team.get("rm") or {}).get("email") or "[navn]@epico.dk",
            },
        },
        "research_facts": analysis.get("research_facts", []),
        "strategic_priorities": analysis.get("strategic_priorities", []),
        "value_mappings": analysis.get("value_mappings", []),
        "service_slides": analysis.get("service_slides", []),
        "next_steps": analysis.get("next_steps", []),
        "case": analysis.get("case_recommendation", {}),
        "industry_tag": analysis.get("industry_tag", "branchen"),
    }

    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    # Slide-rækkefølge (samme som HTML-template)
    _slide_cover(prs, ctx)
    _slide_agenda(prs, ctx)
    _slide_research(prs, ctx)
    _slide_priorities(prs, ctx)
    _slide_mapping(prs, ctx)

    if "epico_intro_chapter" in included_slides:
        _slide_divider(prs, "02", "Dette er Epico.")
    if "epico_stats" in included_slides:
        _slide_epico_stats(prs, ctx)
    if "it_market" in included_slides:
        _slide_market(prs, ctx)
    if "epico_dna" in included_slides:
        _slide_dna(prs, ctx)
    if "services_chapter" in included_slides:
        _slide_divider(prs, "03", "Det vi leverer.", red=True)

    # Dynamiske service-slides
    service_slides = ctx["service_slides"]
    for i, s in enumerate(service_slides, start=1):
        _slide_service(prs, s, i, len(service_slides))

    if "case_study" in included_slides and ctx["case"]:
        _slide_case(prs, ctx)

    _slide_next_steps(prs, ctx)
    _slide_contact(prs, ctx)

    # Skriv til bytes
    out = BytesIO()
    prs.save(out)
    out.seek(0)
    return out.read()
