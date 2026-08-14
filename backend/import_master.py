"""Importér Benjamins master-deck fra en "bundler"-HTML-fil.

Masterdecket vedligeholdes som én selvudpakkende HTML-fil (eksporteret
fra deck-værktøjet). Denne kommando pakker den ud i backend/master_deck/
så composeren kan plukke slides fra den:

    master_deck/
      slides/NN-Label.html   én <section> pr. slide, urørt markup
      assets/<uuid>.<ext>    billeder + fonte, refereret ved uuid i markup
      head.css               @font-face + animations-CSS fra filens <head>
      runtime.js             deck-stage vieweren (navigation, rail, print)
      source.json            metadata om importen

Brug:  python import_master.py "/sti/til/Epico Salgsdeck.html"

Kør den igen når der kommer en ny masterfil — alt overskrives. Slide-
metadata (kapitler/services/længder) ligger i master_deck.py's MANIFEST
og skal kun justeres hvis der kommer nye slides til eller labels ændres.
"""
from __future__ import annotations

import base64
import gzip
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from master_deck import MANIFEST

DECK_DIR = Path(__file__).parent / "master_deck"

# Masterdecket findes i én mappe pr. sprog — master_deck/da, master_deck/en.
LANGS = ("da", "en")

_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/svg+xml": "svg",
    "font/woff2": "woff2",
    "text/javascript": "js",
}


def _block(html: str, kind: str) -> str | None:
    m = re.search(rf'<script type="__bundler/{kind}">(.*?)</script>', html, re.S)
    return m.group(1).strip() if m else None


def import_master(source: Path, lang: str) -> dict:
    html = source.read_text(encoding="utf-8")
    manifest_raw = _block(html, "manifest")
    template_raw = _block(html, "template")
    if not manifest_raw or not template_raw:
        raise SystemExit(
            "Filen ligner ikke en bundler-eksport (mangler __bundler/manifest "
            "eller __bundler/template)."
        )

    assets: dict = json.loads(manifest_raw)
    template: str = json.loads(template_raw)

    out = DECK_DIR / lang
    slides_dir = out / "slides"
    assets_dir = out / "assets"
    for d in (slides_dir, assets_dir):
        d.mkdir(parents=True, exist_ok=True)
        for old in d.iterdir():
            old.unlink()

    # Assets — gemmes under deres uuid så slide-markup kan bruges urørt.
    # Eksporten indeholder flere JavaScript-assets (React, design-system,
    # editor-runtime) som kun redigeringsværktøjet bruger — slides er ren
    # statisk markup. Det eneste script decket behøver er deck-stage-vieweren:
    # den kendes på at den registrerer custom-elementet.
    js_assets = []
    for uuid, meta in assets.items():
        raw = base64.b64decode(meta["data"])
        if meta.get("compressed") in (True, "True"):
            raw = gzip.decompress(raw)
        if "javascript" in meta["mime"]:
            js_assets.append(raw)
            continue
        ext = _EXT.get(meta["mime"], "bin")
        (assets_dir / f"{uuid}.{ext}").write_bytes(raw)

    runtime_js = next(
        (js for js in js_assets
         if b"define('deck-stage'" in js or b'define("deck-stage"' in js),
        None,
    )
    if runtime_js is None and len(js_assets) == 1:
        runtime_js = js_assets[0]
    if runtime_js:
        (out / "runtime.js").write_bytes(runtime_js)
    (out / "extra.js").unlink(missing_ok=True)

    # Head-CSS: font-faces + animationsregler, i dokumentrækkefølge
    head = template.split("<section", 1)[0]
    css_blocks = [
        m.group(1).strip()
        for m in re.finditer(r"<style>(.*?)</style>", head, re.S)
    ]
    (out / "head.css").write_text("\n\n".join(css_blocks), encoding="utf-8")

    # Slides: én fil pr. <section>, nummereret i deck-rækkefølge.
    # Eksporten HTML-serialiserer camelCase-SVG-attributter som
    # "sc-camel-view-box" o.l. og lader sin runtime gendanne dem i browseren.
    # Vi renderer slides statisk, så vi gendanner dem her i stedet — uden
    # viewBox tegnes fx Epico-logoet som en massiv farvet boks.
    def _restore_camel(m: re.Match) -> str:
        first, *rest = m.group(1).split("-")
        return first + "".join(w.capitalize() for w in rest)

    template = re.sub(r"sc-camel-([a-z-]+)", _restore_camel, template)

    sections = re.findall(r"<section .*?</section>", template, re.S)
    labels = []
    for i, section in enumerate(sections, 1):
        label = re.search(r'data-label="([^"]*)"', section)
        name = label.group(1) if label else f"slide-{i}"
        labels.append(name)
        safe = re.sub(r"[^\w\næøåÆØÅ-]", "_", name)
        (slides_dir / f"{i:02d}-{safe}.html").write_text(section, encoding="utf-8")

    info = {
        "source_file": source.name,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "slide_count": len(sections),
        "labels": labels,
        "assets": {u: m["mime"] for u, m in assets.items()},
    }
    (out / "source.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return info


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    lang = next((f.split("=", 1)[1] for f in flags if f.startswith("--lang=")), None)

    if len(args) != 1 or lang not in LANGS:
        print("Brug: python import_master.py <fil.html> --lang=da|en")
        print()
        print("Masterdecket importeres pr. sprog. Sælgeren vælger sprog i composeren,")
        print("og både Epico-slidesne og AI'ens kundeslides følger valget.")
        sys.exit(1)

    result = import_master(Path(args[0]), lang)
    print(f"Importeret til master_deck/{lang}/: "
          f"{result['slide_count']} slides, {len(result['assets'])} assets")

    expected = len([s for s in MANIFEST])
    if result["slide_count"] != expected:
        print()
        print(f"ADVARSEL: masterfilen har {result['slide_count']} slides, men MANIFEST "
              f"forventer {expected}.")
        print("Slide-numrene styrer hvad der vises hvor, så en anden rækkefølge eller")
        print("et andet antal betyder at MANIFEST i master_deck.py skal rettes til.")
