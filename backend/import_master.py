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

DECK_DIR = Path(__file__).parent / "master_deck"

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


def import_master(source: Path) -> dict:
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

    slides_dir = DECK_DIR / "slides"
    assets_dir = DECK_DIR / "assets"
    for d in (slides_dir, assets_dir):
        d.mkdir(parents=True, exist_ok=True)
        for old in d.iterdir():
            old.unlink()

    # Assets — gemmes under deres uuid så slide-markup kan bruges urørt
    runtime_js = None
    for uuid, meta in assets.items():
        raw = base64.b64decode(meta["data"])
        if meta.get("compressed") in (True, "True"):
            raw = gzip.decompress(raw)
        if meta["mime"] == "text/javascript":
            runtime_js = raw
            continue
        ext = _EXT.get(meta["mime"], "bin")
        (assets_dir / f"{uuid}.{ext}").write_bytes(raw)

    if runtime_js:
        (DECK_DIR / "runtime.js").write_bytes(runtime_js)

    # Head-CSS: font-faces + animationsregler, i dokumentrækkefølge
    head = template.split("<section", 1)[0]
    css_blocks = [
        m.group(1).strip()
        for m in re.finditer(r"<style>(.*?)</style>", head, re.S)
    ]
    (DECK_DIR / "head.css").write_text("\n\n".join(css_blocks), encoding="utf-8")

    # Slides: én fil pr. <section>, nummereret i deck-rækkefølge
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
    (DECK_DIR / "source.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return info


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    result = import_master(Path(sys.argv[1]))
    print(f"Importerede {result['slide_count']} slides fra {result['source_file']}:")
    for i, label in enumerate(result["labels"], 1):
        print(f"  {i:02d}  {label}")
